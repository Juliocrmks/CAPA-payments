"""Parsers for the non-check documents in a daily packet, plus page classification.

Document kinds seen in real packets:
  sheet         printout of the day's workbook rows (skipped; it is the answer key, not a payment)
  check         paper check, often with a remittance stub          -> method check
  confirmation  TransactPro 'You Just Got Paid!' e-mail            -> card (Visa/MC/Amex...) or ach (CHECKING ****)
  receipt       CAPA receipt slip, red receipt number = TICKET REF  (handwritten amount/name: hints only)
  bankpost      bank screen 'ACH Entry ... Posted Today' / wire    -> wire
  email         e-mail header page for a confirmation              (support)
  sensitive     driver licence / card photos                       (support, image not kept by default)
  support       statements, quotes, bill-payment advices, blank pages
"""
import re
from rapidfuzz import fuzz
import math
from .ocr import norm, cy_, h_, text_of, skew
from .common import money, money_items, parse_date, customer_name, digits_fixed, money_hand

def _same_line(items, label_item, sk=0.0):
    """The value box printed to the right of a label, following the page's skew (scans are rarely straight)."""
    h = max(h_(label_item), 10)
    best, bd = None, 1e9
    for i in items:
        if i is label_item or i["x0"] <= label_item["x1"] - 5: continue
        expect = cy_(label_item) + (((i["x0"] + i["x1"]) / 2) - ((label_item["x0"] + label_item["x1"]) / 2)) * math.tan(sk)
        d = abs(cy_(i) - expect)
        if d < 0.9 * h and d < bd: best, bd = i, d
    return best

def kv(items, pattern, exclude=None):
    """Value printed to the right of a label (two-column layouts like the TransactPro confirmation)."""
    rx = re.compile(pattern, re.I)
    sk = skew(items)
    for i in items:
        t = i["t"].strip()
        if rx.fullmatch(t) and not (exclude and re.search(exclude, t, re.I)):
            v = _same_line(items, i, sk)
            if v: return v["t"].strip()
    return None

CARD = re.compile(r"(VISA|MASTER\s*CARD|MASTERCARD|AMEX|AMERICAN\s*EXPRESS|DISCOVER|DINERS)\D*(\d{4})", re.I)
ACCT = re.compile(r"(CHECKING|SAVINGS|ACH|BANK)\D*(\d{4})", re.I)

def parse_confirmation(items, reg):
    F, W = {}, {}
    pm = kv(items, r"Payment\s*Method") or ""
    m = CARD.search(pm) or CARD.search(text_of(items))
    a = ACCT.search(pm)
    if m and not (a and a.start() < m.start()):
        brand = m.group(1).upper().replace(" ", "")
        F.update(method="card", card_brand={"MASTERCARD": "Mastercard", "AMERICANEXPRESS": "Amex"}.get(brand, brand.title()), last4=m.group(2))
    elif a:
        F.update(method="ach", last4=a.group(2))
    else:
        F["method"] = "card"; W["method"] = "Payment method not read. Pick card or ACH."
    F["payref"] = F.get("last4", "")
    amt = None
    for lab in (r"Total\s*Paid", r"Total", r"Amount"):
        v = kv(items, lab)
        if v and money(v) is not None: amt = money(v); break
    if amt is None:
        W["amount"] = "Amount not found."
    else:
        F["amount"] = f"{amt:.2f}"
    cust = kv(items, r"Customer")
    if cust:
        F["customer_raw"] = cust
        F["customer"] = reg.snap_customer(customer_name(cust))
    else:
        W["customer"] = "Customer not found."
    desc = kv(items, r"Description") or ""
    q = re.search(r"\b(QU?O[A-Z]{0,2}\d{3,6})\b", desc.replace(" ", ""), re.I)
    if q: F["order"] = q.group(1).upper()
    inv = re.search(r"\b(INV[A-Z]{0,3}-?\d{3,6})\b", desc.replace(" ", ""), re.I)
    F["invoice"] = (inv.group(1).upper() if inv else "") or (kv(items, r"Invoice\s*#?") or "").upper()
    ref = kv(items, r"Reference\s*#?")
    if ref: F["confirmation"] = ref.replace(" ", "")
    paid = kv(items, r"Paid")
    if paid and parse_date(paid): F["doc_date"] = parse_date(paid)
    pay = reg.match_payee(text_of(items))
    if pay: F["payee"], F["sheet"] = pay
    return F, W

def receipt_numbers(items):
    """Red serial number printed on CAPA receipt slips (e.g. 035391), tolerant of OCR letter/digit swaps."""
    out = []
    for i in items:
        raw = i["t"].strip()
        if not (5 <= len(raw) <= 8) or re.search(r"[/:$.,]", raw): continue
        fixed = re.sub(r"[^0-9]", "", digits_fixed(raw))
        if len(fixed) == 6 and fixed.startswith("03"):
            out.append((i, fixed.lstrip("0"), fixed != re.sub(r"[^0-9]", "", raw) or len(re.sub(r"[^0-9]", "", raw)) != 6))
    return out

def parse_receipts(items, page_h):
    """A page can hold one or two receipt slips (and sometimes a confirmation below). -> [(fields, warns, top, bottom)]"""
    t = norm(text_of(items))
    if not ("RECEIVEDOF" in t or ("HOWPAID" in t and "CAPA" in t)): return []
    anchors = sorted([i for i in items if re.search(r"RECEIVED\s*OF", i["t"], re.I)], key=cy_)
    if not anchors:      # 'RECEIVED OF' not read: the 'HOW PAID' box only exists on receipt slips (never on statements)
        anchors = sorted([i for i in items if re.search(r"HOW\W*PAID", i["t"], re.I)], key=cy_)
    if not anchors: return []
    enders = sorted([i for i in items if re.search(r"THANK\s*YOU|BALANCE\s*DUE", i["t"], re.I)], key=cy_)
    nums = sorted(receipt_numbers(items), key=lambda x: cy_(x[0]))
    recs, top = [], 0
    for k, anc in enumerate(anchors):
        nxt = cy_(anchors[k + 1]) if k + 1 < len(anchors) else page_h
        ends = [e for e in enders if cy_(anc) < cy_(e) < nxt and cy_(e) - cy_(anc) < 0.45 * page_h]
        bot = (max(cy_(e) for e in ends) + 25) if ends else min(nxt, cy_(anc) + 0.25 * page_h)
        if k + 1 < len(anchors):          # the next slip's header (and its number) sits above its 'RECEIVED OF'
            bot = min(bot, nxt - 1)
        region = [i for i in items if top <= cy_(i) <= bot]
        num = next(((n, fixed) for i, n, fixed in nums if top <= cy_(i) <= bot), None)
        F, W = {"ticket": num[0] if num else ""}, {}
        if not num: W["ticket"] = "Receipt number not read. Type it from the slip."
        elif num[1]: W["ticket"] = "Receipt number was hard to read. Verify."
        def numeric(t):
            core = re.sub(r"(?i)DOLLARS|\$|\s", "", t)
            return len(core) >= 4 and sum(c.isdigit() or c in ".," for c in core) / len(core) >= 0.7
        amts = [money_hand(re.sub(r"(?i)DOLLARS|\$", "", i["t"])) for i in region if numeric(i["t"]) and not re.search(r"\(\d{3}\)|\d{3}-\d{4}|TX", i["t"])]
        amts = [a for a in amts if a and a > 0]
        if amts: F["amount_hint"] = f"{max(amts):.2f}"
        # handwritten name: text in the same OCR box after 'RECEIVED OF', or the nearest box beside it
        rest = re.sub(r"(?i).*RECEIVED\s*OF[\s_:\-]*", "", anc["t"]).strip()
        if len(rest) >= 3: F["customer_hint"] = rest
        else:
            cand = [i for i in region if i is not anc and abs(cy_(i) - cy_(anc)) < 2.5 * max(h_(anc), 10)
                    and re.search(r"[A-Za-z]{3}", i["t"]) and not re.search(r"DOLLAR|CAPA|PALMA|VALLEY|PALMVIEW|CONCRETE|PIPE|MATERIAL|ASPHALT", i["t"], re.I)]
            if cand: F["customer_hint"] = min(cand, key=lambda i: (abs(cy_(i) - cy_(anc)), i["x0"]))["t"]
        recs.append((F, W, top, bot))
        top = bot + 1
    return recs

def parse_bankpost(items, reg):
    F, W = {"method": "wire"}, {}
    amts = [v for _, v in money_items(items) if v > 0]
    if amts: F["amount"] = f"{max(amts):.2f}"
    else: W["amount"] = "Amount not found."
    t = text_of(items)
    m = re.search(r"([A-Z][A-Za-z&\.\- ]{3,40}?)\s+(?:Payment|Pmt|Wire)\b", t)
    if m and not re.search(r"VENDOR|ENTRY|MEMO|POSTED|\bACH\b", m.group(1), re.I):
        F["customer_raw"] = m.group(1).strip()
        F["customer"] = reg.snap_customer(customer_name(F["customer_raw"]))
    else:
        F["memo"] = re.sub(r"\s+", " ", t)[:120]
        learned = reg.customer_for_memo(F["memo"]) if hasattr(reg, "customer_for_memo") else None
        if learned: F["customer"] = learned
        else: W["customer"] = "Bank posting doesn't name the sender. Type the customer."
    return F, W

SENSITIVE = re.compile(r"DRIVER|LICEN[CS]E|\bDOB\b|DATE OF BIRTH|\bCLASS\s*:|HAZMAT|ROADSIDE|VALID\s*THRU|MEMBER\s*SINCE|\bEXP\s*\d{2}/\d{2}|AMERICAN\s*EXPRESS|EXPRES+\b")

def classify(items):
    if len(items) < 2: return "blank"
    raw = text_of(items).upper()
    t = norm(raw)
    if all(k in t for k in ("CUSTOMER", "TICKET", "PAYMENT")) and ("DEPOSIT" in t or "CREDIT" in t): return "sheet"
    if "YOUJUSTGOTPAID" in t or ("PAYMENTMETHOD" in t and ("REFERENCE" in t or "RETREF" in t)): return "confirmation"
    if ("TOTALPAID" in t or "RETREF" in t) and "TRANSACTPRO" in t or ("TOTALPAID" in t and "RETREF" in t): return "confirmation_cont"
    if re.search(r"ACHENTRY|ENTRYMEMO|POSTEDTODAY|WIRETRANSFER|INCOMINGWIRE|VENDORPAY", t) and money_items(items): return "bankpost"
    if SENSITIVE.search(raw) and "PAYMENTMETHOD" not in t: return "sensitive"
    if "PAYMENTCONFIRMATION" in t and "FROM" in t: return "email"
    return "other"

def match_hint(a, b):
    return fuzz.token_set_ratio(norm_words(a), norm_words(b)) if a and b else 0

def norm_words(s): return re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())

def parse_total_paid(items):
    v = kv(items, r"Total\s*Paid")
    return money(v) if v else None
