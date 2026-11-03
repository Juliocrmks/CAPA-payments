"""Daily report: the DEPOSIT TAXES sheet rebuilt from the ledger for one day, with formulas over a Payments sheet."""
import io, uuid
import openpyxl
import pytest
from fastapi.testclient import TestClient

def sent(admin, **f):
    base = dict(method="check", deposit_bank="TNB", customer="REPORT CO", sheet="MVC", amount="100.00", received="2027-03-03", payref="1")
    p = admin.post("/api/payments", json={"fields": base | f}).json()
    admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    assert admin.post("/api/submit", json={"ids": [p["id"]]}).json()["written"] == 1
    return p["id"]

@pytest.fixture(autouse=True)
def practice(admin):
    admin.post("/api/settings/practice")

BANKS = "LSB, LSBPAY, TNB, MID, REGIONS, BPS, PETTY CASH"

def test_daily_report_from_the_ledger(admin):
    admin.post("/api/settings", json={"deposit_banks": BANKS})
    tag = uuid.uuid4().hex[:4].upper()
    a = sent(admin, customer=f"A {tag}", amount="5200.00", deposit_bank="LSB", taxable="Yes")
    sent(admin, customer=f"B {tag}", amount="3000.00", deposit_bank="LONE STAR", taxable="No", method="cash", sheet="UVM")
    c = sent(admin, customer=f"C {tag}", amount="10000.00", deposit_bank="TNB")
    admin.post(f"/api/ledger/{c}/invoices", json={"lines": [dict(invoice="INV-1", amount="6000", taxable="Yes"),
                                                            dict(invoice="INV-2", amount="4000", taxable="No")]})
    sent(admin, customer=f"D {tag}", amount="-250.00", deposit_bank="TNB", method="cash")         # withdrawal: left out
    sent(admin, customer=f"E {tag}", amount="700.00", deposit_bank="MID", received="2027-03-01")  # Monday: week to date
    sent(admin, customer=f"F {tag}", amount="900.00", deposit_bank="TNB", received="2027-02-26")  # last week: not in it
    admin.patch(f"/api/ledger/{a}", json={"posted": "NS-1"})
    sent(admin, customer=f"G {tag}", amount="400.00", deposit_bank="BPS", taxable="Yes", method="card")    # BPS: LSB for taxes
    sent(admin, customer=f"H {tag}", amount="100.00", deposit_bank="PETTY CASH", taxable="Yes", method="cash")
    sent(admin, customer=f"I {tag}", amount="1000.00", deposit_bank="TNB", taxable="Yes", sheet="VCP")      # VCP: never taxable
    sent(admin, customer=f"J {tag}", amount="300.00", deposit_bank="REGIONS", taxable="Yes", sheet="RVP")   # its own bank

    r = admin.get("/api/reports/daily", params={"day": "2027-03-03"})
    assert r.status_code == 200 and 'filename="Daily report 2027-03-03.xlsx"' in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Daily report", "Payments", "Invoice splits"]
    pay = wb["Payments"]
    rows = {pay.cell(x, 3).value: [pay.cell(x, c).value for c in range(1, 20)] for x in range(2, pay.max_row) if pay.cell(x, 3).value}
    mine = {k: v for k, v in rows.items() if k.endswith(tag)}
    assert set(mine) == {f"{x} {tag}" for x in "ABCDEGHIJ"}                     # Monday through the day, not last week
    A, B, C, D, E = (mine[f"{x} {tag}"] for x in "ABCDE")
    assert (A[1], A[5], A[6], A[7], A[8], A[12], A[14]) == ("MVC", 5200, "LSB", "LSB", "Yes", "NS-1", "Yes")
    assert A[13] and A[9].startswith("=IF(I")                                  # posted by; taxable amount is a formula
    assert (B[1], B[7], B[3]) == ("UVM", "LSB", "Cash")                         # LONE STAR counts as LSB
    assert (C[8], C[15], C[16]) == ("Partial", 6000, "INV-1 6,000.00 taxable; INV-2 4,000.00 not taxable")
    assert (D[5], D[14]) == (-250, "No") and E[7] == "MIDFIRST"
    G, H, I, J = (mine[f"{x} {tag}"] for x in "GHIJ")
    assert (G[7], G[18], H[7], H[18], J[7], J[18], A[18]) == ("BPS", "LSB", "PETTY CASH", "LSB", "REGIONS", "REGIONS", "LSB")
    assert (I[1], I[8], I[9], I[10], I[11]) == ("VCP", "No", 0, "=F" + str(next(x for x in range(2, pay.max_row) if pay.cell(x, 3).value == f"I {tag}")), 0)
    spl = wb["Invoice splits"]
    assert [spl.cell(x, 5).value for x in range(2, spl.max_row + 1) if spl.cell(x, 3).value == f"C {tag}"] == ["INV-1", "INV-2"]

    rep = wb["Daily report"]
    assert rep["F3"].value == 0.0825 and rep["C3"].value.isoformat()[:10] == "2027-03-03"
    heads = [rep.cell(8, c).value for c in range(2, 15)]
    assert heads == ["COMPANY", "TOTAL DEPOSIT", "LSB", "LSBPAY", "TNB", "MIDFIRST", "REGIONS", "BPS", "PETTY CASH", "OTHER / NO BANK",
                     "PAYMENTS", "LEFT OUT OF DAILY TOTAL", None]
    assert [rep.cell(9 + i, 2).value for i in range(4)] == ["MVC", "UVM", "RVP", "VCP"]
    assert rep["C9"].value.startswith("=SUMIFS(Payments!$F:$F") and 'Payments!$O:$O,"Yes"' in rep["C9"].value
    texts = [str(c.value) for row in rep.iter_rows() for c in row if c.value]
    taxes = next(r for r in range(1, rep.max_row) if rep.cell(r, 2).value == "COMPANY" and rep.cell(r, 3).value == "DEPOSIT")
    assert [rep.cell(taxes, c).value for c in range(4, 12)] == ["LSB TAXABLE INCOME", "TNB TAXABLE INCOME", "MIDFIRST TAXABLE INCOME",
        "REGIONS TAXABLE INCOME", "WITHHOLD LSB", "WITHHOLD TNB", "WITHHOLD MIDFIRST", "WITHHOLD REGIONS"]
    assert 'Payments!$S:$S,"LSB"' in rep.cell(taxes + 1, 4).value                            # tax bank, not deposit column
    assert rep.cell(taxes, 4).comment.text == "Includes LSBPAY, BPS, PETTY CASH deposits."
    vcp = taxes + 4
    assert rep.cell(vcp, 2).value == "VCP" and {rep.cell(vcp, c).value for c in range(4, 12)} == {"N/A"}
    assert "LSB taxes include LSBPAY, BPS, PETTY CASH deposits." in texts
    assert "VCP is non-taxable income: all of it counts as not taxable." in texts
    assert any("have no deposit bank" in t for t in texts)
    week = [rep.cell(r, 2).value for r in range(taxes + 10, rep.max_row + 1)]
    assert "MVC" in week and "VCP" not in week                                               # VCP: nothing to withhold
    assert "WEEK TO DATE: TAX TO WITHHOLD" in texts and any("/(1+$F$3)" in t for t in texts)

def test_daily_report_rate_and_access(admin, client):
    assert admin.post("/api/settings", json={"sales_tax_rate": "8%"}).json()["sales_tax_rate"] == "8"
    assert admin.post("/api/settings", json={"sales_tax_rate": "abc"}).status_code == 400
    wb = openpyxl.load_workbook(io.BytesIO(admin.get("/api/reports/daily", params={"day": "2027-03-03"}).content))
    assert wb["Daily report"]["F3"].value == 0.08
    admin.post("/api/settings", json={"sales_tax_rate": "8.25"})
    assert admin.get("/api/reports/daily", params={"day": "03/03/2027"}).status_code == 400
    email = f"ro.{uuid.uuid4().hex[:5]}@example.com"
    admin.post("/api/users", json={"email": email, "role": "readonly", "password": "pw"})
    ro = TestClient(client.app); ro.post("/api/login", json={"username": email, "password": "pw"})
    assert ro.get("/api/reports/daily", params={"day": "2027-03-03"}).status_code == 200    # anyone who can export
    assert TestClient(client.app).get("/api/reports/daily", params={"day": "2027-03-03"}).status_code == 401

def test_deposit_bank_required_except_refunds(admin):
    base = dict(method="check", customer="NO BANK CO", sheet="MVC", received="2027-03-04", payref="9")
    def try_send(**f):
        p = admin.post("/api/payments", json={"fields": base | f}).json()
        admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
        return p["id"], admin.post("/api/submit", json={"ids": [p["id"]]}).json()
    _, r = try_send(amount="500.00", deposit_bank="")
    assert r["written"] == 0 and "deposit bank" in r["skipped"][0]["reason"]
    pid, r = try_send(amount="-75.00", deposit_bank="")                  # a refund / returned check: no bank needed
    assert r["written"] == 1
    assert admin.patch(f"/api/ledger/{pid}", json={"amount": "-80.00"}).status_code == 200
    pid, r = try_send(amount="500.00", deposit_bank="TNB")
    assert r["written"] == 1
    e = admin.patch(f"/api/ledger/{pid}", json={"deposit_bank": ""})
    assert e.status_code == 400 and "deposit bank" in e.json()["detail"]

def test_vcp_is_never_taxable(admin):
    base = dict(method="check", customer="VCP CO", sheet="VCP", amount="800.00", received="2027-03-05", deposit_bank="TNB", payref="3")
    p = admin.post("/api/payments", json={"fields": base}).json()
    assert p["fields"]["taxable"] == "No"                                        # new VCP payments default to No
    r = admin.patch(f"/api/payments/{p['id']}", json={"fields": {"taxable": "Yes"}})
    assert r.status_code == 400 and "non-taxable" in r.json()["detail"]
    other = admin.post("/api/payments", json={"fields": base | {"sheet": "MVC"}}).json()
    assert other["fields"]["taxable"] == ""                                      # other sheets still start Not set
    assert admin.patch(f"/api/payments/{other['id']}", json={"fields": {"sheet": "VCP"}}).json()["fields"]["taxable"] == "No"
    admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    assert admin.post("/api/submit", json={"ids": [p["id"]]}).json()["written"] == 1
    assert admin.patch(f"/api/ledger/{p['id']}", json={"taxable": "Yes"}).status_code == 400
    assert admin.post(f"/api/ledger/{p['id']}/invoices", json={"lines": [dict(invoice="I-1", amount="800", taxable="Yes")]}).status_code == 400
    # a ledger payment moved to VCP becomes Taxable = No
    m = admin.post("/api/payments", json={"fields": base | {"sheet": "MVC", "taxable": "Yes", "customer": "MOVE CO"}}).json()
    admin.patch(f"/api/payments/{m['id']}", json={"status": "validated"}); admin.post("/api/submit", json={"ids": [m["id"]]})
    assert admin.patch(f"/api/ledger/{m['id']}", json={"sheet": "VCP"}).status_code == 200
    f = next(x for x in admin.get("/api/ledger").json()["rows"] if x["id"] == m["id"])["fields"]
    assert f["taxable"] == "No"
    from checkflow.app import tax_parts
    assert tax_parts({"sheet": "VCP", "amount": "50", "taxable": "Yes"}) == (0.0, 50.0, 0.0)  # old rows marked Yes
