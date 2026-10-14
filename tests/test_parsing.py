"""Pure parsing helpers: routing checksum, money, dates, names, document parsers on synthetic OCR boxes."""
import pytest
from checkflow.extract.common import aba_ok, repair_aba, money, money_hand, parse_date, date_from_filename, customer_name, parse_written
from checkflow.extract import docs, group
from checkflow.extract.check import parse_micr, printed_numbers
from checkflow.registry import StaticRegistry

def box(t, x, y, w=None, h=16):
    return dict(t=t, s=0.95, x0=x, y0=y, x1=x + (w or 9 * len(t)), y1=y + h, a=0.0)

@pytest.mark.parametrize("r,ok", [("114915447", True), ("114917623", True), ("111322994", True), ("114915448", False),
                                  ("149116871", False), ("12345678", False)])
def test_aba(r, ok):
    assert aba_ok(r) is ok          # 149116871 passes the checksum but has an invalid Fed prefix (14)

def test_repair_aba():
    assert repair_aba("114915441") in (None, "114915447")

@pytest.mark.parametrize("s,v", [("$ **36,628.00", 36628.0), ("$2.788.00", 2788.0), ("206.478.65", 206478.65), ("no money", None)])
def test_money(s, v):
    assert money(s) == v

def test_money_handwritten():
    assert money_hand("5443S.07") == 54435.07

@pytest.mark.parametrize("s,iso", [("10/9/26", "2026-10-09"), ("October 9, 2026", "2026-10-09"), ("OCT/09/26", "2026-10-09"), ("13/45/26", None)])
def test_dates(s, iso):
    assert parse_date(s) == iso

@pytest.mark.parametrize("fn,iso", [("MVC OCT_09-26.pdf", "2026-10-09"), ("RVP OCT_09_26 1.pdf", "2026-10-09"), ("scan.pdf", None)])
def test_filename_date(fn, iso):
    assert date_from_filename(fn) == iso

@pytest.mark.parametrize("raw,name", [("Elite Utility & Paving, LLC", "ELITE UTILITY & PAVING"), ("COD-JUAN CANTU", "JUAN CANTU"),
                                      ("PENNY CONSTRUCT1ON", "PENNY CONSTRUCTION"), ("TURNER H. CONSTRUCTION", "TURNER H CONSTRUCTION"),
                                      ("JRGARCIACOMPANYLLC", "JRGARCIACOMPANY")])
def test_customer_name(raw, name):
    assert customer_name(raw) == name

def test_written_amount():
    assert parse_written("Forty-nine thousand seven hundred forty-four and 36 / 100 Dollars") == pytest.approx(49744.36)

def test_micr_symbols_and_runs():
    # transit symbols read as 1s, routing glued to the account, on-us check number before the routing
    r, acct, pre, _ = parse_micr(["10016241:1149116871:10201124574m"], [])
    assert r == "114911687" and acct.endswith("0201124574") and "1624" in "".join(pre)

def test_micr_known_routing_repairs_dropped_digit():
    r, *_ = parse_micr(["113229941728255290010057"], [], known={"111322994"})
    assert r == "111322994"

def test_printed_numbers_skip_dates_and_fractions():
    assert printed_numbers([box("10/08/2026", 0, 0), box("88-2299/1113", 0, 20), box("2427", 0, 40)]) == ["2427"]

def test_confirmation_parser_follows_skew():
    reg = StaticRegistry()
    items = [box("You Just Got Paid!", 60, 0), box("Customer", 60, 100), box("COD-JUAN CANTU", 600, 108),
             box("Payment Method", 60, 130), box("Mastercard **** 6759", 600, 139), box("Total", 60, 160), box("$141.81", 600, 170),
             box("Total Paid", 60, 190), box("$146.06", 600, 200), box("Description", 60, 220), box("QUOR3124", 600, 230)]
    for i in items: i["a"] = 0.016          # page scanned slightly tilted
    F, W = docs.parse_confirmation(items, reg)
    assert F["method"] == "card" and F["last4"] == "6759" and F["amount"] == "146.06" and F["customer"] == "JUAN CANTU"
    assert F["order"] == "QUOR3124"

def test_ach_confirmation():
    F, _ = docs.parse_confirmation([box("Payment Method", 60, 100), box("CHECKING **** 7801", 600, 100), box("Total", 60, 130), box("$5,763.23", 600, 130)], StaticRegistry())
    assert F["method"] == "ach" and F["payref"] == "7801" and F["amount"] == "5763.23"

def test_two_receipt_slips_on_one_page():
    items = [box("035407", 1080, 40), box("RECEIVED OF", 40, 190), box("Thank You", 940, 380),
             box("035408", 1080, 460), box("RECEIVED OF JR Garcia Company", 40, 600), box("5443S.07", 1060, 640), box("Thank You", 940, 800)]
    recs = docs.parse_receipts(items, 1650)
    assert [r[0]["ticket"] for r in recs] == ["35407", "35408"]
    assert recs[1][0]["amount_hint"] == "54435.07" and "Garcia" in recs[1][0]["customer_hint"]

def test_classify():
    assert docs.classify([box("CUSTOMER", 0, 0), box("TICKET", 0, 0), box("PAYMENT", 0, 0), box("DEPOSIT", 0, 0)]) == "sheet"
    assert docs.classify([box("DOB: 03/31/1997", 0, 0), box("CLASS: C", 0, 20)]) == "sensitive"
    assert docs.classify([box("Esperanza Homes Payment ACH Entry Memo Posted Today", 0, 0), box("$10,359.53", 900, 0)]) == "bankpost"

def test_grouping_pairs_receipts_in_order_and_falls_back_to_cash():
    recs = [dict(kind="receipt", page=3, y=100, fields={"ticket": "35407"}, warns={}),
            dict(kind="receipt", page=3, y=600, fields={"ticket": "35408", "amount_hint": "54435.07"}, warns={}),
            dict(kind="check", page=4, y=0, fields={"amount": "", "payref": "1624"}, warns={}),
            dict(kind="check", page=5, y=0, fields={"amount": "", "payref": "1625"}, warns={}),
            dict(kind="receipt", page=9, y=0, fields={"ticket": "35500", "amount_hint": "20.00"}, warns={})]
    pages = [dict(index=i, kind="check") for i in range(10)]
    pays = group(recs, pages)
    by_ref = {p["fields"].get("payref"): p for p in pays}
    assert by_ref["1624"]["fields"]["ticket"] == "35407"
    assert by_ref["1625"]["fields"]["ticket"] == "35408" and by_ref["1625"]["fields"]["amount"] == "54435.07"
    cash = [p for p in pays if p["fields"].get("method") == "cash"]
    assert len(cash) == 1 and cash[0]["fields"]["ticket"] == "35500"

def test_page_with_no_payment_becomes_a_card():
    """Nothing is dropped silently: a lone page with no recognisable payment still shows up for review."""
    pays = group([], [dict(index=0, kind="support")])
    assert len(pays) == 1 and "page" in pays[0]["warns"] and pays[0]["pages"] == [0]

def test_unreadable_check_page_becomes_its_own_card(monkeypatch):
    """A page that looks like a check but whose MICR line can't be read gets its own card (not hidden as a support page)."""
    import numpy as np, cv2
    import checkflow.extract as X
    monkeypatch.setattr(X, "analyze_page", lambda img, reg, received, batch=(): (img, "check?", [], []))
    ok, png = cv2.imencode(".png", np.full((60, 80, 3), 255, np.uint8))
    res = X.process(png.tobytes(), "photo.png", StaticRegistry(), "2026-10-13")
    assert len(res["payments"]) == 1
    p = res["payments"][0]
    assert p["fields"]["method"] == "check" and "bank line" in p["warns"]["page"] and p["fields"]["received"] == "2026-10-13"
