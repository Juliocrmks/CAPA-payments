"""The whole flow through the API: create -> review -> pending -> validate -> send -> ledger edit -> Excel, plus learned data."""
import openpyxl
from fastapi.testclient import TestClient
from checkflow import db
from checkflow.excel.layout import Layout

def new(admin, **f):
    base = dict(method="check", customer="ACME BUILDERS", sheet="MVC", amount="125.00", received="2026-10-09", payref="501")
    return admin.post("/api/payments", json={"fields": base | f}).json()

def test_review_pending_validate_send_and_ledger(admin, client):
    admin.post("/api/settings/practice")
    a = new(admin, payref="1001", routing="114915447", account="99887766")
    b = new(admin, method="card", amount="10.00", payref="6759", customer="JUAN CANTU", ticket="35391")
    assert a["status"] == "review" and a["fields"]["bank"] == ""
    # edits: checksum warning, sheet from payee, amount normalised
    r = admin.patch(f"/api/payments/{a['id']}", json={"fields": {"routing": "114915448", "amount": "$1,234.5"}}).json()
    assert "routing" in r["warns"] and r["fields"]["amount"] == "1234.50"
    r = admin.patch(f"/api/payments/{a['id']}", json={"fields": {"routing": "114915447"}}).json()
    assert "routing" not in r["warns"] and r["fields"]["bank"] == "Rio Bank"
    # pending and back
    assert admin.patch(f"/api/payments/{b['id']}", json={"status": "pending"}).json()["status"] == "pending"
    assert any(p["id"] == b["id"] for p in admin.get("/api/payments?status=pending").json())
    for p in (a, b): admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    res = admin.post("/api/submit", json={"ids": [a["id"], b["id"]]}).json()
    assert res["written"] == 2 and res["sheets"] == {"MVC": 2}
    # ledger + learned
    L = admin.get("/api/ledger").json()["rows"]
    row = next(x for x in L if x["id"] == a["id"])
    assert row["sheet"] == "MVC" and row["row"]
    learned = admin.get("/api/learned").json()
    assert any(x["customer"] == "ACME BUILDERS" and x["account"] == "99887766" for x in learned["accounts"])
    # AR sets taxable -> Excel cell changes
    admin.post("/api/users", json={"username": "ar_flow", "password": "arpass1", "role": "ar"})
    ar = TestClient(client.app); ar.post("/api/login", json={"username": "ar_flow", "password": "arpass1"})
    assert ar.patch(f"/api/ledger/{a['id']}", json={"taxable": "Yes"}).json()["excel"] == "synced"
    assert ar.patch(f"/api/ledger/{a['id']}", json={"deposit_bank": "LSB"}).status_code == 403
    wb = openpyxl.load_workbook(admin.get("/api/settings").json()["workbook"]); ws = wb["MVC"]; lay = Layout(ws)
    r_ = next(x for x in admin.get("/api/ledger").json()["rows"] if x["id"] == a["id"])["row"]
    assert ws.cell(r_, lay.cols["taxable"]).value == "YES"
    # sent payments are locked in the review queue and show up as duplicates if scanned again
    assert admin.patch(f"/api/payments/{a['id']}", json={"fields": {"amount": "1"}}).status_code == 409
    again = new(admin, payref="1001", routing="114915447", account="99887766", amount="1234.50", check_no="1001")
    assert "Already sent" in (again["warns"].get("duplicate") or "")

def test_submit_skips_incomplete_and_unknown_sheet(admin):
    admin.post("/api/settings/practice")
    a = new(admin, customer=""); b = new(admin, sheet="NOT_A_SHEET")
    for p in (a, b): admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    res = admin.post("/api/submit", json={"ids": [a["id"], b["id"]]}).json()
    assert res["written"] == 0 and len(res["skipped"]) == 2

def test_excel_open_keeps_edit_pending(admin):
    from checkflow.excel import writer
    admin.post("/api/settings/practice")
    a = new(admin, payref="777", customer="LOCKED OUT")
    admin.patch(f"/api/payments/{a['id']}", json={"status": "validated"}); admin.post("/api/submit", json={"ids": [a["id"]]})
    wbp = admin.get("/api/settings").json()["workbook"]
    open(writer.lock_path(wbp), "w").close()
    try:
        r = admin.patch(f"/api/ledger/{a['id']}", json={"taxable": "No"}).json()
        assert r["excel"] == "pending"
        assert next(x for x in admin.get("/api/ledger").json()["rows"] if x["id"] == a["id"])["pending"]
    finally:
        import os; os.remove(writer.lock_path(wbp))
    from checkflow.app import push_to_excel
    assert push_to_excel()[0] == 0
    assert not next(x for x in admin.get("/api/ledger").json()["rows"] if x["id"] == a["id"])["pending"]

def test_learned_crud_and_customer_defaults(admin):
    admin.put("/api/learned/customers", json={"name": "Default Co", "taxable_default": "Yes", "deposit_bank_default": "MID"})
    p = admin.post("/api/payments", json={"fields": {"customer": "DEFAULT CO", "method": "check", "amount": "1"}}).json()
    assert p["fields"]["taxable"] == "Yes" and p["fields"]["deposit_bank"] == "MID"
    admin.put("/api/learned/payees", json={"name": "Test Division", "sheet": "VCP", "aliases": "TD"})
    assert db.registry().payee_from_filename("TD OCT_10_26.pdf") == ("Test Division", "VCP")
    admin.delete("/api/learned/customers?key=DEFAULT%20CO")
    assert not any(c["name"] == "DEFAULT CO" for c in admin.get("/api/learned").json()["customers"])

def test_import_customers_and_history(admin):
    admin.post("/api/settings/practice")
    assert admin.post("/api/import", json={"what": "customers"}).json()["imported"] >= 1
    n = admin.post("/api/import", json={"what": "history"}).json()["imported"]
    assert n >= 1 and admin.post("/api/import", json={"what": "history"}).json()["imported"] == 0   # idempotent
    assert any(r["imported"] for r in admin.get("/api/ledger").json()["rows"])

def test_audit_records_actions(admin):
    acts = [a["action"] for a in admin.get("/api/audit").json()]
    assert "login" in acts
