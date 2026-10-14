"""Shared patterns and validators used by all document parsers."""
import re, datetime

MONEY = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?!\d)")
DATE = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?!\d)")
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
LONGDATE = re.compile(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*(\d{1,2}),?\s*(\d{4})", re.I)
ZIPLINE = re.compile(r"[A-Za-z][\s,.]*(?:[A-Z]{2}|Texas|TEXAS)[\s,.]*\d{5}")

def money(text):
    """First money value in a string, or None. Tolerates '$ **1,234.56' and OCR'd 'O' for zero in cents."""
    t = text.replace(" ", "").replace("$", "")
    t = re.sub(r"(?<=\.\d)[Oo]|(?<=\.)[Oo](?=\d)", "0", t)
    t = re.sub(r"(?<!\d)(\d{1,3})((?:\.\d{3})+)\.(\d{2})(?!\d)", lambda m: m.group(1) + m.group(2).replace(".", ",") + "." + m.group(3), t)
    m = MONEY.search(t)
    return float(m.group(1).replace(",", "") + "." + m.group(2)) if m else None

def money_items(items):
    """Money values, skipping boxes where the match is only a fragment of a garbled number ('14,9(03.01')."""
    out = []
    for i in items:
        v = money(i["t"])
        if v is None: continue
        digits = sum(c.isdigit() for c in i["t"])
        got = len(re.sub(r"\D", "", f"{v:.2f}").lstrip("0") or "0")
        if digits and got / digits < 0.7: continue
        out.append((i, v))
    return out

def aba_ok(r):
    """ABA routing number: 9 digits, valid Federal Reserve prefix, 3-7-1 checksum."""
    if not re.fullmatch(r"\d{9}", r or ""): return False
    p = int(r[:2])
    if not (p <= 12 or 21 <= p <= 32 or 61 <= p <= 72 or p == 80): return False
    return sum(int(d) * w for d, w in zip(r, [3, 7, 1] * 3)) % 10 == 0

CONF = {"1": "74", "7": "1", "4": "19", "0": "86", "8": "0369", "6": "580", "5": "63", "3": "85", "9": "48", "2": "7"}
def repair_aba(r):
    """Single-digit repair using common OCR confusions. Returns the repaired number only if unique."""
    hits = set()
    for i, d in enumerate(r):
        for c in CONF.get(d, ""):
            t = r[:i] + c + r[i + 1:]
            if aba_ok(t): hits.add(t)
    return hits.pop() if len(hits) == 1 else None

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

def parse_date(text):
    """-> ISO 'YYYY-MM-DD' or None. Accepts 10/9/26, 10/09/2026, 'October 9, 2026', 'OCT/09/26'."""
    t = text.replace(" ", "")
    m = DATE.search(t)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = 2000 + int(y) if len(y) == 2 else int(y)
    else:
        m = LONGDATE.search(text) or re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)/(\d{1,2})/(\d{2,4})", text, re.I)
        if not m: return None
        mo, d, y = MONTHS[m.group(1).upper()[:3]], int(m.group(2)), int(m.group(3))
        y = 2000 + y if y < 100 else y
    try: return datetime.date(y, mo, d).isoformat()
    except ValueError: return None

def date_from_filename(name):
    """'MVC OCT_09-26.pdf' -> 2026-10-09."""
    m = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[ _\-.]*(\d{1,2})[ _\-.]+(\d{2,4})", name or "", re.I)
    if not m: return None
    y = int(m.group(3)); y = 2000 + y if y < 100 else y
    try: return datetime.date(y, MONTHS[m.group(1).upper()[:3]], int(m.group(2))).isoformat()
    except ValueError: return None

LEGAL = re.compile(r"[\s,]+(LLC|L\.L\.C\.?|INC\.?|CORP\.?|CO\.?|LTD\.?|LP)$", re.I)
def customer_name(raw):
    """Name as the sheets write it: upper case, no punctuation noise, legal suffix dropped."""
    s = re.sub(r"\s+", " ", (raw or "").replace(".", " ").replace(",", " ")).strip().upper()
    s = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", s); s = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", s)
    s = re.sub(r"^(COD|C O D)[\s\-]+", "", s)          # 'COD-JUAN CANTU' -> 'JUAN CANTU' (cash-on-delivery prefix)
    prev = None
    while prev != s: prev, s = s, LEGAL.sub("", s).strip()
    if " " not in s and len(s) > 8: s = re.sub(r"(LLC|INC|CORP)$", "", s)       # squashed 'JRGARCIACOMPANYLLC
    return re.sub(r"\s+", " ", s)

HAND = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "i": "1", "|": "1", "S": "5", "s": "5",
                      "B": "8", "b": "6", "Z": "2", "z": "2", "g": "9", "q": "9", "G": "6", "T": "7"})
def digits_fixed(text):
    """Map common OCR letter/digit confusions in a mostly-numeric token (handwriting, serial numbers)."""
    return (text or "").translate(HAND)

def money_hand(text):
    """Money from a handwritten box: '5443S.07' -> 54435.07."""
    v = money(text)
    if v is not None: return v
    return money(digits_fixed(text))
