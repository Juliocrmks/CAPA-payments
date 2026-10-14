"""Read an uploaded spreadsheet into ledger records (admin: Ledger -> Import Excel).

Two shapes are understood, per worksheet:
  * the payee workbook itself: a header row per day with CASH / CHECK / CREDIT amount columns (same reader as the
    one-time migration), sheet = worksheet name;
  * a plain table: one header row (Date, Customer/Client, Amount, and optionally Method, Check #, Ticket, Payee,
    Deposit bank, Taxable), one payment per row. .csv files are read the same way.

Nothing is written here: read_file() returns records + a summary; the API previews it, then commits."""
import csv, datetime, io, os, re, statistics
from collections import Counter, defaultdict
import openpyxl
from .importer import history_ws, parse_sheet_date
from ..extract.common import money, parse_date
from ..registry import nkey

SYN = {  # normalised header text -> field
    "date": ["DATE", "DATERECEIVED", "RECEIVED", "RECEIVEDDATE", "PAYMENTDATE", "DEPOSITDATE", "DATEPAID", "PAIDON", "DAY"],
    "customer": ["CUSTOMER", "CUSTOMERNAME", "CLIENT", "CLIENTNAME", "NAME", "PAYER", "RECEIVEDFROM", "PAIDBY", "COMPANY", "COMPANYNAME"],
    "amount": ["AMOUNT", "AMT", "TOTAL", "PAYMENT", "PAYMENTAMOUNT", "AMOUNTPAID", "AMOUNTRECEIVED", "DEPOSIT"],
    "method": ["METHOD", "PAYMENTMETHOD", "TYPE", "PAYMENTTYPE", "HOWPAID", "PAIDWITH", "TENDER"],
    "payref": ["CHECK", "CHECKNO", "CHECKNUMBER", "CHECKNUM", "CK", "CKNO", "REF", "REFERENCE", "REFNO", "PAYMENTREF", "CONFIRMATION"],
    "ticket": ["TICKET", "TICKETNO", "TICKETREF", "RECEIPT", "RECEIPTNO", "RECEIPTNUMBER"],
    "order": ["ORDER", "ORDERNO", "PO", "PONUMBER", "INVOICE", "INVOICENO"],
    "sheet": ["PAYEE", "SHEET", "DIVISION", "PAYEECOMPANY", "PAIDTO", "LOCATION"],
    "deposit_bank": ["BANK", "DEPOSITBANK", "DEPOSITEDTO", "DEPOSITEDIN"],
    "taxable": ["TAXABLE", "TAX", "TAXABLEYN"],
}
LOOKUP = {h: f for f, hs in SYN.items() for h in hs}

def _h(v): return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())

def method_of(text):
    t = (text or "").upper()
    if not t.strip(): return "check"
    if "WIRE" in t: return "wire"
    if "ACH" in t or "E-CHECK" in t or "ECHECK" in t or "EFT" in t: return "ach"
    if re.search(r"CARD|VISA|MASTER|AMEX|DISCOVER|CREDIT|\bCC\b|\bMC\b", t): return "card"
    if "CASH" in t: return "cash"
    return "check"

def _date(v):
    if isinstance(v, datetime.datetime): return v.date().isoformat()
    if isinstance(v, datetime.date): return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:            # Excel serial date stored as a number
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    s = str(v or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s): return s[:10]
    return parse_date(s) or parse_sheet_date(s)

def _amount(v):
    if isinstance(v, bool): return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v or "").strip()
    if not s: return None
    neg = s.startswith("(") or s.startswith("-")
    m = money(s if "." in s else s + ".00")
    return (-m if neg else m) if m is not None else None

def _text(v):
    if v is None: return ""
    if isinstance(v, float) and v.is_integer(): v = int(v)
    return str(v).strip()

def _header(rows):
    """First row (of the first 20) naming at least a date, a customer and an amount column."""
    for i, row in enumerate(rows[:20]):
        cols = {}
        for j, v in enumerate(row):
            f = LOOKUP.get(_h(v))
            if f and f not in cols: cols[f] = j
        if {"date", "customer", "amount"} <= cols.keys(): return i, cols
    return None, None

def table_records(rows, sheet_name, resolve_sheet):
    """Plain table -> records. rows = list of value lists (row 1 first). Returns (records, skipped)."""
    hi, cols = _header(rows)
    if hi is None: return None, 0
    out, skipped = [], 0
    for k, row in enumerate(rows[hi + 1:], start=hi + 2):
        get = lambda f: row[cols[f]] if f in cols and cols[f] < len(row) else None
        if all(_text(x) == "" for x in row): continue
        d, amt, cust = _date(get("date")), _amount(get("amount")), _text(get("customer"))
        if not d or amt is None or not cust or amt == 0:
            skipped += 1; continue
        tax = _text(get("taxable")).upper()
        named = _text(get("sheet"))           # a payee we don't know stays as written; the tab name only counts if it is one
        out.append(dict(sheet=resolve_sheet(named) or named.upper() or resolve_sheet(sheet_name) or "", row=k, received=d,
                        customer=re.sub(r"\s+", " ", cust).upper(), order=_text(get("order")), ticket=_text(get("ticket")),
                        payref=_text(get("payref")), method=method_of(_text(get("method"))), amount=f"{amt:.2f}",
                        taxable={"YES": "Yes", "Y": "Yes", "TRUE": "Yes", "NO": "No", "N": "No", "FALSE": "No"}.get(tax, ""),
                        deposit_bank=_text(get("deposit_bank")).upper(), source=sheet_name))
    return out, skipped

def read_file(path, filename, known_sheets, reg):
    """-> dict(records, sheets: {source sheet: format}, skipped, warnings)."""
    known = {s.upper(): s for s in known_sheets}
    def resolve(text):
        t = (text or "").strip()
        if not t: return ""
        if t.upper() in known: return known[t.upper()]
        for name, sheet, aliases in reg.payees():
            if t.upper() == sheet.upper() or t.upper() in [a.upper() for a in aliases] or nkey(t) == nkey(name): return sheet
        m = reg.match_payee(t)
        return m[1] if m else ""
    records, formats, skipped, warnings = [], {}, 0, []
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".csv":
        raw = open(path, "rb").read().decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(raw)))
        name = os.path.splitext(os.path.basename(filename))[0]
        recs, sk = table_records(rows, name, resolve)
        if recs is None: raise ValueError("No header row with a date, a customer and an amount column was found.")
        records += recs; skipped += sk; formats[name] = "table"
    else:
        try: wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e: raise ValueError(f"Couldn't open the file as an Excel workbook ({type(e).__name__}).")
        try:
            for ws in wb.worksheets:
                recs = [dict(r, sheet=resolve(ws.title) or ws.title.upper(), source=ws.title) for r in history_ws(ws)]
                if recs:
                    records += recs; formats[ws.title] = "workbook"; continue
                rows = [list(r) for r in ws.iter_rows(values_only=True)]
                recs, sk = table_records(rows, ws.title, resolve)
                if recs: records += recs; skipped += sk; formats[ws.title] = "table"
                elif rows and any(any(_text(v) for v in r) for r in rows[:5]): formats[ws.title] = "skipped"
        finally:
            wb.close()
    if not records: raise ValueError("No payments found. Use the payee workbook layout, or a table with Date, Customer and Amount columns.")
    undated = [r for r in records if not r["received"]]
    if undated:
        records = [r for r in records if r["received"]]
        skipped += len(undated)
    if not records: raise ValueError("None of the rows has a date received.")
    outflow = [r for r in records if float(r["amount"]) <= 0 or r["customer"].startswith(("WITHDRAWAL", "TRANSFER OUT"))]
    if outflow:
        records = [r for r in records if r not in outflow]
        warnings.append(f"{len(outflow)} withdrawal / negative row{'s' if len(outflow) != 1 else ''} left out (not payments received).")
    flag_dates(records)
    if skipped: warnings.append(f"{skipped} row{'s' if skipped != 1 else ''} skipped: missing a date, customer or amount.")
    blank = sum(1 for r in records if not r["sheet"])
    if blank: warnings.append(f"{blank} row{'s' if blank != 1 else ''} don't say which payee they belong to. Pick one below.")
    unknown = sorted({r["sheet"] for r in records if r["sheet"] and r["sheet"] not in known_sheets})
    if unknown and known_sheets: warnings.append("Payees not in the workbook: " + ", ".join(unknown) + ". They are imported under those names.")
    return dict(records=records, sheets=formats, skipped=skipped, warnings=warnings)

def fingerprint(sheet, received, amount, customer):
    try: cents = round(float(amount) * 100)
    except (TypeError, ValueError): cents = 0
    return f"{(sheet or '').upper()}|{received}|{cents}|{nkey(customer)}"

def mark_duplicates(records, existing):
    """existing: Counter of fingerprints already in the ledger. Two identical payments on one day stay two:
    only as many file rows as the ledger already holds are marked duplicate."""
    left = Counter(existing)
    for k, n in list(left.items()):                  # rows that don't name a payee match on day + amount + client alone
        left["|" + k.split("|", 1)[1]] += n
    for r in records:
        fp = fingerprint(r["sheet"], r["received"], r["amount"], r["customer"])
        r["duplicate"] = left[fp] > 0
        if left[fp] > 0: left[fp] -= 1
    return records

def summary(records):
    per = {}
    for r in records:
        s = per.setdefault(r["sheet"] or "", dict(sheet=r["sheet"] or "", rows=0, new=0, duplicates=0, total=0.0, first=None, last=None))
        s["rows"] += 1
        if r["duplicate"]: s["duplicates"] += 1
        else: s["new"] += 1; s["total"] += float(r["amount"])
        s["first"] = min(filter(None, [s["first"], r["received"]]))
        s["last"] = max(filter(None, [s["last"], r["received"]]))
    return sorted(per.values(), key=lambda s: s["sheet"])

def _odd_dates(ds, window, tolerance):
    """Index -> (median of neighbours, year-corrected date or None) for dates far from the rows around them."""
    out = {}
    for i, d in enumerate(ds):
        near = ds[max(0, i - window):i] + ds[i + 1:i + 1 + window]
        if len(near) < 3: continue
        mid = datetime.date.fromordinal(int(statistics.median(x.toordinal() for x in near)))
        if abs((d - mid).days) <= tolerance: continue
        fix = None
        for y in (mid.year, mid.year - 1, mid.year + 1):
            try: cand = d.replace(year=y)
            except ValueError: continue
            if abs((cand - mid).days) <= tolerance: fix = cand; break
        out[i] = (mid, fix)
    return out

def flag_dates(records, window=6, tolerance=45):
    """Mark dates that sit far from the rows around them in the file (day blocks are in date order), e.g. a 2026 typed
    among 2025 rows. r['date_issue'] = {'was', 'fix' (same month/day in the neighbours' year) or None, 'near'}.
    Second pass: with the year typos corrected, rows that only looked odd because of those typos are cleared."""
    by_src = defaultdict(list)
    for r in records: by_src[r.get("source", "")].append(r)
    for rows in by_src.values():
        ds = [datetime.date.fromisoformat(r["received"]) for r in rows]
        gaps = [abs((b - a).days) for a, b in zip(ds, ds[1:])]
        tol = max(tolerance, 4 * statistics.median(gaps)) if gaps else tolerance   # sparse exports have wider gaps
        odd = _odd_dates(ds, window, tol)
        fixed = [odd[i][1] if i in odd and odd[i][1] else d for i, d in enumerate(ds)]
        again = _odd_dates(fixed, window, tol)
        for i, (mid, fix) in odd.items():
            if fix is None and i not in again: continue
            m2 = again.get(i, (mid, fix))[0]
            rows[i]["date_issue"] = dict(was=rows[i]["received"], fix=fix.isoformat() if fix else None, near=(mid if fix else m2).isoformat())
    return records

def apply_date_policy(records, policy="fix"):
    """fix: correct the year where that puts the row among its neighbours (others are kept as written);
    skip: leave every flagged row out; keep: import them all as written. -> (records, fixed, dropped)"""
    out, fixed, dropped = [], 0, 0
    for r in records:
        iss = r.get("date_issue")
        if not iss or policy == "keep": out.append(r); continue
        if policy == "fix":
            if iss["fix"]: out.append(dict(r, received=iss["fix"])); fixed += 1
            else: out.append(r)
        else:
            dropped += 1
    return out, fixed, dropped
