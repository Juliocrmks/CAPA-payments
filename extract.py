"""Local check extraction (no cloud / no LLM): RapidOCR + MICR parsing + validators."""
import re, datetime
from collections import Counter
import numpy as np, cv2
from PIL import Image, ImageOps
from rapidfuzz import fuzz

_eng = None
def engine():
    global _eng
    if _eng is None:
        from rapidocr_onnxruntime import RapidOCR
        _eng = RapidOCR()
    return _eng

# ---------- helpers ----------
def aba_ok(r):
    return bool(re.fullmatch(r"\d{9}", r or "")) and sum(int(d) * w for d, w in zip(r, [3, 7, 1] * 3)) % 10 == 0

CONF = {"1": "74", "7": "1", "4": "19", "0": "86", "8": "0369", "6": "580", "5": "63", "3": "85", "9": "48", "2": "7"}
def repair_aba(r):
    """Single-digit repair using common OCR confusions. Returns the repaired number only if unique."""
    hits = set()
    for i, d in enumerate(r):
        for c in CONF.get(d, ""):
            t = r[:i] + c + r[i + 1:]
            if aba_ok(t): hits.add(t)
    return hits.pop() if len(hits) == 1 else None

def norm(s): return re.sub(r"[^A-Z0-9]", "", (s or "").upper())
def w_(i): return i["x1"] - i["x0"]
def h_(i): return i["y1"] - i["y0"]
def cy_(i): return (i["y0"] + i["y1"]) / 2

def load_image(data, max_side=2000):
    import io
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    a = np.array(im)[:, :, ::-1].copy()
    s = max_side / max(a.shape[:2])
    return cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else a

ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
def rotate(img, deg): return img if not deg else cv2.rotate(img, ROT[deg])

def ocr(img):
    r, _ = engine()(img)
    return [dict(t=t.strip(), s=float(s), x0=min(p[0] for p in b), y0=min(p[1] for p in b),
                 x1=max(p[0] for p in b), y1=max(p[1] for p in b)) for b, t, s in (r or []) if t.strip()]

# ---------- patterns ----------
MONEY = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?!\d)")
DATE = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?!\d)")
ZIPLINE = re.compile(r"[A-Za-z]\s*,?\s*(?:[A-Z]{2}|Texas|TEXAS)\s*,?\s*\d{5}")

def money_items(items):
    out = []
    for i in items:
        m = MONEY.search(i["t"].replace(" ", ""))
        if m: out.append((i, float(m.group(1).replace(",", "") + "." + m.group(2))))
    return out

# ---------- written amount ----------
W = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
     "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
     "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
WRE = re.compile("|".join(sorted(list(W) + ["hundred", "thousand", "million"], key=len, reverse=True)))
def parse_written(text):
    t = text.lower().replace("fortv", "forty")
    words = WRE.findall(t)
    if len(words) < 2: return None
    total = cur = 0
    for w in words:
        if w in W: cur += W[w]
        elif w == "hundred": cur = (cur or 1) * 100
        elif w == "thousand": total += (cur or 1) * 1000; cur = 0
        elif w == "million": total += (cur or 1) * 1000000; cur = 0
    total += cur
    m = re.search(r"(\d{1,2})\s*/\s*1[0o]{2}", t)
    return total + (int(m.group(1)) / 100 if m else 0)

# ---------- band re-OCR (several preprocessings) ----------
def band_variants(img, item, pad_f=0.8):
    """Generator: re-OCR a horizontal band with different preprocessing (lazy, stop early)."""
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

def parse_micr(texts, printed_nums):
    """texts: line strings from variants. Returns routing, account, onus_tokens, notes."""
    votes, info = Counter(), {}
    for vi, t in enumerate(texts):
        toks = re.findall(r"\d+", t)
        for ti, tok in enumerate(toks):
            cands = []
            if len(tok) == 9 and aba_ok(tok): cands.append((tok, 2))
            elif len(tok) in (10, 11):
                for off in range(len(tok) - 8):
                    if off in (0, len(tok) - 9) and aba_ok(tok[off:off + 9]): cands.append((tok[off:off + 9], 1))
            for c, v in cands:
                votes[c] += v; info.setdefault(c, (vi, ti, toks))
    for p in printed_nums:                       # printed routing number elsewhere on the check
        if len(p) == 9 and aba_ok(p): votes[p] += 2
    note = None
    if votes:
        routing = votes.most_common(1)[0][0]
    else:                                        # try single-digit repair on a 9-digit token
        routing = None
        for t in texts:
            for tok in re.findall(r"\d{9}", t):
                fixed = repair_aba(tok)
                if fixed: routing, note = fixed, f"Routing number was corrected from {tok} using the checksum. Verify."; break
            if routing: break
        if not routing: return None, None, None, None
    acc, pre = None, []
    for vi, t in enumerate(texts):               # prefer the cleanest variant that contains the routing as a token
        toks = re.findall(r"\d+", t)
        idx = next((k for k, tok in enumerate(toks) if tok == routing), None)
        if idx is None and info.get(routing) and info[routing][0] == vi:
            idx = info[routing][1]
        if idx is None: continue
        pre = [x for x in toks[:idx] if len(x) >= 3]
        post = [x for x in toks[idx + 1:] if len(x) >= 3]
        if post:
            joined = "".join(post)
            acc = joined if len(joined) <= 17 else post[0]
            break
    return routing, acc, pre, note

# ---------- main entry ----------
KEYS = ("PAY", "ORDER", "DOLLAR", "DATE", "AMOUNT", "BANK", "MEMO", "SIGNATURE", "CHECK", "VOID")
def upright_ok(items):
    """True/False when we can tell, None when unknown. MICR must sit below the amount."""
    m = [cy_(i) for i, _ in money_items(items) if "$" in i["t"]]
    d = [cy_(i) for i in items if sum(c.isdigit() for c in i["t"]) >= 9 and not re.search(r"[A-Za-z]{2}", i["t"])
         and not MONEY.search(i["t"])]
    if not m or not d: return None
    return max(d) > min(m)

def orient(img):
    small = cv2.resize(img, None, fx=700 / max(img.shape[:2]), fy=700 / max(img.shape[:2])) if max(img.shape[:2]) > 700 else img
    its = [i for i in ocr(small) if len(i["t"]) >= 4]
    vert = sum(1 for i in its if h_(i) > 1.2 * w_(i))
    return [270, 90] if its and vert / len(its) >= 0.4 else [0, 180]

def extract(data, reg):
    """reg: registry with payer(routing,account), payees(), bank(routing). Returns (fields, warns, upright_image)."""
    img0 = load_image(data)
    cands = orient(img0)
    img, items = None, None
    for k, deg in enumerate(cands):
        im = rotate(img0, deg); its = ocr(im)
        ok = upright_ok(its)
        if img is None or ok is not False: img, items = im, its
        if ok is not False: break
        if k == 0: img, items = im, its
    # if first rotation said "upside-down" and second didn't, loop above already switched
    H, Wd = img.shape[:2]
    warns, F = {}, dict(payer="", payee="", sheet="", bank="", routing="", account="", check="", amount="", date="", ticket="", taxable="No")

    # --- amount (numeric + written cross-check)
    mi = money_items(items)
    amt_item, amount = None, None
    if mi:
        cnt = Counter(v for _, v in mi)
        withd = [(i, v) for i, v in mi if "$" in i["t"]]
        amt_item, amount = (withd[0] if withd else max(mi, key=lambda x: (cnt[x[1]], x[1])))
        if cnt[amount] < 2 or withd:
            amount = amount
    if amount is not None:
        F["amount"] = f"{amount:.2f}"
        written = None
        def scan(texts):
            nonlocal written
            for t in texts:
                wv = parse_written(t)
                if wv is not None:
                    if abs(wv - amount) < 0.005: written = wv; return True
                    written = written if written is not None else wv
            return False
        if not scan(i["t"] for i in items):
            for t in band_variants(img, amt_item, 0.6):
                if scan([t]): break
        if written is None or abs(written - amount) >= 0.005:
            warns["amount"] = (f"Written amount reads {written:,.2f}, which doesn't match. It may be cut off in the photo. Verify."
                               if written is not None else "Could not cross-check against the written amount. Verify.")
    else:
        warns["amount"] = "Amount not found."

    # --- MICR
    printed = [t for i in items for t in re.findall(r"\d+", i["t"]) if not MONEY.search(i["t"])]
    digit_items = sorted([i for i in items if sum(c.isdigit() for c in i["t"]) >= 5 and not re.search(r"[A-Za-z]{3}", i["t"])
                          and not MONEY.search(i["t"]) and not DATE.search(i["t"])], key=lambda i: -cy_(i))
    texts, seen_y = [], []
    for i in digit_items:
        if any(abs(cy_(i) - y) < h_(i) for y in seen_y): continue
        seen_y.append(cy_(i))
        t = []; r = None
        for v in band_variants(img, i):
            t.append(v)
            if len(t) >= 2:
                r, a, pre, note = parse_micr(t, printed)
                if r: break
        if not r: continue
        if r and pre is not None and (a or len(texts) == 0):
            texts = t; routing, acct, pre_, rnote = r, a, pre, note; break
    else:
        routing = acct = pre_ = rnote = None
    if routing:
        F["routing"] = routing
        if rnote: warns["routing"] = rnote
    else:
        warns["routing"] = "Routing number not found. Retake the photo or type it."
    if acct:
        corro = [p for p in printed if len(p) >= 6 and acct.startswith(p)]
        if corro: acct = max(corro, key=len)
        else: warns["account"] = "Read from the MICR line only. Verify the digits."
        F["account"] = acct
    elif routing:
        warns["account"] = "Account number not found."

    # --- check number
    micr_tok = pre_[-1] if pre_ else ""
    skip = {routing, acct, F["amount"].replace(".", "")}
    pc = Counter(p for p in printed if 3 <= len(p) <= 10 and p not in skip and not (len(p) == 3 and p.startswith("0")))
    best, bs = None, 0
    for p, c in pc.items():
        sc = c + (3 if micr_tok and micr_tok.endswith(p) else 0) + (1 if len(p) >= 4 else 0)
        if sc > bs: best, bs = p, sc
    if best and (not micr_tok or micr_tok.endswith(best)): F["check"] = best
    elif micr_tok:
        F["check"] = micr_tok.lstrip("1").lstrip("0") if micr_tok.startswith("1") and len(micr_tok) > 6 else micr_tok.lstrip("0")
        warns["check"] = "Read from the MICR line only. Verify."
    elif best: F["check"] = best; warns["check"] = "Check number not confirmed by the MICR line."
    else: warns["check"] = "Check number not found."

    # --- date
    dates = [(i, m) for i in items for m in [DATE.search(i["t"].replace(" ", ""))] if m]
    if dates:
        i, m = dates[0]
        mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = y[-2:]
        if 1 <= mo <= 12 and 1 <= d <= 31:
            F["date"] = f"{mo:02d}/{d:02d}/{y}"
            try:
                dt = datetime.date(2000 + int(y), mo, d); age = (datetime.date.today() - dt).days
                if age > 180: warns["date"] = f"Check is dated {age} days ago (stale)."
                elif age < -1: warns["date"] = "Check is post-dated."
            except ValueError: warns["date"] = "Invalid date."
        else: warns["date"] = "Date looks wrong. Verify."
    else: warns["date"] = "Date not found."

    # --- bank
    if routing and reg.bank(routing): F["bank"] = reg.bank(routing)
    else:
        for i in sorted(items, key=lambda i: i["y0"]):
            m = re.search(r"([A-Za-z&. ]{0,20}?)\s*BANK\b", re.sub(r"(?<=[a-z])BANK|(?<=[A-Z])BANK", " BANK", i["t"]), re.I)
            if m and "ing" not in i["t"].lower().split("bank")[-1][:3] and len(i["t"]) < 28:
                F["bank"] = i["t"].strip(); break
        if not F["bank"]: warns["bank"] = "Bank not recognized. Type the bank name."

    # --- payee: known list first, then 'pay to the order of' anchor
    payee_name = ""
    best = (0, None)
    for name, sheet in reg.payees():
        n = norm(name)
        hits = [i for i in items if len(norm(i["t"])) >= 6 and fuzz.partial_ratio(n, norm(i["t"])) >= 88]
        if hits and len(hits) > best[0]: best = (len(hits), (name, sheet))
    if best[1]:
        payee_name, F["sheet"] = best[1]; F["payee"] = payee_name
    else:
        anc = next((i for i in items if re.search(r"ORDER|PAY\s*TO", i["t"], re.I)), None)
        if anc:
            c = [i for i in items if i is not anc and re.search(r"[A-Za-z]{4}", i["t"]) and not re.search(r"ORDER|PAYTO|^THE$|DOLLAR|BANK|SIGNATURE|^OF:?$", i["t"], re.I)
                 and ((i["x0"] > anc["x1"] - 10 and abs(cy_(i) - cy_(anc)) < 1.5 * h_(anc)) or (0 < i["y0"] - anc["y1"] < 3 * h_(anc) and abs(i["x0"] - anc["x0"]) < 0.25 * Wd))]
            if c: F["payee"] = min(c, key=lambda i: (i["y0"], i["x0"]))["t"]
        warns["payee"] = "New payee. Pick the sheet it belongs to." if F["payee"] else "Payee not found."
        warns["sheet"] = "Pick the payee sheet."

    # --- payer: registry first, then address-block heuristic
    known = reg.payer(routing, acct) if routing and acct else None
    if known: F["payer"] = known
    else:
        for z in sorted([i for i in items if ZIPLINE.search(i["t"])], key=lambda i: (i["y0"], i["x0"])):
            blk = [z]
            for _ in range(2):
                up = [i for i in items if i not in blk and 0 < blk[0]["y0"] - i["y1"] < 2.2 * h_(z) and abs(i["x0"] - z["x0"]) < 0.06 * Wd]
                if not up: break
                blk.insert(0, max(up, key=lambda i: i["y1"]))
            text = " ".join(i["t"] for i in blk)
            if re.search(r"BANK", text, re.I) or (payee_name and fuzz.partial_ratio(norm(payee_name), norm(text)) >= 85): continue
            name = [i for i in blk if not re.match(r"\s*(\d|PO\s*BOX)", i["t"], re.I) and not ZIPLINE.search(i["t"])
                    and not re.fullmatch(r"(VENDOR|CHECK|DATE|AMOUNT|PAY|NAME|NO\.?|NUMBER|\s)+", i["t"], re.I)]
            if name: F["payer"] = re.sub(r",(?=\S)", ", ", name[0]["t"].strip()); break
        warns["payer"] = "Check the payer name as it should appear in the sheet." if F["payer"] else "Payer not found."
    return F, warns, img

def jpeg(img, q=82):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes()
