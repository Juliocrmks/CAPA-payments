"""Turn an uploaded file (photo or multi-page scanned PDF) into payment records ready for review.

process(data, filename, reg) -> {"pages": [page...], "payments": [payment...]}
  page    = {index, kind, image(np), sensitive}
  payment = {fields, warns, pages: [page index...], primary: page index, sources: [kinds]}
"""
from .ocr import load_pages, orient, rotate, ocr, cy_, jpeg, engine  # noqa: F401  (re-exported)
from .common import date_from_filename, parse_date, money
from .check import parse_check, looks_like_check
from .docs import classify, parse_confirmation, parse_receipts, parse_bankpost, parse_total_paid, match_hint

PRIMARY = ("check", "confirmation", "bankpost", "receipt")

def analyze_page(img, reg, received, batch_routings=(), partial=False):
    deg = orient(img)
    img = rotate(img, deg)
    items = ocr(img)
    H = img.shape[0]
    kind = classify(items)
    recs = []
    if kind in ("sheet", "blank", "sensitive", "email"):
        return img, kind, recs, items
    if kind == "confirmation_cont":       # 2nd page of a TransactPro e-mail: carries 'Total Paid' (amount incl. fees)
        tp = parse_total_paid(items)
        if tp is not None: recs.append(dict(kind="total_paid", fields={"amount": f"{tp:.2f}"}, warns={}, y=0))
        return img, "support", recs, items
    receipts = parse_receipts(items, H)
    for F, W, top, bot in receipts:
        recs.append(dict(kind="receipt", fields=F, warns=W, y=(top + bot) / 2))
    rest = items
    if receipts:   # what is left on the page outside the receipt slips (e.g. a confirmation printed below)
        rest = [i for i in items if not any(top <= cy_(i) <= bot for _, _, top, bot in receipts)]
    if kind == "confirmation":
        conf_items = rest if receipts else items
        F, W = parse_confirmation(conf_items, reg)
        recs.append(dict(kind="confirmation", fields=F, warns=W, y=min((cy_(i) for i in conf_items), default=0)))
    elif kind == "bankpost":
        F, W = parse_bankpost(items, reg)
        recs.append(dict(kind="bankpost", fields=F, warns=W, y=0))
    elif len(rest) >= 5 and looks_like_check(rest):
        r = parse_check(img, rest, reg, received, batch_routings, partial=partial)
        if r:
            recs.append(dict(kind="check", fields=r[0], warns=r[1], y=0))
            kind = "check"
        else:
            kind = "check?"   # looks like a check but the MICR line was unreadable; retried after the batch
    if not recs and kind != "check?": kind = "receipt" if receipts else ("support" if kind == "other" else kind)
    elif receipts and kind == "other": kind = "receipt"
    return img, kind, recs, items

def group(records, pages):
    """Pair receipt slips with the payment they document and hang support pages on the nearest payment."""
    pays = [dict(fields=dict(r["fields"]), warns=dict(r["warns"]), pages=[r["page"]], primary=r["page"], sources=[r["kind"]])
            for r in records if r["kind"] not in ("receipt", "total_paid")]
    # 'Total Paid' continuation page -> the confirmation right before it
    for r in records:
        if r["kind"] != "total_paid": continue
        prev = [p for p in pays if p["primary"] < r["page"] and "confirmation" in p["sources"]]
        if prev and r["page"] - prev[-1]["primary"] <= 2:
            prev[-1]["fields"]["amount"] = r["fields"]["amount"]; prev[-1]["warns"].pop("amount", None)
            prev[-1]["pages"] = sorted(set(prev[-1]["pages"] + [r["page"]]))
    receipts = {}
    for r in sorted((r for r in records if r["kind"] == "receipt"), key=lambda r: (r["page"], r["y"])):
        key = r["fields"].get("ticket") or f"p{r['page']}y{int(r['y'])}"
        if key in receipts: receipts[key]["pages"].append(r["page"])          # duplicate copy of the same slip
        else: receipts[key] = dict(r, pages=[r["page"]])
    taken = set()
    for rec in receipts.values():
        best, bs = None, 0
        ahead = [n for n, p in enumerate(pays) if n not in taken and p["primary"] >= rec["page"]]
        for n, p in enumerate(pays):
            if n in taken: continue
            s = 0
            ah, pa = money(rec["fields"].get("amount_hint", "") or ""), money(p["fields"].get("amount", "") or "")
            if ah is not None and pa is not None and abs(ah - pa) < 0.01: s += 4
            if match_hint(rec["fields"].get("customer_hint"), p["fields"].get("customer")) >= 70: s += 2
            d = p["primary"] - rec["page"]
            if d < 0 or d > 3: s -= 2
            elif ahead and n == ahead[0]: s += 3          # the next unpaired payment after the slip
            elif len(ahead) > 1 and n == ahead[1]: s += 1
            if s > bs: best, bs = n, s
        if best is not None and bs >= 3:
            p = pays[best]; taken.add(best)
            p["fields"]["ticket"] = rec["fields"].get("ticket", "")
            if rec["warns"].get("ticket"): p["warns"]["ticket"] = rec["warns"]["ticket"]
            if not p["fields"].get("amount") and rec["fields"].get("amount_hint"):
                p["fields"]["amount"] = rec["fields"]["amount_hint"]
                p["warns"]["amount"] = "Taken from the handwritten receipt. Verify against the check."
            if not p["fields"].get("customer") and rec["fields"].get("customer_hint"):
                p["fields"]["customer_raw"] = rec["fields"]["customer_hint"]
            p["sources"].append("receipt")
            p["pages"] = sorted(set(p["pages"] + rec["pages"]))
        else:   # a receipt with no matching check/card/wire: most likely a cash payment
            F = dict(method="cash", ticket=rec["fields"].get("ticket", ""))
            if rec["fields"].get("amount_hint"): F["amount"] = rec["fields"]["amount_hint"]
            if rec["fields"].get("customer_hint"): F["customer_raw"] = rec["fields"]["customer_hint"]
            W = dict(rec["warns"], method="Receipt only. Confirm this was cash.", amount="Handwritten amount. Verify.",
                     customer="Handwritten name. Type the customer.")
            pays.append(dict(fields=F, warns=W, pages=list(rec["pages"]), primary=rec["page"], sources=["receipt"]))
    pays.sort(key=lambda p: p["primary"])
    # support / e-mail / sensitive pages: attach to the payment printed right before them (e-mail headers: right after)
    for pg in pages:
        if pg["kind"] in ("sheet", "blank") or any(pg["index"] in p["pages"] for p in pays): continue
        target = None
        if pg["kind"] == "email":
            target = next((p for p in pays if p["primary"] >= pg["index"]), None)
        if target is None:
            prev = [p for p in pays if p["primary"] <= pg["index"]]
            target = prev[-1] if prev else (pays[0] if pays else None)
        if target: target["pages"] = sorted(set(target["pages"] + [pg["index"]]))
        else:
            pays.append(dict(fields={"method": "check"}, pages=[pg["index"]], primary=pg["index"], sources=["unread"],
                             warns={"page": "Couldn't find a payment on this page. Fill it in from the image, or remove it."}))
    return pays

def process(data, filename, reg, received=None, progress=None):
    received = received or date_from_filename(filename)
    imgs = load_pages(data, filename)
    pages, records, retry = [], [], []
    for k, img in enumerate(imgs):
        if progress: progress(k, len(imgs))
        up, kind, recs, items = analyze_page(img, reg, received)
        pages.append(dict(index=k, kind=kind, image=up, sensitive=kind == "sensitive"))
        for r in recs: records.append(dict(r, page=k))
        if kind == "check?": retry.append(k)
    seen = {r["fields"]["routing"] for r in records if r["fields"].get("routing")}
    for k in retry:
        up, kind, recs, _ = analyze_page(pages[k]["image"], reg, received, seen, partial=True)
        pages[k]["kind"] = "check" if kind == "check?" else kind
        if kind == "check?":
            records.append(dict(kind="check", page=k, y=0, fields={"method": "check"},
                                warns={"page": "Looks like a check, but the bank line at the bottom couldn't be read. Type the details from the image."}))
        for r in recs:
            if not any(x["page"] == k and x["kind"] == r["kind"] for x in records): records.append(dict(r, page=k))
    records.sort(key=lambda r: (r["page"], r["y"]))
    # the same bank account in one batch is the same customer: share the cleanest name
    by_acct = {}
    for r in records:
        f = r["fields"]
        if f.get("routing") and f.get("account") and f.get("customer"):
            cur = by_acct.get((f["routing"], f["account"]))
            if not cur or (" " in f["customer"] and " " not in cur): by_acct[(f["routing"], f["account"])] = f["customer"]
    for r in records:
        f = r["fields"]; c = by_acct.get((f.get("routing"), f.get("account")))
        if c and (not f.get("customer") or " " not in f["customer"]): f["customer"] = c
    pays = group(records, pages)
    sheet_hint = reg.payee_from_filename(filename)
    for p in pays:
        F = p["fields"]
        F.setdefault("received", received or "")
        if not F.get("sheet") and sheet_hint: F["payee"], F["sheet"] = sheet_hint
        if not F.get("sheet"): p["warns"]["sheet"] = "Pick the payee sheet."
        if F.get("customer") and reg.is_known_customer(F["customer"]): p["warns"].pop("customer", None)
        d = reg.defaults_for(F.get("customer", ""), F.get("method", ""))
        for k, v in d.items():
            if v and not F.get(k): F[k] = v
    return dict(pages=pages, payments=pays, received=received)
