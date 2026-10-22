"""Read the layout of a payee sheet: column positions, day blocks, subtotal labels and spacing.

Real sheets (MVC / UVM / RVP / VCP) differ: column order, header wording ('CC / WIRES', 'WW/ WIRE',
'CREDIT CARD'...), a TAXABLE column in 2026, which column holds subtotal labels vs. =SUM formulas,
group order inside a day (credit first in MVC/UVM 2026, checks first in RVP), and blank-row spacing.
Everything here is inferred from the sheet itself so a new year's workbook works without code changes."""
import re
from collections import Counter

def H(v): return re.sub(r"\s+", " ", str(v or "")).strip().upper()

SYN = {
    "date": ["DATE"],
    "customer": ["CUSTOMER"],
    "order": ["ORDER #", "ORDER#", "ORDER"],
    "ticket": ["TICKET REF", "RECEIPT #", "RECEIPT#", "RECEIPT"],
    "payref": ["PAYMENT REF:", "PAYMENT REF", "PAYMENT REF :"],
    "taxable": ["TAXABLE"],
    "cash": ["CASH"],
    "check": ["CHECK", "CHECKS"],
    "credit": ["CREDIT", "CREDIT CARD", "CC / WIRES", "CC / WIRE", "CC/WIRES", "CC/WIRE", "WW/ WIRE", "WW/WIRE", "CC/ WIRE", "CC / WIRES "],
    "bank": ["BANK ACC", "BANK", "BANK ACCOUNT"],
    "deposit_date": ["DEPOSIT DATE"],
    "deposit_type": ["DEPOSIT TYPE"],
    "deposit_amount": ["DEPOSIT AMOUNT", "AMOUNT"],
    "total": ["TOTAL"],
}
DATE_TXT = re.compile(r"^[A-Z]{3}/\d{1,2}/\d{2}$", re.I)
MAXC = 30

def is_header(ws, r):
    vals = [H(ws.cell(r, c).value) for c in range(1, MAXC)]
    return "CUSTOMER" in vals and sum(1 for v in vals if v in ("CASH", "CHECK", "CHECKS") or "PAYMENT REF" in v) >= 1

def header_map(ws, r):
    vals = {c: H(ws.cell(r, c).value) for c in range(1, MAXC)}
    m = {}
    for key, names in SYN.items():
        for name in names:                      # priority order: first synonym that exists wins
            col = next((c for c, v in vals.items() if v == name), None)
            if col and col not in m.values():
                m[key] = col; break
    if "date" not in m:                         # 2026 MVC prints no 'DATE' header; dates live in column A
        m["date"] = 1
    return m

def last_row(ws):
    for r in range(ws.max_row, 0, -1):
        if any(ws.cell(r, c).value not in (None, "") for c in range(1, MAXC)): return r
    return 0

def headers(ws, lo=1):
    return [r for r in range(lo, ws.max_row + 1) if is_header(ws, r)]

def group_of_label(label):
    t = H(label)
    if not t or "TOTAL" in t: return None
    if "CHECK" in t and "CASH" in t: return None           # 'CHECKS/CASH' combined subtotal
    if "CHECK" in t: return "check"
    if "CASH" in t: return "cash"
    if any(k in t for k in ("CREDIT", "WIRE", "CC")): return "credit"
    return None

class Layout:
    """Everything the writer needs about one sheet."""
    def __init__(self, ws):
        self.ws = ws
        hs = headers(ws, max(1, ws.max_row - 3000))
        if not hs: hs = headers(ws)
        if not hs: raise ValueError(f"Sheet '{ws.title}': no header row with CUSTOMER / CASH / CHECK found.")
        self.headers = hs
        self.hdr = hs[-1]
        self.cols = header_map(ws, self.hdr)
        for k in ("customer", "check"):
            if k not in self.cols: raise ValueError(f"Sheet '{ws.title}': can't find the {k.upper()} column.")
        self.amount_cols = {g: self.cols[g] for g in ("cash", "check", "credit") if g in self.cols}
        self._learn()

    def _learn(self):
        ws, lo = self.ws, max(1, self.headers[-min(len(self.headers), 25)])
        sum_cols, labels, totals = Counter(), {}, Counter()
        orders = Counter()
        gaps = Counter(); tgaps = Counter(); block_gap = Counter(); has_total = Counter()
        prev_end = None
        for bi, h in enumerate([x for x in self.headers if x >= lo]):
            nxt = next((x for x in self.headers if x > h), last_row(ws) + 1)
            seq, last_entry, saw_total = [], None, False
            for r in range(h + 1, nxt):
                for c in range(1, MAXC):
                    v = ws.cell(r, c).value
                    if isinstance(v, str) and v.startswith("="):
                        sum_cols[c] += 1
                        lab = ws.cell(r, c - 1).value
                        g = group_of_label(lab)
                        if g:
                            labels.setdefault(g, Counter())[H(lab)] += 1
                            seq.append(g)
                            if last_entry: gaps[r - last_entry - 1] += 1
                            else:                       # template block (new workbook): one empty entry slot + the gap rows
                                k, rr = 0, r - 1
                                while rr > h and not self.used(rr): k, rr = k + 1, rr - 1
                                if k >= 1: tgaps[k - 1] += 1
                        elif "TOTAL" in H(lab):
                            totals[H(lab)] += 1; saw_total = True
                        break
                if self.is_entry(r): last_entry = r
            if seq: orders[tuple(dict.fromkeys(seq))] += 1
            has_total[saw_total and len(set(seq)) >= 2] += 1
            if prev_end is not None: block_gap[h - prev_end - 1] += 1
            prev_end = max([r for r in range(h, nxt) if any(ws.cell(r, c).value not in (None, "") for c in range(1, MAXC))] or [h])
        self.sum_col = sum_cols.most_common(1)[0][0] if sum_cols else (
            (self.cols.get("deposit_amount") or (self.cols.get("deposit_date") or self.cols.get("deposit_type") or 9) + 1))
        self.label_col = self.sum_col - 1
        self.labels = {g: (labels[g].most_common(1)[0][0] if g in labels else d)
                       for g, d in (("check", "CHECKS"), ("cash", "CASH"), ("credit", "CREDIT"))}
        self.total_label = totals.most_common(1)[0][0] if totals else "TOTAL"
        best = orders.most_common(1)[0][0] if orders else ()
        self.order = list(best) + [g for g in ("credit", "check", "cash") if g not in best]
        self.gap_before_subtotal = gaps.most_common(1)[0][0] if gaps else (tgaps.most_common(1)[0][0] if tgaps else 0)
        self.gap_between_blocks = block_gap.most_common(1)[0][0] if block_gap else 1
        self.gap_before_subtotal = min(self.gap_before_subtotal, 2)
        self.gap_between_blocks = min(self.gap_between_blocks, 3)
        self.totals_always = bool(totals)

    def is_entry(self, r):
        ws = self.ws
        cust = ws.cell(r, self.cols["customer"]).value
        if cust in (None, "") or H(cust) == "CUSTOMER": return False
        return any(isinstance(ws.cell(r, c).value, (int, float)) for c in self.amount_cols.values())

    def entry_group(self, r):
        for g, c in self.amount_cols.items():
            if isinstance(self.ws.cell(r, c).value, (int, float)): return g
        return None

    def used(self, r): return any(self.ws.cell(r, c).value not in (None, "") for c in range(1, MAXC))

    def block_bounds(self, h):
        """(header row, last used row) of the day block that starts at header h.
        Stops at a long empty stretch, so stray leftovers far below the data are never treated as part of the day."""
        nxt = next((x for x in self.headers if x > h), None)
        limit = (nxt - 1) if nxt else last_row(self.ws)
        end, empty = h, 0
        for r in range(h + 1, limit + 1):
            if self.used(r): end, empty = r, 0
            else:
                empty += 1
                if empty >= 8: break
        return h, end

    def block_date(self, h):
        _, end = self.block_bounds(h)
        for r in range(h + 1, end + 1):
            v = self.ws.cell(r, self.cols["date"]).value
            if isinstance(v, str) and DATE_TXT.match(v.strip()): return v.strip().upper()
            if hasattr(v, "strftime"): return v.strftime("%b/%d/%y").upper()
        return None

    def date_style(self):
        """How dates are written in the date column (text 'OCT/09/26' in every sheet seen so far)."""
        return "text"
