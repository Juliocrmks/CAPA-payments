"""Analytics over the ledger (admin -> Analytics): KPIs, receipts per period, breakdowns by payee / client / method /
deposit bank, a simple projection, and plain-language storylines.

Everything is computed here from submitted payments (scanned and imported); nothing leaves the machine.

Projection method (kept deliberately simple so it can be explained in one sentence):
  * a least-squares straight line through the last complete periods (up to 24 months / 12 quarters / 52 weeks);
  * monthly seasonality on top when there are 24+ complete months (average ratio of each calendar month to the line);
  * an 80% range from the spread of past periods around that fit, widening the further out it goes;
  * the period in progress is projected by run-rate: received so far / business days elapsed x business days in period.
"""
import datetime as dt, json, math, statistics
from collections import Counter, defaultdict
from . import db

GRAINS = ("day", "week", "month", "quarter", "year")
DIMS = ("sheet", "customer", "method", "bank")
METHOD_ORDER = ["check", "cash", "card", "ach", "wire"]
METHOD_LABEL = {"check": "Check", "cash": "Cash", "card": "Credit card", "ach": "ACH", "wire": "Wire"}
SHEET_ORDER = ["MVC", "UPPER", "RIO", "VCP"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
FIT_LEN = {"day": 60, "week": 52, "month": 24, "quarter": 12, "year": 8}
Z80 = 1.2816

# ------------------------------------------------------------------ data
def load():
    with db.conn() as c:
        rows = c.execute("""SELECT p.fields, p.imported, s.sheet FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                            WHERE p.status='submitted'""").fetchall()
    out = []
    for r in rows:
        f = json.loads(r["fields"] or "{}")
        try:
            d = dt.date.fromisoformat((f.get("received") or "")[:10])
            amt = float(str(f.get("amount") or "").replace(",", "").replace("$", ""))
        except ValueError:
            continue
        if amt <= 0: continue        # analytics is money received: withdrawals, cash on hand and refunds stay in the ledger only
        out.append(dict(date=d, amount=amt, sheet=(r["sheet"] or f.get("sheet") or "").upper() or "(none)",
                        customer=" ".join((f.get("customer") or "").upper().split()) or "(no name)",
                        method=f.get("method") if f.get("method") in METHOD_LABEL else "check",
                        bank=(f.get("deposit_bank") or "").strip().upper() or "(none)", taxable=f.get("taxable") or "",
                        imported=bool(r["imported"])))
    return out

# ------------------------------------------------------------------ periods
def pkey(d, g):
    if g == "day": return d
    if g == "week": return d - dt.timedelta(days=d.weekday())
    if g == "month": return d.replace(day=1)
    if g == "quarter": return dt.date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    return dt.date(d.year, 1, 1)

def _add_months(d, n):
    m = d.month - 1 + n
    return dt.date(d.year + m // 12, m % 12 + 1, 1)

def pnext(p, g):
    if g == "day": return p + dt.timedelta(days=1)
    if g == "week": return p + dt.timedelta(days=7)
    if g == "month": return _add_months(p, 1)
    if g == "quarter": return _add_months(p, 3)
    return dt.date(p.year + 1, 1, 1)

def pend(p, g): return pnext(p, g) - dt.timedelta(days=1)

def plabel(p, g, short=False):
    if g == "day": return f"{p:%b} {p.day}" + ("" if short else f", {p.year}")
    if g == "week": return f"Wk of {p:%b} {p.day}" if short else f"week of {p:%b} {p.day}, {p.year}"
    if g == "month": return f"{p:%b %Y}" if short else f"{p:%B %Y}"
    if g == "quarter": return f"Q{(p.month - 1) // 3 + 1} {p.year}"
    return str(p.year)

def plist(a, b, g):
    out, p = [], pkey(a, g)
    while p <= b:
        out.append(p); p = pnext(p, g)
    return out

def bdays(a, b):
    """Business days (Mon-Fri) from a to b inclusive."""
    if b < a: return 0
    n = (b - a).days + 1
    full, rem = divmod(n, 7)
    return full * 5 + sum(1 for i in range(rem) if (a.weekday() + i) % 7 < 5)

# ------------------------------------------------------------------ helpers
def money(v):
    a = abs(v); s = "-" if v < 0 else ""
    if a >= 1e6: return f"{s}${a / 1e6:.2f}M"
    if a >= 1e5: return f"{s}${a / 1e3:.0f}K"
    return f"{s}${a:,.0f}"

def pct(a, b):
    return None if not b else (a - b) / b * 100

def linfit(ys):
    n = len(ys)
    xm = (n - 1) / 2; ym = sum(ys) / n
    sxx = sum((i - xm) ** 2 for i in range(n)) or 1
    b = sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / sxx
    return ym - b * xm, b

def dim_of(r, by): return r[by]

def dim_label(k, by):
    return METHOD_LABEL.get(k, k) if by == "method" else k

def order_keys(keys, by, banks):
    keys = set(keys)
    if by == "sheet": fixed = [s for s in SHEET_ORDER if s in keys]
    elif by == "method": fixed = [m for m in METHOD_ORDER if m in keys]
    elif by == "bank": fixed = [b for b in banks if b in keys]
    else: fixed = []
    return fixed + sorted(keys - set(fixed))

# ------------------------------------------------------------------ forecast
def forecast(hist, g, horizon, last_key):
    """hist: [(period, total)] contiguous complete periods. -> dict or None."""
    hist = hist[-FIT_LEN[g]:]
    n = len(hist)
    if n < 4 or g == "day": return None
    ys = [v for _, v in hist]
    a, b = linfit(ys)
    seas = None
    if g == "month" and n >= 24:
        ratios = defaultdict(list)
        for i, (p, v) in enumerate(hist):
            base = a + b * i
            if base > 0: ratios[p.month].append(v / base)
        if len(ratios) == 12:
            seas = {m: statistics.mean(r) for m, r in ratios.items()}
            norm = statistics.mean(seas.values())
            seas = {m: min(1.8, max(0.5, v / norm)) for m, v in seas.items()}
    fit = [(a + b * i) * (seas[p.month] if seas else 1) for i, (p, _) in enumerate(hist)]
    resid = [y - f for y, f in zip(ys, fit)]
    sd = statistics.pstdev(resid) if n > 2 else 0
    pts, p = [], last_key
    for h in range(1, horizon + 1):
        p = pnext(p, g)
        i = n - 1 + h
        y = max(0.0, (a + b * i) * (seas[p.month] if seas else 1))
        w = Z80 * sd * math.sqrt(1 + h / n)
        pts.append(dict(key=p.isoformat(), label=plabel(p, g, True), value=round(y, 2), low=round(max(0.0, y - w), 2), high=round(y + w, 2)))
    slope_pct = pct(a + b * n, a + b * (n - 1)) if a + b * (n - 1) > 0 else None
    return dict(points=pts, fitted_on=n, seasonal=bool(seas), slope_per_period=round(b, 2), slope_pct=slope_pct,
                peak=(max(seas, key=seas.get) if seas else None), low_month=(min(seas, key=seas.get) if seas else None),
                seas=seas)

def group_next(values):
    """Next-period estimate for one breakdown row (straight line over its recent complete periods)."""
    ys = values[-12:]
    if len(ys) < 4 or not any(ys): return None
    a, b = linfit(ys)
    return round(max(0.0, a + b * len(ys)), 2)

# ------------------------------------------------------------------ main
def analytics(start=None, end=None, grain="month", by="sheet", sheets=(), customer="", methods=(), banks=(), horizon=3, deposit_banks=()):
    grain = grain if grain in GRAINS else "month"
    by = by if by in DIMS else "sheet"
    horizon = max(1, min(int(horizon or 3), 12))
    rows = load()
    base = dict(grain=grain, by=by, filters=dict(sheets=list(sheets), customer=customer, methods=list(methods), banks=list(banks)))
    if not rows:
        return base | dict(empty=True, message="No payments in the ledger yet. Send payments to Excel or import a spreadsheet first.",
                           options=dict(sheets=[], customers=[], banks=list(deposit_banks), methods=METHOD_ORDER))
    as_of = max(r["date"] for r in rows)
    options = dict(sheets=order_keys({r["sheet"] for r in rows}, "sheet", ()), methods=METHOD_ORDER,
                   banks=order_keys({r["bank"] for r in rows}, "bank", deposit_banks),
                   customers=_customer_options(rows),
                   first=min(r["date"] for r in rows).isoformat(), as_of=as_of.isoformat())
    cust = " ".join((customer or "").upper().split())
    scoped = [r for r in rows if (not sheets or r["sheet"] in sheets) and (not cust or r["customer"] == cust)
              and (not methods or r["method"] in methods) and (not banks or r["bank"] in banks)]
    end = dt.date.fromisoformat(end) if end else as_of
    start = dt.date.fromisoformat(start) if start else _add_months(pkey(end, "month"), -11)
    if start > end: start, end = end, start
    span = (end - start).days
    pstart, pend_ = start - dt.timedelta(days=span + 1), start - dt.timedelta(days=1)
    cur = [r for r in scoped if start <= r["date"] <= end]
    prev = [r for r in scoped if pstart <= r["date"] <= pend_]

    keys = plist(start, end, grain)
    idx = {k: i for i, k in enumerate(keys)}
    def per_period(rs, val=lambda r: r["amount"]):
        v = [0.0] * len(keys)
        for r in rs: v[idx[pkey(r["date"], grain)]] += val(r)
        return v
    totals = per_period(cur)
    counts = per_period(cur, lambda r: 1)
    clients_pp = [len({r["customer"] for r in cur if pkey(r["date"], grain) == k}) for k in keys]
    partial_end = end < pend(keys[-1], grain)
    in_progress = partial_end and end >= as_of          # the latest period is still filling up
    partial_start = start > keys[0]

    # ---- KPIs
    def k(rs):
        t = sum(r["amount"] for r in rs); n = len(rs)
        return dict(total=round(t, 2), count=n, avg=round(t / n, 2) if n else 0, clients=len({r["customer"] for r in rs}))
    kc, kp = k(cur), k(prev)
    largest = max(cur, key=lambda r: r["amount"], default=None)
    kpis = dict(current=kc, previous=kp, delta={m: pct(kc[m], kp[m]) for m in kc},
                prev_range=dict(start=pstart.isoformat(), end=pend_.isoformat()),
                largest=dict(amount=largest["amount"], customer=largest["customer"], date=largest["date"].isoformat(), sheet=largest["sheet"]) if largest else None,
                spark=dict(total=[round(v, 2) for v in totals], count=counts, avg=[round(t / c, 2) if c else 0 for t, c in zip(totals, counts)], clients=clients_pp))

    # ---- composition over time (fixed-entity dimensions only; clients are ranked instead)
    series = []
    if by != "customer":
        g = defaultdict(lambda: [0.0] * len(keys))
        for r in cur: g[dim_of(r, by)][idx[pkey(r["date"], grain)]] += r["amount"]
        for key in order_keys(g.keys(), by, deposit_banks):
            series.append(dict(key=key, label=dim_label(key, by), values=[round(v, 2) for v in g[key]]))

    # ---- projection on the total
    hist_tot = defaultdict(float)
    for r in scoped:
        if r["date"] <= end: hist_tot[pkey(r["date"], grain)] += r["amount"]
    last_complete = pkey(end, grain) if not partial_end else pkey(pkey(end, grain) - dt.timedelta(days=1), grain)
    hist = []
    if hist_tot:
        p = min(hist_tot)
        while p <= last_complete:
            hist.append((p, hist_tot.get(p, 0.0))); p = pnext(p, grain)
    fc = forecast(hist, grain, horizon + (1 if partial_end else 0), last_complete) if hist else None
    pace = None
    if in_progress and keys:
        kcur = keys[-1]
        so_far = totals[-1]
        done, whole = bdays(max(kcur, start), end), bdays(kcur, pend(kcur, grain))
        if done >= 3 and whole:
            pace = dict(key=kcur.isoformat(), label=plabel(kcur, grain, True), so_far=round(so_far, 2), days_done=done, days_total=whole,
                        value=round(so_far / done * whole, 2))
    if fc and partial_end and pace:
        fc["points"] = fc["points"][1:]          # the period in progress is shown 'on pace' (run-rate) instead
    projection = dict(points=fc["points"] if fc else [], method=_method_text(fc, grain), pace=pace,
                      fitted_on=fc["fitted_on"] if fc else len(hist), seasonal=fc["seasonal"] if fc else False)

    # ---- breakdown table
    bd = _breakdown(cur, prev, scoped, keys, idx, grain, by, kc["total"], deposit_banks, end, partial_end)

    stories = _stories(dict(rows=rows, scoped=scoped, cur=cur, prev=prev, kc=kc, kp=kp, start=start, end=end, grain=grain, by=by,
                            keys=keys, totals=totals, in_progress=in_progress, fc=fc, pace=pace, bd=bd, cust=cust, largest=largest,
                            sheets=sheets, methods=methods))
    return base | dict(empty=False, as_of=as_of.isoformat(), range=dict(start=start.isoformat(), end=end.isoformat(), partial_start=partial_start,
                       in_progress=in_progress, partial_end=partial_end, label=_range_label(start, end)),
                       periods=[dict(key=p.isoformat(), label=plabel(p, grain, True), start=max(p, start).isoformat(), end=min(pend(p, grain), end).isoformat()) for p in keys],
                       totals=[round(v, 2) for v in totals], counts=counts, series=series, kpis=kpis, projection=projection,
                       breakdown=bd, storylines=stories, options=options)

def _customer_options(rows):
    t = Counter()
    for r in rows: t[r["customer"]] += r["amount"]
    return [c for c, _ in t.most_common(3000)]

def _range_label(a, b):
    if a.year == b.year: return f"{a:%b} {a.day} – {b:%b} {b.day}, {b.year}"
    return f"{a:%b} {a.day}, {a.year} – {b:%b} {b.day}, {b.year}"

def _method_text(fc, g):
    if g == "day": return "Projections are shown for weekly, monthly, quarterly or yearly views."
    if not fc: return "Not enough history to project yet (needs at least 4 complete periods)."
    s = f"Straight-line trend of the last {fc['fitted_on']} complete {g}s"
    if fc["seasonal"]: s += ", adjusted for the usual pattern of each calendar month"
    return s + ". Shaded band: 80% range from how much past periods varied."

def _breakdown(cur, prev, scoped, keys, idx, grain, by, total, deposit_banks, end, partial_end=False):
    agg = defaultdict(lambda: dict(total=0.0, count=0, last=None, spark=[0.0] * len(keys), methods=Counter(), sheets=set()))
    for r in cur:
        a = agg[dim_of(r, by)]
        a["total"] += r["amount"]; a["count"] += 1; a["spark"][idx[pkey(r["date"], grain)]] += r["amount"]
        a["last"] = max(filter(None, [a["last"], r["date"]])); a["methods"][r["method"]] += r["amount"]; a["sheets"].add(r["sheet"])
    ptot = Counter()
    for r in prev: ptot[dim_of(r, by)] += r["amount"]
    first_ever, dates = {}, defaultdict(list)
    for r in scoped:
        kk = dim_of(r, by)
        if kk not in first_ever or r["date"] < first_ever[kk]: first_ever[kk] = r["date"]
        if by == "customer" and r["date"] <= end: dates[kk].append(r["date"])
    out = []
    for key, a in agg.items():
        row = dict(key=key, label=dim_label(key, by), total=round(a["total"], 2), count=a["count"], avg=round(a["total"] / a["count"], 2),
                   share=round(a["total"] / total * 100, 1) if total else 0, prev_total=round(ptot.get(key, 0.0), 2),
                   change=pct(a["total"], ptot.get(key, 0.0)), last=a["last"].isoformat(), first_ever=first_ever[key].isoformat(),
                   spark=[round(v, 2) for v in a["spark"]], next=group_next(a["spark"][:-1] if partial_end else a["spark"]),
                   method=max(a["methods"], key=a["methods"].get), sheets=sorted(a["sheets"]))
        if by == "customer":
            ds = sorted(set(dates[key]))
            gaps = [(y - x).days for x, y in zip(ds, ds[1:])]
            row["cadence_days"] = statistics.median(gaps) if len(gaps) >= 3 else None
            row["days_since"] = (end - ds[-1]).days if ds else None
        out.append(row)
    if by in ("sheet", "method", "bank"):
        order = order_keys([r["key"] for r in out], by, deposit_banks)
        out.sort(key=lambda r: order.index(r["key"]))
    else:
        out.sort(key=lambda r: -r["total"])
    return out

# ------------------------------------------------------------------ storylines
NOUN = {"sheet": "payee", "customer": "client", "method": "payment method", "bank": "deposit bank"}

def _stories(c):
    S = []
    add = lambda id_, tone, title, text, **kw: S.append(dict(id=id_, tone=tone, title=title, text=text, **kw))
    kc, kp, g = c["kc"], c["kp"], c["grain"]
    rng = _range_label(c["start"], c["end"])
    if not c["cur"]:
        add("empty", "info", "No payments in this range", f"Nothing received between {rng} for the current filters. Widen the dates or clear a filter.")
        return S
    who = f"{c['cust'].title()} paid" if c["cust"] else "Receipts were"
    d = pct(kc["total"], kp["total"])
    if d is None:
        add("headline", "info", f"{money(kc['total'])} received", f"{who} {money(kc['total'])} across {kc['count']:,} payments ({rng}). "
            "There is nothing in the ledger for the period before it to compare with.")
    else:
        word = "up" if d >= 0 else "down"
        add("headline", "up" if d >= 0 else "down", f"{money(kc['total'])} received, {word} {abs(d):.0f}%",
            f"{who} {money(kc['total'])} across {kc['count']:,} payments ({rng}), {word} {abs(d):.0f}% on the same length of time before it "
            f"({money(kp['total'])} from {kp['count']:,} payments).")

    # projection / pace
    fc, pace = c["fc"], c["pace"]
    if pace:
        add("pace", "info", f"{pace['label']} is on pace for about {money(pace['value'])}",
            f"{money(pace['so_far'])} received in the first {pace['days_done']} of {pace['days_total']} business days. At the same daily rate "
            f"the period ends near {money(pace['value'])}.")
    if fc and fc["points"]:
        p0 = fc["points"][0]
        trend = ""
        if fc["slope_pct"] is not None and abs(fc["slope_pct"]) >= 1:
            trend = f" The underlying trend is {'rising' if fc['slope_pct'] > 0 else 'falling'} about {abs(fc['slope_pct']):.0f}% per {g}."
        add("forecast", "info", f"Next {g}: about {money(p0['value'])}",
            f"Projected {p0['label']}: {money(p0['value'])} (80% range {money(p0['low'])}–{money(p0['high'])}).{trend}")
        if fc["seasonal"] and fc["peak"]:
            sv = fc["seas"]
            add("season", "info", f"{MONTHS[fc['peak'] - 1]} is usually the strongest month",
                f"Over the last {fc['fitted_on']} months, {MONTHS[fc['peak'] - 1]} ran {(sv[fc['peak']] - 1) * 100:.0f}% above trend and "
                f"{MONTHS[fc['low_month'] - 1]} {(1 - sv[fc['low_month']]) * 100:.0f}% below.")

    bd, by = c["bd"], c["by"]
    if c["cust"]:
        _client_story(c, add)
    elif len(bd) >= 2:
        lead = max(bd, key=lambda r: r["total"])
        add("leader", "info", f"{lead['label']} leads with {lead['share']:.0f}%",
            f"{lead['label']} brought in {money(lead['total'])}, {lead['share']:.0f}% of receipts in this range, from {lead['count']:,} payments.",
            focus={by: lead["key"]})
        movers = [r for r in bd if r["prev_total"] > 0 or r["total"] > 0]
        up = max(movers, key=lambda r: r["total"] - r["prev_total"])
        dn = min(movers, key=lambda r: r["total"] - r["prev_total"])
        if up["total"] - up["prev_total"] > 0 and up["prev_total"] > 0:
            add("mover-up", "up", f"{up['label']} grew the most", f"{up['label']}: {money(up['total'])}, up {money(up['total'] - up['prev_total'])} "
                f"({pct(up['total'], up['prev_total']):+.0f}%) on the previous period.", focus={by: up["key"]})
        if dn is not up and dn["total"] - dn["prev_total"] < 0:
            add("mover-down", "down", f"{dn['label']} fell the most", f"{dn['label']}: {money(dn['total'])}, down {money(dn['prev_total'] - dn['total'])} "
                f"({pct(dn['total'], dn['prev_total']):+.0f}%) on the previous period.", focus={by: dn["key"]})

    if not c["cust"]:
        ct = Counter()
        for r in c["cur"]: ct[r["customer"]] += r["amount"]
        if len(ct) >= 10:
            top5 = sum(v for _, v in ct.most_common(5)) / kc["total"] * 100
            names = ", ".join(n.title() for n, _ in ct.most_common(3))
            add("concentration", "warn" if top5 >= 50 else "info", f"Top 5 clients = {top5:.0f}% of receipts",
                f"The five largest clients paid {top5:.0f}% of everything received ({names} lead). "
                + ("That is a concentrated book: losing one of them would show." if top5 >= 50 else "Receipts are spread across many clients."))
        first = {}
        for r in c["rows"]:
            if r["customer"] not in first or r["date"] < first[r["customer"]]: first[r["customer"]] = r["date"]
        new = {n for n in ct if first[n] >= c["start"]}
        oldest = min(first.values())
        if new and oldest < c["start"]:
            add("new-clients", "up", f"{len(new)} new client{'s' if len(new) != 1 else ''}",
                f"{len(new)} client{'s' if len(new) != 1 else ''} paid for the first time in this range, worth {money(sum(ct[n] for n in new))}. "
                f"Largest: {max(new, key=ct.get).title()} ({money(ct[max(new, key=ct.get)])}).")
        _lapsed(c, add)
        el = lambda rs: sum(r["amount"] for r in rs if r["method"] in ("card", "ach", "wire"))
        if kp["total"] and kc["total"]:
            a, b = el(c["cur"]) / kc["total"] * 100, el(c["prev"]) / kp["total"] * 100
            if abs(a - b) >= 5:
                add("mix", "info", f"Electronic payments {'up' if a > b else 'down'} to {a:.0f}%",
                    f"Card, ACH and wire made up {a:.0f}% of receipts, {'up' if a > b else 'down'} from {b:.0f}% in the previous period.")
    if c["largest"]:
        L = c["largest"]
        add("largest", "info", f"Largest payment: {money(L['amount'])}", f"{L['customer'].title()} paid {money(L['amount'])} to {L['sheet']} on "
            f"{L['date']:%b} {L['date'].day}, {L['date'].year}.", focus={"customer": L["customer"]})
    unset = sum(1 for r in c["cur"] if not r["taxable"] and not r["imported"])
    if unset:
        add("taxable", "warn", f"{unset} payment{'s' if unset != 1 else ''} without Taxable",
            f"{unset} payment{'s' if unset != 1 else ''} sent to Excel in this range still {'have' if unset != 1 else 'has'} Taxable not set. "
            "AR can set them in the Ledger (filter Taxable: Not set).")
    return S

def _client_story(c, add):
    rs, name = c["cur"], c["cust"].title()
    m = Counter(); sh = Counter()
    for r in rs: m[r["method"]] += r["amount"]; sh[r["sheet"]] += r["amount"]
    top_m = max(m, key=m.get)
    add("client-profile", "info", f"{name}: {len(rs)} payment{'s' if len(rs) != 1 else ''}, average {money(c['kc']['avg'])}",
        f"Mostly by {METHOD_LABEL[top_m].lower()} ({m[top_m] / c['kc']['total'] * 100:.0f}% of the value). Paid to "
        + ", ".join(f"{s} ({money(v)})" for s, v in sh.most_common()) + ".")
    ds = sorted({r["date"] for r in c["scoped"] if r["date"] <= c["end"]})
    if len(ds) >= 4:
        gaps = [(y - x).days for x, y in zip(ds, ds[1:])]
        cad = statistics.median(gaps); since = (c["end"] - ds[-1]).days
        late = since > max(2.5 * cad, 30)
        add("client-cadence", "warn" if late else "info", f"Usually pays every ~{cad:.0f} days",
            f"Last payment {ds[-1]:%b} {ds[-1].day}, {ds[-1].year}: {since} days before {c['end']:%b} {c['end'].day}. "
            + ("That is well past the usual gap, worth a call." if late else "That is within the usual rhythm."))
    first = min(r["date"] for r in c["scoped"])
    total_all = sum(r["amount"] for r in c["scoped"])
    add("client-lifetime", "info", f"Client since {first:%b} {first.year}",
        f"{money(total_all)} received in total from {len(c['scoped']):,} payments in the ledger.")

def _lapsed(c, add):
    end = c["end"]; yr = end - dt.timedelta(days=365)
    per = defaultdict(list); val = Counter()
    for r in c["scoped"]:
        if yr <= r["date"] <= end: per[r["customer"]].append(r["date"]); val[r["customer"]] += r["amount"]
    gone = []
    for n, ds in per.items():
        ds = sorted(set(ds))
        if len(ds) < 5: continue
        cad = statistics.median([(y - x).days for x, y in zip(ds, ds[1:])])
        since = (end - ds[-1]).days
        if since > max(2.5 * cad, 30): gone.append((val[n], n, since, cad))
    if gone:
        gone.sort(reverse=True)
        names = "; ".join(f"{n.title()} ({s} days, usually every {cad:.0f})" for _, n, s, cad in gone[:3])
        add("lapsed", "warn", f"{len(gone)} regular client{'s have' if len(gone) != 1 else ' has'} gone quiet",
            f"Clients who paid at least 5 times in the past year but not lately: {names}.", focus={"customer": gone[0][1]})
