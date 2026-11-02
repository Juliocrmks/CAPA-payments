"""Daily report: the DEPOSIT TAXES sheet rebuilt from the ledger for one day, with formulas over a Payments sheet."""
import io, uuid
import openpyxl
import pytest
from fastapi.testclient import TestClient

def sent(admin, **f):
    base = dict(method="check", customer="REPORT CO", sheet="MVC", amount="100.00", received="2027-03-03", payref="1")
    p = admin.post("/api/payments", json={"fields": base | f}).json()
    admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    assert admin.post("/api/submit", json={"ids": [p["id"]]}).json()["written"] == 1
    return p["id"]

@pytest.fixture(autouse=True)
def practice(admin):
    admin.post("/api/settings/practice")

def test_daily_report_from_the_ledger(admin):
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

    r = admin.get("/api/reports/daily", params={"day": "2027-03-03"})
    assert r.status_code == 200 and 'filename="Daily report 2027-03-03.xlsx"' in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Daily report", "Payments", "Invoice splits"]
    pay = wb["Payments"]
    rows = {pay.cell(x, 3).value: [pay.cell(x, c).value for c in range(1, 19)] for x in range(2, pay.max_row) if pay.cell(x, 3).value}
    mine = {k: v for k, v in rows.items() if k.endswith(tag)}
    assert set(mine) == {f"{x} {tag}" for x in "ABCDE"}                         # Monday through the day, not last week
    A, B, C, D, E = (mine[f"{x} {tag}"] for x in "ABCDE")
    assert (A[1], A[5], A[6], A[7], A[8], A[12], A[14]) == ("MVC", 5200, "LSB", "LSB", "Yes", "NS-1", "Yes")
    assert A[13] and A[9].startswith("=IF(I")                                  # posted by; taxable amount is a formula
    assert (B[1], B[7], B[3]) == ("UVM", "LSB", "Cash")                         # LONE STAR counts as LSB
    assert (C[8], C[15], C[16]) == ("Partial", 6000, "INV-1 6,000.00 taxable; INV-2 4,000.00 not taxable")
    assert (D[5], D[14]) == (-250, "No") and E[7] == "MIDFIRST"
    spl = wb["Invoice splits"]
    assert [spl.cell(x, 5).value for x in range(2, spl.max_row + 1) if spl.cell(x, 3).value == f"C {tag}"] == ["INV-1", "INV-2"]

    rep = wb["Daily report"]
    assert rep["F3"].value == 0.0825 and rep["C3"].value.isoformat()[:10] == "2027-03-03"
    heads = [rep.cell(8, c).value for c in range(2, 12)]
    assert heads == ["COMPANY", "TOTAL DEPOSIT", "LSB", "TNB", "MIDFIRST", "BPS", "OTHER / NO BANK", "PAYMENTS", "LEFT OUT OF DAILY TOTAL", None]
    assert [rep.cell(9 + i, 2).value for i in range(4)] == ["MVC", "UVM", "RVP", "VCP"]
    assert rep["C9"].value.startswith("=SUMIFS(Payments!$F:$F") and 'Payments!$O:$O,"Yes"' in rep["C9"].value
    texts = [str(c.value) for row in rep.iter_rows() for c in row if c.value]
    assert {"WITHHOLD LSB", "WITHHOLD MIDFIRST", "WITHHOLD BPS", "BPS TAXABLE INCOME"} <= set(texts)            # BPS is taxed too
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
