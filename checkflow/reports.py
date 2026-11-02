"""The Daily report: the DEPOSIT TAXES sheet rebuilt from the ledger, with live formulas.

Three sheets:
  Daily report    - deposits by company and bank, the taxes block (taxable income, tax to withhold, TAXED at the
                    sales tax rate in F3), Taxable not set / Posted to NetSuite, and week-to-date tax to withhold.
  Payments        - every payment from Monday of that week through the day (blue = ledger data, black = formulas).
  Invoice splits  - the per-invoice lines of payments AR split across invoices.
Every figure on the report is a SUMIFS / COUNTIFS over the Payments sheet, so changing a payment there updates it.
"""
import datetime as dt
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter as L

DEFAULT_RATE = 0.0825
# Deposit bank names as typed in CheckFlow -> the column they go in on the report
ALIASES = {"LONE STAR": "LSB", "LONE STAR BANK": "LSB", "MID": "MIDFIRST", "MID FIRST": "MIDFIRST", "TEXAS NATIONAL": "TNB",
           "TEXAS NATIONAL BANK": "TNB"}
PREFERRED = ["LSB", "TNB", "MIDFIRST", "BPS"]
BANK_TITLES = {"LSB": "LONE STAR BANK", "TNB": "TEXAS NATIONAL BANK"}
METHODS = {"check": "Check", "cash": "Cash", "card": "Credit card", "ach": "ACH / e-check", "wire": "Wire transfer"}

FONT = "Arial"
NUM = '#,##0.00;-#,##0.00;"-"'
YEL = PatternFill("solid", fgColor="FFFF00")
HEAD = PatternFill("solid", fgColor="F2EFEC")
BLUE = Font(name=FONT, size=10, color="0000FF")
thin, med, dbl = Side(style="thin", color="999999"), Side(style="medium"), Side(style="double")

def font(**k): return Font(name=FONT, size=k.pop("size", 10), **k)

def hdr(c, text):
    c.value = text; c.font = font(bold=True); c.fill = HEAD; c.border = Border(bottom=med)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

def group_of(bank):
    b = (bank or "").strip().upper()
    return ALIASES.get(b, b)

def bank_groups(deposit_banks):
    gs = []
    for b in deposit_banks:
        g = group_of(b)
        if g and g not in gs: gs.append(g)
    return sorted(gs, key=lambda g: (PREFERRED.index(g) if g in PREFERRED else len(PREFERRED), gs.index(g)))

def _num(v):
    try: return float(str(v or 0).replace(",", "") or 0)
    except ValueError: return 0.0

def _date(s):
    try: return dt.date.fromisoformat(str(s)[:10])
    except ValueError: return None

def build(rows, day, companies, deposit_banks, in_daily, rate=DEFAULT_RATE, generated_by="", now=None):
    """rows: ledger rows (dict id/fields/sheet). day: date. companies: payee sheets in order. in_daily(fields) -> bool.
    Returns the .xlsx bytes."""
    mon = day - dt.timedelta(days=day.weekday())
    week = [mon + dt.timedelta(k) for k in range((day - mon).days + 1)]
    groups = bank_groups(deposit_banks)
    taxed = groups                 # every deposit bank, BPS included, gets taxable income / withhold / TAXED

    pays = []
    for r in rows:
        f = r["fields"]; d = _date(f.get("received"))
        if not d or not (mon <= d <= day): continue
        pays.append((d, (r.get("sheet") or f.get("sheet") or "").upper(), r["id"], f))
    cos = list(companies)
    for _, co, _, _ in sorted(pays):
        if co and co not in cos: cos.append(co)
    order = {c: i for i, c in enumerate(cos)}
    pays.sort(key=lambda p: (p[0], order.get(p[1], 99), p[2]))

    wb = openpyxl.Workbook()
    rep = wb.active; rep.title = "Daily report"
    pay = wb.create_sheet("Payments")
    spl = wb.create_sheet("Invoice splits")

    # ---------------- Payments
    cols = ["Date", "Company", "Customer", "Method", "Payment ref", "Amount", "Deposit bank", "Bank group", "Taxable", "Taxable amount",
            "Not taxable", "Taxable not set", "NetSuite #", "Posted by", "In daily total", "Split: taxable part", "Invoice split", "Taxable set by"]
    for i, h in enumerate(cols, 1): hdr(pay.cell(1, i), h)
    pay.row_dimensions[1].height = 28
    splits = []
    for r, (d, co, pid, f) in enumerate(pays, 2):
        g = group_of(f.get("deposit_bank"))
        tax = f.get("taxable") or ""
        inv = f.get("invoices") or []
        split = "; ".join(f"{l.get('invoice', '')} {_num(l.get('amount')):,.2f} {'taxable' if l.get('taxable') == 'Yes' else 'not taxable'}" for l in inv)
        vals = {1: d, 2: co, 3: f.get("customer") or "", 4: METHODS.get(f.get("method"), f.get("method") or ""),
                5: f.get("check_no") or f.get("payref") or "", 6: _num(f.get("amount")), 7: f.get("deposit_bank") or "",
                8: g if g in groups else ("NO BANK" if not g else "OTHER"), 9: tax,
                13: f.get("posted") or "", 14: (f.get("posted_by") or "") if f.get("posted") else "",
                15: "Yes" if in_daily(f) else "No", 16: _num(f.get("taxable_amount")) if tax == "Partial" else None,
                17: split, 18: (f.get("taxable_by") or "") if tax else ""}
        for c, v in vals.items():
            pay.cell(r, c, v).font = BLUE if c in (6, 7, 9, 15, 16) else font()
        pay.cell(r, 10, f'=IF(I{r}="Yes",F{r},IF(I{r}="Partial",P{r},0))').font = font()
        pay.cell(r, 11, f'=IF(I{r}="",0,F{r}-J{r})').font = font()
        pay.cell(r, 12, f'=IF(I{r}="",F{r},0)').font = font()
        pay.cell(r, 1).number_format = "MMM/DD/YY"
        for c in (6, 10, 11, 12, 16): pay.cell(r, c).number_format = NUM
        for l in inv: splits.append((d, co, f.get("customer") or "", _num(f.get("amount")), l))
    n = len(pays) + 1
    pay.cell(n + 1, 1, "Total").font = font(bold=True)
    for c in (6, 10, 11, 12):
        x = pay.cell(n + 1, c, f"=SUBTOTAL(9,{L(c)}2:{L(c)}{max(n, 2)})")
        x.font = font(bold=True); x.number_format = NUM; x.border = Border(top=thin, bottom=dbl)
    for c, w in zip(range(1, 19), (11, 9, 26, 13, 12, 13, 13, 11, 9, 13, 12, 13, 12, 17, 11, 13, 52, 17)): pay.column_dimensions[L(c)].width = w
    pay.freeze_panes = "A2"; pay.auto_filter.ref = f"A1:R{max(n, 2)}"
    pay["F1"].comment = Comment("Blue = data from the CheckFlow ledger; black = formulas.", "CheckFlow")

    # ---------------- Invoice splits
    for i, h in enumerate(["Date", "Company", "Customer", "Payment amount", "Invoice", "Invoice amount", "Taxable"], 1): hdr(spl.cell(1, i), h)
    for r, (d, co, cust, amt, l) in enumerate(splits, 2):
        for c, v in enumerate([d, co, cust, amt, l.get("invoice", ""), _num(l.get("amount")), "Yes" if l.get("taxable") == "Yes" else "No"], 1):
            spl.cell(r, c, v).font = font()
        spl.cell(r, 1).number_format = "MMM/DD/YY"; spl.cell(r, 4).number_format = NUM; spl.cell(r, 6).number_format = NUM
    if not splits: spl.cell(2, 1, "No payments split by invoice this week.").font = font(color="777777")
    for c, w in zip(range(1, 8), (11, 9, 26, 15, 14, 15, 9)): spl.column_dimensions[L(c)].width = w
    spl.freeze_panes = "A2"

    # ---------------- Daily report
    R = rep; PR = "Payments!"
    R.sheet_view.showGridLines = False
    R["B1"] = "Daily report"; R["B1"].font = font(size=16, bold=True)
    R["B3"] = "DATE"; R["B3"].font = font(bold=True)
    R["C3"] = day; R["C3"].number_format = "MMM/DD/YY"; R["C3"].font = font(bold=True, size=12); R["C3"].alignment = Alignment(horizontal="left")
    R["E3"] = "SALES TAX"; R["E3"].font = font(bold=True); R["E3"].alignment = Alignment(horizontal="right")
    R["F3"] = rate; R["F3"].number_format = "0.00%"; R["F3"].font = BLUE; R["F3"].fill = YEL
    R["F3"].comment = Comment("Sales tax rate included in taxable deposits. Change it here and the report recalculates.", "CheckFlow")
    now = now or dt.datetime.now()
    stamp = now.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    R["G3"] = f"Generated by CheckFlow from the ledger · {stamp}" + (f" · {generated_by}" if generated_by else "")
    R["G3"].font = font(color="777777", size=9)
    R["B5"] = "Good afternoon,"; R["B5"].font = font(size=11)
    R["B6"] = "This was how our day ended up:"; R["B6"].font = font(size=11)

    def sumifs(col, r, extra=""): return f"SUMIFS({PR}${col}:${col},{PR}$B:$B,$B{r},{PR}$A:$A,$C$3{extra})"
    daily = f',{PR}$O:$O,"Yes"'

    # Section A: deposits by company and bank
    h = 8
    a_cols = ["COMPANY", "TOTAL DEPOSIT", *groups, "OTHER / NO BANK", "PAYMENTS", "LEFT OUT OF DAILY TOTAL"]
    for c, t in enumerate(a_cols, 2): hdr(R.cell(h, c), t)
    R.row_dimensions[h].height = 30
    c_other, c_count, c_left = 4 + len(groups), 5 + len(groups), 6 + len(groups)
    for i, co in enumerate(cos):
        r = h + 1 + i
        R.cell(r, 2, co).font = font(bold=True)
        R.cell(r, 3, "=" + sumifs("F", r, daily))
        for j in range(len(groups)):
            R.cell(r, 4 + j, "=" + sumifs("F", r, daily + f",{PR}$H:$H,{L(4 + j)}${h}"))
        R.cell(r, c_other, "=" + sumifs("F", r, daily + f',{PR}$H:$H,"OTHER"') + "+" + sumifs("F", r, daily + f',{PR}$H:$H,"NO BANK"'))
        R.cell(r, c_count, f'=COUNTIFS({PR}$B:$B,$B{r},{PR}$A:$A,$C$3,{PR}$O:$O,"Yes")')
        R.cell(r, c_left, "=" + sumifs("F", r, f',{PR}$O:$O,"No"'))
        for c in range(3, c_left + 1):
            x = R.cell(r, c); x.font = font(size=11); x.number_format = "0" if c == c_count else NUM
    tA = h + 1 + len(cos) + 1
    R.cell(tA, 2, "TOTAL:").font = font(bold=True)
    for c in range(3, c_left + 1):
        x = R.cell(tA, c, f"=SUM({L(c)}{h + 1}:{L(c)}{tA - 1})")
        x.font = font(bold=True, size=11); x.number_format = "0" if c == c_count else NUM; x.border = Border(top=thin, bottom=dbl)
    R.cell(tA + 1, 2, f'=IF(ABS(C{tA}-SUM(D{tA}:{L(c_other)}{tA}))<0.005,"Check: the bank columns add up to the total deposit.",'
                      f'"CHECK: the bank columns don\'\'t add up to the total deposit.")').font = font(size=9, color="777777")

    # Section B: taxes
    s = tA + 4
    R.cell(s - 1, 2, "TAXES").font = font(bold=True, size=12)
    k = len(taxed)
    c_inc, c_wh = 4, 4 + k
    c_not, c_unset, c_posted = 4 + 2 * k, 5 + 2 * k, 6 + 2 * k
    c_taxed = c_posted + 2                       # one empty column, then TAXED / rate pairs per bank
    hb = s + 1
    hdr(R.cell(hb, 2), "COMPANY"); hdr(R.cell(hb, 3), "DEPOSIT")
    for j, g in enumerate(taxed):
        hdr(R.cell(hb, c_inc + j), f"{g} TAXABLE INCOME"); hdr(R.cell(hb, c_wh + j), f"WITHHOLD {g}")
        tc = c_taxed + 2 * j
        R.merge_cells(start_row=s, start_column=tc, end_row=s, end_column=tc + 1)
        R.cell(s, tc, BANK_TITLES.get(g, g)).font = font(bold=True); R.cell(s, tc).alignment = Alignment(horizontal="center")
        hdr(R.cell(hb, tc), "TAXED")
        x = R.cell(hb, tc + 1, "=$F$3"); hdr(x, None); x.value = "=$F$3"; x.number_format = "0.00%"
    hdr(R.cell(hb, c_not), "NOT TAXABLE"); hdr(R.cell(hb, c_unset), "TAXABLE NOT SET"); hdr(R.cell(hb, c_posted), "POSTED TO NETSUITE")
    R.row_dimensions[hb].height = 30
    for i, co in enumerate(cos):
        r, ra = hb + 1 + i, h + 1 + i
        R.cell(r, 2, co).font = font(bold=True)
        R.cell(r, 3, f"=C{ra}")
        for j, g in enumerate(taxed):
            inc, tc = L(c_inc + j), c_taxed + 2 * j
            R.cell(r, c_inc + j, "=" + sumifs("J", r, daily + f',{PR}$H:$H,"{g}"'))
            R.cell(r, tc, f"={inc}{r}/(1+$F$3)")
            R.cell(r, tc + 1, f"={inc}{r}-{L(tc)}{r}")
            R.cell(r, c_wh + j, f"={inc}{r}-{L(tc)}{r}")
        R.cell(r, c_not, "=" + sumifs("K", r, daily))
        R.cell(r, c_unset, "=" + sumifs("L", r, daily))
        R.cell(r, c_posted, f'=IF({L(c_count)}{ra}=0,"-",COUNTIFS({PR}$B:$B,$B{r},{PR}$A:$A,$C$3,{PR}$O:$O,"Yes",{PR}$M:$M,"<>")&" of "&{L(c_count)}{ra})')
        for c in list(range(3, c_posted)) + list(range(c_taxed, c_taxed + 2 * k)):
            x = R.cell(r, c); x.font = font(size=11); x.number_format = NUM
        for c in range(c_wh, c_wh + k): R.cell(r, c).fill = YEL
        R.cell(r, c_posted).alignment = Alignment(horizontal="center"); R.cell(r, c_posted).font = font(size=11)
    tB = hb + 1 + len(cos) + 1
    R.cell(tB, 2, "TOTAL:").font = font(bold=True)
    for c in list(range(3, c_posted)) + list(range(c_taxed, c_taxed + 2 * k)):
        x = R.cell(tB, c, f"=SUM({L(c)}{hb + 1}:{L(c)}{tB - 1})")
        x.font = font(bold=True, size=11); x.number_format = NUM; x.border = Border(top=thin, bottom=dbl)
    for c in range(c_wh, c_wh + k): R.cell(tB, c).fill = YEL
    x = R.cell(tB, c_posted, f'=COUNTIFS({PR}$A:$A,$C$3,{PR}$O:$O,"Yes",{PR}$M:$M,"<>")&" of "&{L(c_count)}{tA}')
    x.font = font(bold=True, size=11); x.alignment = Alignment(horizontal="center"); x.border = Border(top=thin, bottom=dbl)
    U = f"{L(c_unset)}{tB}"
    R.cell(tB + 1, 2, f'=IF({U}<>0,"Taxable not set on "&TEXT({U},"$#,##0.00")&": counted as not taxable here until AR sets it.","Every payment has Taxable set.")').font = font(size=9, color="C00000")
    LO = f"{L(c_left)}{tA}"
    R.cell(tB + 2, 2, f'=IF({LO}<>0,"Left out of the daily total (Affects daily total off): "&TEXT({LO},"$#,##0.00")&". See Payments, In daily total = No.","")').font = font(size=9, color="777777")

    # Section C: week to date, tax to withhold
    w = tB + 6
    R.cell(w - 1, 2, "WEEK TO DATE: TAX TO WITHHOLD").font = font(bold=True, size=12)
    wc = ["COMPANY", "DATE", *[f"WITHHOLD {g}" for g in taxed], "DAILY", "WKLY"]
    for c, t in enumerate(wc, 2): hdr(R.cell(w, c), t)
    c_day, c_wk = 4 + k, 5 + k
    r = w + 1; wk_cells = []
    for co in cos:
        first = r
        for d in week:
            R.cell(r, 2, co).font = font()
            x = R.cell(r, 3, d); x.number_format = "MMM/DD/YY"; x.font = font(); x.alignment = Alignment(horizontal="left")
            for j, g in enumerate(taxed):
                f_ = f'SUMIFS({PR}$J:$J,{PR}$B:$B,$B{r},{PR}$A:$A,$C{r},{PR}$O:$O,"Yes",{PR}$H:$H,"{g}")'
                R.cell(r, 4 + j, f"={f_}-{f_}/(1+$F$3)")
            R.cell(r, c_day, f"=SUM(D{r}:{L(c_day - 1)}{r})" if k else 0)
            for c in range(4, c_day + 1): R.cell(r, c).number_format = NUM; R.cell(r, c).font = font()
            r += 1
        x = R.cell(r - 1, c_wk, f"=SUM({L(c_day)}{first}:{L(c_day)}{r - 1})"); x.number_format = NUM; x.font = font(bold=True)
        wk_cells.append(f"{L(c_wk)}{r - 1}")
        for c in range(2, c_wk + 1): R.cell(r - 1, c).border = Border(bottom=thin)
    R.cell(r, 2, "TOTAL").font = font(bold=True)
    for c in range(4, c_wk + 1):
        src = ("+".join(wk_cells) or "0") if c == c_wk else f"SUM({L(c)}{w + 1}:{L(c)}{max(r - 1, w + 1)})"
        x = R.cell(r, c, f"={src}"); x.number_format = NUM; x.font = font(bold=True); x.border = Border(top=thin, bottom=dbl)
    R.cell(r + 1, 2, "Tax to withhold = taxable deposit - taxable deposit / (1 + sales tax), the same as the DEPOSIT TAXES sheet (=F17-F17/1.0825).").font = font(size=9, color="777777")

    widths = {1: 2, 2: 12, 3: 16}
    for c in range(4, c_wk + 1): widths[c] = 15
    for c in range(4, c_posted + 1): widths[c] = 15
    widths[c_posted + 1] = 2
    for j in range(k): widths[c_taxed + 2 * j] = 14; widths[c_taxed + 2 * j + 1] = 11
    for c, wd in widths.items(): R.column_dimensions[L(c)].width = wd
    R.freeze_panes = "A4"
    for ws, orient in ((R, "landscape"), (pay, "landscape"), (spl, "portrait")):
        ws.page_setup.orientation = orient; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.calculation.fullCalcOnLoad = True
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()
