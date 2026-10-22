"""The ledger is the source of truth: attachments, delete to a Deleted section (out of Excel), restore, Excel export."""
import io
import openpyxl
from PIL import Image
from checkflow.excel.layout import Layout

def sent(admin, **f):
    base = dict(method="check", customer="LIFE CO", sheet="MVC", amount="300.00", received="2026-11-12", payref="6101")
    p = admin.post("/api/payments", json={"fields": base | f}).json()
    admin.patch(f"/api/payments/{p['id']}", json={"status": "validated"})
    assert admin.post("/api/submit", json={"ids": [p["id"]]}).json()["written"] == 1
    return p["id"]

def row(admin, pid):
    return next((x for x in admin.get("/api/ledger").json()["rows"] if x["id"] == pid), None)

def mvc(admin):
    ws = openpyxl.load_workbook(admin.get("/api/settings").json()["workbook"])["MVC"]
    return ws, Layout(ws)

def pdf_bytes(pages=3):
    imgs = [Image.new("RGB", (400, 520), c) for c in ("white", "lightgray", "white")[:pages]]
    b = io.BytesIO(); imgs[0].save(b, "PDF", save_all=True, append_images=imgs[1:]); return b.getvalue()

def test_attachments_added_and_removed(admin):
    admin.post("/api/settings/practice")
    pid = sent(admin)
    p = admin.post(f"/api/payments/{pid}/attachments", files=[("files", ("card.pdf", pdf_bytes(3), "application/pdf")),
                                                              ("files", ("receipt.png", _png(), "image/png"))]).json()
    att = [x for x in p["pages"] if x["kind"] == "attachment"]
    assert len(att) == 4
    pdf = admin.get(f"/api/payments/{pid}/document.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pdf.content.count(b"/Type /Page") >= 4
    assert len(admin.delete(f"/api/payments/{pid}/attachments/{att[0]['id']}").json()["pages"]) == 3
    assert admin.post(f"/api/payments/{pid}/attachments", files={"files": ("photo.heic", b"x", "image/heic")}).status_code == 400

def _png():
    b = io.BytesIO(); Image.new("RGB", (200, 260), "white").save(b, "PNG"); return b.getvalue()

def test_delete_moves_out_of_ledger_and_excel_then_restore_puts_it_back(admin):
    admin.post("/api/settings/practice")
    a = sent(admin, customer="DELETE ME CO", amount="321.00")
    b = sent(admin, customer="KEEP ME CO", amount="45.00")
    r0 = row(admin, a)["row"]
    res = admin.post(f"/api/ledger/{a}/delete", json={"reason": "typed twice"}).json()
    assert res["excel"] == "synced"
    assert row(admin, a) is None and row(admin, b)
    gone = admin.get("/api/ledger/deleted").json()
    assert gone[0]["id"] == a and gone[0]["reason"] == "typed twice" and gone[0]["deleted_by"] == "admin"
    ws, lay = mvc(admin)
    assert ws.cell(r0, lay.cols["customer"]).value is None                     # emptied, no rows shifted
    assert ws.cell(row(admin, b)["row"], lay.cols["customer"]).value == "KEEP ME CO"
    an = admin.get("/api/analytics", params={"start": "2026-11-12", "end": "2026-11-12", "by": "customer"}).json()
    assert "DELETE ME CO" not in [x["key"] for x in an.get("breakdown", [])]
    # restore: back in the ledger and written into the workbook again
    assert admin.post(f"/api/ledger/{a}/restore").json()["excel"] == "synced"
    back = row(admin, a)
    ws, lay = mvc(admin)
    assert back and back["row"] and ws.cell(back["row"], lay.cols["customer"]).value == "DELETE ME CO"
    assert admin.get("/api/ledger/deleted").json() == []

def test_delete_and_restore_while_workbook_is_open(admin, app_module):
    import os
    admin.post("/api/settings/practice")
    a = sent(admin, customer="OPEN BOOK CO")
    r0 = row(admin, a)["row"]
    path = admin.get("/api/settings").json()["workbook"]
    lock = os.path.join(os.path.dirname(path), "~$" + os.path.basename(path))
    open(lock, "w").close()
    try:
        assert admin.post(f"/api/ledger/{a}/delete", json={}).json()["excel"] == "pending"
        assert admin.post(f"/api/ledger/{a}/restore").json()["excel"] == "synced"     # removal never ran: just cancelled
    finally:
        os.remove(lock)
    app_module.push_to_excel()
    ws, lay = mvc(admin)
    assert row(admin, a)["row"] == r0 and ws.cell(r0, lay.cols["customer"]).value == "OPEN BOOK CO"

def test_excel_export(admin):
    admin.post("/api/settings/practice")
    a = sent(admin, customer="EXPORT CO", amount="1,000.50", deposit_bank="TNB", taxable="Yes")
    x = admin.post("/api/ledger/export", json={"ids": [a]})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Ledger", "Daily bank totals"]
    led = wb["Ledger"]
    assert led["B2"].value == "EXPORT CO" and led["H2"].value == 1000.5 and led["A3"].value == "Total"
    t = wb["Daily bank totals"]
    assert [c.value for c in t[2]][:3] == ["2026-11-12", "TNB", 1] and t["H2"].value == 1000.5
