"""Paper check parser: MICR line (routing/account/check #) + amount, date, bank, payer, payee.
Works on a phone photo of a check or a full scanned page with a check and its remittance stub."""
import re, datetime
from collections import Counter
import cv2
from rapidfuzz import fuzz
from .ocr import ocr, h_, cy_, norm
from .common import MONEY, DATE, LONGDATE, ZIPLINE, money_items, aba_ok, repair_aba, parse_written, customer_name, parse_date

def band_variants(img, item, pad_f=0.8):
    """Re-OCR one horizontal band with different preprocessing. Lazy so callers can stop early."""
    h = h_(item); pad = int(h * pad_f)
    y0, y1 = max(0, int(item["y0"]) - pad), min(img.shape[0], int(item["y1"]) + pad)
    band = img[y0:y1, :]
    def mk():
        yield band, 1
        g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        yield cv2.cvtColor(cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], cv2.COLOR_GRAY2BGR), 1
        yield cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), 2
    for im, sc in mk():
        cy = (cy_(item) - y0) * sc
        its = [i for i in ocr(im) if abs(cy_(i) - cy) < 0.9 * h * sc]
        yield " ".join(i["t"] for i in sorted(its, key=lambda i: i["x0"]))

# Letters the OCR engine reads for E-13B MICR digits (it isn't trained on that font): 5 -> s, 4 -> t/h, 0 -> o, 1 -> i/l.
MICR_LOOKALIKE = str.maketrans({"s": "5", "S": "5", "t": "4", "h": "4", "o": "0", "O": "0", "i": "1", "l": "1", "I": "1", "|": "1"})

def micr_digits(t):
    """Map look-alike letters to digits inside the digit runs of a MICR read ('g11t91s447' -> 'g114915447').
    Only tokens that are mostly digits are touched, so words like 'Authorized' stay as they are."""
    out = []
    for tok in t.split():
        core = re.sub(r"[^0-9A-Za-z|]", "", tok)
        n = sum(c.isdigit() for c in core)
        out.append(tok.translate(MICR_LOOKALIKE) if n >= 2 and n >= 0.5 * len(core) else tok)
    return " ".join(out)

def parse_micr(texts, printed_nums, known=()):
    """texts: one MICR line read several ways -> (routing, account, on-us tokens before routing, note).
    known: routing numbers already seen (learned banks, other checks in the batch) used to repair a dropped digit."""
    from rapidfuzz.distance import Levenshtein
    votes, info = Counter(), {}
    mapped = [m for m in (micr_digits(t) for t in texts) if m not in texts]
    weight = [1.0] * len(texts) + [0.6] * len(mapped)       # look-alike repairs count, but less than clean reads
    texts = list(texts) + mapped
    for vi, t in enumerate(texts):
        toks = re.findall(r"\d+", t)
        for ti, tok in enumerate(toks):
            cands = []
            if len(tok) == 9 and aba_ok(tok): cands.append((tok, 2))
            elif len(tok) >= 10:      # MICR symbols read as extra 1s, or the whole line read as one run of digits
                last = ti == len(toks) - 1
                for off in range(len(tok) - 8):
                    if aba_ok(tok[off:off + 9]):
                        extra = tok[:off] + tok[off + 9:]
                        w = 1.0 + (0.6 if len(extra) <= 3 and set(extra) <= {"1"} else 0) - (0.7 if last else 0)
                        cands.append((tok[off:off + 9], w))
            for k in known:          # one digit dropped / added / misread against a routing number we trust
                for L in (8, 9, 10):
                    for off in range(0, max(0, len(tok) - L) + 1):
                        if Levenshtein.distance(tok[off:off + L], k) <= 1: cands.append((k, 2.5)); break
            for c, v in cands:
                votes[c] += v * weight[vi]; info.setdefault(c, (vi, ti))
    for p in printed_nums:
        if len(p) == 9 and aba_ok(p) and votes: votes[p] += 1
    note = None
    if votes:
        routing = votes.most_common(1)[0][0]
    else:
        routing = None
        for t in texts:
            for tok in re.findall(r"\d{9}", t):
                fixed = repair_aba(tok)
                if fixed: routing, note = fixed, f"Routing number was corrected from {tok} using the checksum. Verify."; break
            if routing: break
        if not routing: return None, None, None, None
    acc, pre, best_len = None, [], -1
    for vi, t in enumerate(texts):
        toks = re.findall(r"\d+", t)
        idx = next((k for k, tok in enumerate(toks) if tok == routing), None)
        if idx is None:     # routing embedded in a longer run (or read with one digit dropped): split it out
            from rapidfuzz.distance import Levenshtein
            for k, tok in enumerate(toks):
                o, L = tok.find(routing), 9
                if o < 0 and len(tok) >= 8:
                    spans = [(Levenshtein.distance(tok[a:a + n], routing), a, n) for n in (8, 9, 10) for a in range(0, len(tok) - n + 1)]
                    d, a, n = min(spans) if spans else (9, 0, 0)
                    if d <= 1: o, L = a, n
                if o >= 0 and len(tok) > 9:
                    toks = toks[:k] + [x for x in (tok[:o], routing, tok[o + L:]) if x] + toks[k + 1:]
                    idx = toks.index(routing); break
        if idx is None: continue
        p_ = toks[:idx]
        post = [x for x in toks[idx + 1:] if len(x) >= 3]
        if not post: continue
        if len("".join(p_)) > best_len:
            best_len = len("".join(p_)); pre = p_
            joined = "".join(post)
            acc = joined if len(joined) <= 17 else post[0]
    return routing, acc, pre, note

def printed_numbers(items):
    """Digit runs printed on the document, ignoring money, dates, phone numbers and bank fractions."""
    out = []
    for i in items:
        if MONEY.search(i["t"]): continue
        t = DATE.sub(" ", i["t"].replace(" ", ""))
        t = re.sub(r"\(?\d{3}\)?[\s.-]?\d{3}-\d{4}|\d{2}-\d{2,4}/\d{3,4}", " ", t)
        out += re.findall(r"\d+", t)
    return out

def find_micr(img, items, known=()):
    """Locate and read the MICR line. Candidates holding a checksum-valid routing number are tried first."""
    printed = printed_numbers(items)
    digit_items = [i for i in items if sum(c.isdigit() for c in i["t"]) >= 7 and not re.search(r"[A-Za-z]{3}", i["t"])
                   and not MONEY.search(i["t"]) and not DATE.search(i["t"])]
    def has_aba(i):
        d = re.sub(r"\D", " ", i["t"])
        return any(aba_ok(tok[o:o + 9]) for tok in d.split() if len(tok) >= 9 for o in range(len(tok) - 8))
    from rapidfuzz.distance import Levenshtein
    def near_known(i):
        d = re.sub(r"\D", "", i["t"])
        return any(Levenshtein.distance(d[o:o + 9], k) <= 1 for k in known for o in range(0, max(1, len(d) - 7)))
    digit_items.sort(key=lambda i: (not (has_aba(i) or near_known(i)), -sum(c.isdigit() for c in i["t"])))
    seen_y = []
    for i in digit_items[:6]:
        if any(abs(cy_(i) - y) < h_(i) for y in seen_y): continue
        seen_y.append(cy_(i))
        t = [i["t"]]
        for v in band_variants(img, i):
            t.append(v)
            r, a, pre, note = parse_micr(t, printed, known)
            if r and a and len(t) >= 2: break
        if r:
            line = [j for j in items if abs(cy_(j) - cy_(i)) < 0.8 * max(h_(i), 10) and j["x1"] <= i["x0"] + 5
                    and not re.search(r"[A-Za-z]{2}", j["t"])]
            onus = "".join(re.findall(r"\d", " ".join(j["t"] for j in sorted(line, key=lambda j: j["x0"]))))
            return dict(routing=r, account=a, pre=pre, onus=onus, note=note, y=cy_(i), printed=printed)
    return scan_for_micr(img, items, printed, known)

def scan_for_micr(img, items, printed, known=()):
    """Fallback when the page OCR never boxed the MICR line (it happens on angled phone photos and depends on
    the OCR version): walk strips below the written amount line and re-read each one enlarged."""
    H, Wd = img.shape[:2]
    hs = sorted(h_(i) for i in items if len(i["t"]) >= 4)
    th = max(12, hs[len(hs) // 2] if hs else 20)
    anchors = [i for i in items if re.search(r"DOLLARS|DOLLAR", i["t"], re.I) or parse_written(i["t"])]
    if not anchors: anchors = [i for i in items if "$" in i["t"] and MONEY.search(i["t"].replace(" ", ""))]
    start = (min(cy_(a) for a in anchors) + th) if anchors else 0.25 * H
    stop = min(H, start + 0.45 * Wd)
    band_h, step = int(2.8 * th), max(8, int(1.3 * th))
    y = int(start)
    while y < stop:
        y0, y1 = max(0, y - band_h // 2), min(H, y + band_h // 2)
        band = cv2.resize(img[y0:y1, :], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        its = ocr(band)
        text = " ".join(i["t"] for i in sorted(its, key=lambda i: i["x0"]))
        if sum(c.isdigit() for c in text) >= 12:
            r, a, pre, note = parse_micr([text], printed, known)
            if r and a:
                return dict(routing=r, account=a, pre=pre, onus="", note=note, y=float(y), printed=printed)
        y += step
    return None

FRACTION = re.compile(r"(?<!\d)\d{2}-\d{2,4}/\d{3,4}(?!\d)")      # ABA fraction printed on every check, e.g. 88-2299/1113

def looks_like_check(items):
    raw = " ".join(i["t"] for i in items); t = norm(raw)
    if "YOUJUSTGOTPAID" in t or "QUOTE" in t[:200]: return False
    return bool(FRACTION.search(raw)) or any(k in t for k in ("PAYTOTHE", "ORDEROF", "DOLLARS", "AUTHORIZEDSIGNATURE"))

def _corner_number(items, width):
    """The check number printed on its own in the upper right of a check (e.g. '070552')."""
    pay = [i for i in items if re.search(r"PAY|ORDER\s*OF", i["t"], re.I)]
    lim = min(i["y0"] for i in pay) if pay else float("inf")
    c = [i for i in items if re.fullmatch(r"\s*(?:N[O0]\.?|#)?\s*\d{3,10}\s*", i["t"]) and i["x0"] > 0.55 * width and i["y1"] <= lim]
    if not c: return None
    i = min(c, key=lambda i: i["y0"])
    return re.sub(r"\D", "", i["t"]).lstrip("0") or None

def _check_bottom(items):
    """Where the check ends when its MICR line can't be read: just below the signature / memo line."""
    marks = [i for i in items if re.search(r"SIGNATURE|AUTHORI[ZS]ED|MEMO|^\s*FOR\b", i["t"], re.I)]
    return max(i["y1"] for i in marks) + 3 * h_(marks[0]) if marks else float("inf")

def parse_check(img, items, reg, received=None, batch_routings=(), partial=False):
    """-> (fields, warns) or None when no MICR line is found.
    partial: still read amount, date, check #, payer and payee when the MICR line is unreadable (routing and account
    are left for a person to type)."""
    known = set(reg.banks().keys()) | set(batch_routings)
    micr = find_micr(img, items, known)
    if not micr:
        if not partial: return None
        micr = dict(routing=None, account=None, pre=[], onus="", note=None, y=_check_bottom(items), printed=printed_numbers(items))
    F, warns = {"method": "check"}, {}
    routing, acct = micr["routing"], micr["account"]
    if routing: F["routing"] = routing
    else: warns["routing"] = "The bank line at the bottom of the check couldn't be read. Type the routing number from the image."
    if micr["note"]: warns["routing"] = micr["note"]
    printed = micr["printed"]
    if acct:
        from rapidfuzz.distance import Levenshtein
        corro = [p for p in printed if len(p) >= 6 and acct.startswith(p)]
        near = [p for p in printed if len(p) >= 7 and p != routing and Levenshtein.distance(p, acct) <= 2 and abs(len(p) - len(acct)) <= 2]
        if corro: acct = max(corro, key=len)
        elif near:      # e.g. the stub prints 'Bank #2513075935' and the MICR read dropped a digit
            acct = max(near, key=lambda p: (printed.count(p), len(p)))
            warns["account"] = "MICR read differed slightly; used the account number printed on the stub. Verify."
        else: warns["account"] = "Read from the MICR line only. Verify the digits."
        F["account"] = acct
    elif routing:
        warns["account"] = "Account number not found."
    else:
        warns["account"] = "Type the account number from the bank line. It is how the customer is recognized next time."

    # The check itself is the region above the MICR line; a remittance stub may sit below it.
    top = [i for i in items if cy_(i) <= micr["y"] + 5]
    below = [i for i in items if cy_(i) > micr["y"] + 5]

    # amount: the '$' box on the check, else the amount repeated most on check + stub
    mi = [(i, v) for i, v in money_items(top) if v > 0]
    withd = [(i, v) for i, v in mi if "$" in i["t"] or "*" in i["t"]]
    allm = Counter(v for _, v in money_items(items) if v > 0)
    amount, amt_item = None, None
    if withd: amt_item, amount = max(withd, key=lambda x: (allm[x[1]], x[1]))
    elif allm: amount = max(allm, key=lambda v: (allm[v], v))
    if amount is not None:
        F["amount"] = f"{amount:.2f}"
        written = None
        for t in [i["t"] for i in top] + (list(band_variants(img, amt_item, 0.6))[:2] if amt_item and allm[amount] < 2 else []):
            wv = parse_written(t)
            if wv is None: continue
            written = wv
            if abs(wv - amount) < 0.005: break
        if not (written is not None and abs(written - amount) < 0.005) and allm[amount] < 2:
            warns["amount"] = (f"Written amount reads {written:,.2f}, which doesn't match. Verify." if written is not None
                               else "Could not cross-check the amount. Verify.")
    else:
        warns["amount"] = "Amount not found."

    # check number: on-us field of the MICR line, confirmed by the number printed on the check / stub
    pre_join = "".join(micr["pre"]) + "|" + micr.get("onus", "")
    pre_join = pre_join if len(pre_join.replace("|", "")) >= 3 else ""
    skip = {routing, acct, (F.get("amount") or "").replace(".", "")}
    micr_toks = set(micr["pre"]) | {micr.get("onus", "")}
    pc = Counter(p.lstrip("0") for p in printed if 2 <= len(p.lstrip("0")) <= 6 and p not in skip and p not in micr_toks and p.lstrip("0"))
    best, bs = None, 0
    for p, c in pc.items():
        sc = c + (4 if pre_join and p in pre_join else 0) + (1 if len(p) >= 4 else 0)
        if sc > bs: best, bs = p, sc
    from rapidfuzz.distance import Levenshtein
    digits_pre = re.sub(r"\D", "", pre_join)
    def near(pn):      # printed number vs. the MICR on-us digits: equal, or one OCR slip apart
        return any(Levenshtein.distance(pn, digits_pre[o:o + n]) <= 1
                   for n in (len(pn) - 1, len(pn), len(pn) + 1) if n > 0 for o in range(0, max(1, len(digits_pre) - n + 1)))
    close = [p for p in pc if len(p) >= 3 and near(p)] if digits_pre else []
    if best and pre_join and best in pre_join:
        F["check_no"] = best
    elif close:
        F["check_no"] = max(close, key=lambda p: (pc[p], len(p)))
        warns["check_no"] = "MICR line and printed number differ by one digit; used the printed number. Verify."
    elif pre_join:
        tok = max(micr["pre"] + [micr.get("onus", "")], key=len).lstrip("0")
        tok = re.sub(r"^1(?=0)", "", tok).lstrip("0") if len(tok) > 4 else tok    # leading '1' = on-us symbol
        tok = tok[:-1] if len(tok) > 4 and tok.endswith("1") else tok
        F["check_no"] = tok; warns["check_no"] = "Read from the MICR line only. Verify."
    elif acct and len(acct) > 10:
        # business checks put the serial after the account number: ...account  0055
        tail = acct[-4:].lstrip("0")
        if any(p.lstrip("0") == tail for p in printed) or tail:
            F["check_no"] = tail; F["account"] = acct[:-4]
            warns["check_no"] = "Taken from the end of the MICR line. Verify."
    elif not routing and _corner_number(top, img.shape[1]):
        F["check_no"] = _corner_number(top, img.shape[1]); warns["check_no"] = "Read from the number printed on the check. Verify."
    elif best:
        F["check_no"] = best; warns["check_no"] = "Check number not confirmed by the MICR line."
    else:
        warns["check_no"] = "Check number not found."
    F["payref"] = F.get("check_no", "")

    # date on the check
    for i in sorted(top, key=lambda i: i["y0"]):
        iso = parse_date(i["t"]) if (DATE.search(i["t"].replace(" ", "")) or LONGDATE.search(i["t"])) else None
        if iso:
            try:
                dt = datetime.date.fromisoformat(iso); F["doc_date"] = iso
                ref = datetime.date.fromisoformat(received) if received else datetime.date.today()
                age = (ref - dt).days
                if age > 180: warns["doc_date"] = f"Check is dated {age} days before it was received (stale)."
                elif age < -1: warns["doc_date"] = "Check is post-dated."
            except ValueError: pass
            break

    # drawer bank: learned from routing, else a printed '... Bank' line
    b = reg.bank(routing) if routing else None
    if b: F["bank"] = b
    else:
        for i in sorted(top, key=lambda i: i["y0"]):
            if re.search(r"\bBANK\b", i["t"], re.I) and 6 <= len(i["t"].strip()) < 32 and not re.search(r"banking|bank#", i["t"], re.I):
                F["bank"] = i["t"].strip(); break

    # payee division (Magic Valley Concrete, ...) from the pay-to line
    pay = reg.match_payee(" ".join(i["t"] for i in top))
    if pay: F["payee"], F["sheet"] = pay

    # customer (who pays): learned from routing+account, else the printed address block
    known = reg.customer_for_account(routing, F.get("account")) if routing else None
    if known: F["customer"] = known
    else:
        raw = _bill_to(items) or _remitter(top) or _payer_block(top, img.shape[1], F.get("payee", ""))
        if raw and (ZIPLINE.search(raw) or re.match(r"\s*\d+\s", raw)): raw = None
        if raw:
            F["customer_raw"] = raw
            F["customer"] = reg.snap_customer(customer_name(raw))
        warns["customer"] = "New customer. Check the name as it should appear in the sheet." if F.get("customer") else "Customer not found."
    return F, warns

LEGALNAME = re.compile(r"\b(LLC|L\.?L\.?C|INC|CORP|COMPANY|CO\b|CONSTRUCTION|CONTRACTORS?|BUILDERS|HOMES|LTD|LP\b|ENTERPRISES|GROUP)", re.I)
NOT_PAYER = re.compile(r"BANK(?!S)|PAY\s*TO|ORDER|DOLLARS|MEMO|SIGNATURE|VOID|SECURITY|DETAILS", re.I)

def _payer_block(items, width, payee):
    def overlap(a, b): return min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) > -0.02 * width
    def is_payee(text): return bool(payee) and fuzz.partial_ratio(norm(payee), norm(text)) >= 80
    for z in sorted([i for i in items if ZIPLINE.search(i["t"])], key=lambda i: (i["y0"], i["x0"])):
        blk = [z]
        for _ in range(3):
            up = [i for i in items if i not in blk and 0 < blk[0]["y0"] - i["y1"] < 2.4 * h_(z) and overlap(i, blk[0])]
            if not up: break
            blk.insert(0, max(up, key=lambda i: i["y1"]))
        text = " ".join(i["t"] for i in blk)
        if NOT_PAYER.search(text) or is_payee(text): continue
        names = [i for i in blk if not re.match(r"\s*(\d|PO\s*BOX|P\.?O\.?\s)", i["t"], re.I) and not ZIPLINE.search(i["t"])
                 and not re.fullmatch(r"(VENDOR|CHECK|DATE|AMOUNT|PAY|NAME|NO\.?|NUMBER|\s)+", i["t"], re.I)
                 and re.search(r"[A-Za-z]{3}", i["t"])]
        if names: return re.sub(r",(?=\S)", ", ", names[0]["t"].strip())
    # no address block: the first business-looking name near the top of the check
    for i in sorted(items, key=lambda i: (i["y0"], i["x0"])):
        if LEGALNAME.search(i["t"]) and not NOT_PAYER.search(i["t"]) and not is_payee(i["t"]) and re.search(r"[A-Za-z]{3}", i["t"]):
            return re.sub(r",(?=\S)", ", ", i["t"].strip())
    return None

REMITTER = re.compile(r"^\s*(REMITTER|PURCHASER|PURCHASED\s*BY|PURCHASER'?S?\s*NAME|SENDER|FROM)\s*:?\s*", re.I)

def _remitter(items):
    """Cashier's checks and money orders name the payer after 'Remitter:' / 'Purchaser:' instead of an address block."""
    for a in items:
        m = REMITTER.match(a["t"])
        if not m: continue
        rest = a["t"][m.end():].strip()
        if re.search(r"[A-Za-z]{3}", rest): return rest
        h = h_(a)
        near = [i for i in items if i is not a and re.search(r"[A-Za-z]{3}", i["t"]) and not NOT_PAYER.search(i["t"])
                and not parse_date(i["t"]) and not MONEY.search(i["t"]) and not re.search(r"DATE", i["t"], re.I)
                and ((abs(cy_(i) - cy_(a)) < 1.2 * h and i["x0"] > a["x0"]) or (0 < i["y0"] - a["y1"] < 2 * h and abs(i["x0"] - a["x0"]) < 6 * h))]
        if near: return min(near, key=lambda i: max(0, i["x0"] - a["x1"]) + 3 * max(0, i["y0"] - a["y1"]))["t"].strip()
    return None

def _bill_to(items):
    """CAPA statements / quotes stapled behind a check name the customer cleanly under 'Bill To'."""
    for a in items:
        if re.fullmatch(r"\s*Bill\s*To:?\s*", a["t"], re.I):
            below = [i for i in items if 0 < i["y0"] - a["y1"] < 3 * h_(a) and abs(i["x0"] - a["x0"]) < 4 * h_(a)
                     and re.search(r"[A-Za-z]{3}", i["t"])]
            if below: return min(below, key=lambda i: i["y0"])["t"].strip()
    return None
