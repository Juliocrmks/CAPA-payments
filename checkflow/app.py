"""CheckFlow API + static UI. Run with:  python run.py   (or CheckFlow.command / run.bat)"""
import os, json, threading, queue, datetime, uuid, traceback
import cv2
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, auth, config
from .auth import require_user, require_admin
from .excel import writer, importer

app = FastAPI(title="CheckFlow")
WB_LOCK = threading.Lock()

def startup():
    db.init()
    auth.seed_admin()
startup()

def workbook_path():
    p = db.get_setting("workbook", "")
    if not p:
        p = os.path.join(config.DATA, "Practice_Workbook.xlsx")
        if not os.path.exists(p):
            from .excel.practice import make_practice
            make_practice(p)
        db.set_setting("workbook", p)
    return p

def ignore_list(): return [s.strip() for s in (db.get_setting("ignore_sheets") or "").split(",") if s.strip()]

def sheets():
    try: return [s for s in writer.list_sheets(workbook_path(), ignore_list()) if s]
    except Exception: return []

# ================================================================== auth
class Cred(BaseModel):
    username: str
    password: str

@app.get("/api/me")
def me(request: Request):
    return dict(user=auth.current_user(request), auth_mode=db.get_setting("auth_mode"))

@app.post("/api/login")
def login(c: Cred, request: Request, response: Response):
    tok = auth.login(c.username, c.password, request.client.host if request.client else "")
    response.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax", max_age=auth.TTL)
    return {"ok": True}

@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE, "")); response.delete_cookie(auth.COOKIE); return {"ok": True}

class PwChange(BaseModel):
    current: str
    new: str

@app.post("/api/me/password")
def change_password(p: PwChange, user=Depends(require_user)):
    if user["source"] != "local": raise HTTPException(400, "Your password is managed by Active Directory.")
    if not auth._local_check(user["username"], p.current): raise HTTPException(400, "Current password is wrong.")
    auth.set_password(user["id"], p.new)
    db.audit(user["username"], "password_changed")
    return {"ok": True}

@app.get("/api/users")
def users(_=Depends(require_admin)):
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT id, username, role, source, display_name, active, must_change, last_login FROM users ORDER BY id")]

class NewUser(BaseModel):
    username: str
    password: str = ""
    role: str = "ar"

@app.post("/api/users")
def add_user(u: NewUser, me_=Depends(require_admin)):
    auth.create_user(u.username, u.password, u.role)
    db.audit(me_["username"], "user_added", target=u.username, role=u.role)
    return users()

class UserPatch(BaseModel):
    password: str | None = None
    active: bool | None = None
    role: str | None = None

@app.patch("/api/users/{uid}")
def edit_user(uid: int, p: UserPatch, me_=Depends(require_admin)):
    if p.password: auth.set_password(uid, p.password)
    with db._lock, db.conn() as c:
        if p.active is not None:
            if uid == me_["id"] and not p.active: raise HTTPException(400, "You can't disable your own account.")
            c.execute("UPDATE users SET active=? WHERE id=?", (int(p.active), uid))
            if not p.active: c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if p.role in ("admin", "ar"):
            if uid == me_["id"] and p.role != "admin": raise HTTPException(400, "You can't remove your own admin role.")
            c.execute("UPDATE users SET role=? WHERE id=?", (p.role, uid))
    db.audit(me_["username"], "user_changed", target=uid, **p.model_dump(exclude_none=True, exclude={"password"}))
    return users()

# ================================================================== settings
SETTING_KEYS = ["workbook", "ignore_sheets", "deposit_banks", "deposit_bank_check", "deposit_bank_cash", "deposit_bank_card",
                "deposit_bank_ach", "deposit_bank_wire", "keep_sensitive_pages", "auth_mode", "ldap_server", "ldap_domain",
                "ldap_upn_suffix", "ldap_base_dn", "ldap_admin_group", "ldap_ar_group"]

@app.get("/api/settings")
def get_settings(_=Depends(require_admin)):
    s = db.settings(); p = workbook_path()
    return dict({k: s.get(k, "") for k in SETTING_KEYS}, workbook=p, workbook_exists=os.path.exists(p),
                workbook_open=os.path.exists(writer.lock_path(p)), sheets=sheets(), methods=config.METHODS)

@app.post("/api/settings")
def save_settings(s: dict, me_=Depends(require_admin)):
    for k, v in s.items():
        if k not in SETTING_KEYS: continue
        if k == "workbook":
            v = (v or "").strip().strip('"').strip("'")
            if v and not os.path.exists(v): raise HTTPException(400, "That workbook file doesn't exist. Check the path.")
            if v and not v.lower().endswith((".xlsx", ".xlsm")): raise HTTPException(400, "Choose an .xlsx or .xlsm workbook.")
        if k == "auth_mode" and v not in ("local", "ldap"): raise HTTPException(400, "Sign-in must be local or ldap.")
        db.set_setting(k, v)
    db.audit(me_["username"], "settings_changed", keys=[k for k in s if k in SETTING_KEYS])
    return get_settings()

@app.post("/api/settings/practice")
def practice(me_=Depends(require_admin)):
    from .excel.practice import make_practice
    p = os.path.join(config.DATA, "Practice_Workbook.xlsx"); make_practice(p); db.set_setting("workbook", p)
    return get_settings()

class LdapTest(BaseModel):
    username: str
    password: str
    settings: dict = {}

@app.post("/api/settings/test-ldap")
def test_ldap(t: LdapTest, _=Depends(require_admin)):
    from . import ldap_auth
    s = db.settings() | {k: v for k, v in t.settings.items() if k.startswith("ldap_")}
    if not s.get("ldap_server"): raise HTTPException(400, "Enter the AD server first.")
    return ldap_auth.test(s, t.username, t.password)

# ================================================================== upload + background extraction
JOBS: "queue.Queue[tuple]" = queue.Queue()

def _worker():
    from . import extract
    while True:
        doc_id, path, filename, received, sheet_hint = JOBS.get()
        try:
            db.update_document(doc_id, status="processing", progress=0.02)
            reg = db.registry()
            def prog(k, n): db.update_document(doc_id, progress=round(0.05 + 0.9 * k / max(n, 1), 3), pages=n)
            data = open(path, "rb").read()
            res = extract.process(data, filename, reg, received or None, progress=prog)
            keep_sensitive = db.get_setting("keep_sensitive_pages") == "1"
            page_ids = {}
            for pg in res["pages"]:
                img = pg["image"]
                if pg["sensitive"] and not keep_sensitive:       # ID / card photos: keep only an unreadable placeholder
                    img = cv2.resize(cv2.resize(img, (24, 32)), (img.shape[1] // 4, img.shape[0] // 4), interpolation=cv2.INTER_NEAREST)
                name = f"{uuid.uuid4().hex}.jpg"
                with open(os.path.join(config.IMAGES, name), "wb") as fh: fh.write(extract.jpeg(img))
                page_ids[pg["index"]] = db.add_page(doc_id, pg["index"], pg["kind"], name, pg["sensitive"])
            for p in res["payments"]:
                f = dict(p["fields"])
                if sheet_hint and not f.get("sheet"):
                    f["sheet"] = sheet_hint; p["warns"].pop("sheet", None)
                if not f.get("received"): f["received"] = received or datetime.date.today().isoformat()
                db.add_payment(doc_id, f, p["warns"], p["sources"], [page_ids[i] for i in p["pages"] if i in page_ids])
            unread = sum(1 for p in res["payments"] if "page" in p["warns"])
            db.update_document(doc_id, status="done", progress=1, pages=len(res["pages"]), received=res.get("received") or received or "",
                               error=(f"{unread} page{'s' if unread > 1 else ''} need typing in" if unread else None),
                               found=len(res["payments"]))
        except Exception as e:
            traceback.print_exc()
            db.update_document(doc_id, status="error", error=f"{type(e).__name__}: {e}"[:400])
        finally:
            try: os.remove(path)
            except OSError: pass
            JOBS.task_done()

threading.Thread(target=_worker, daemon=True).start()

@app.post("/api/documents")
async def upload(files: list[UploadFile] = File(...), received: str = Form(""), sheet: str = Form(""), user=Depends(require_admin)):
    out = []
    os.makedirs(os.path.join(config.DATA, "uploads"), exist_ok=True)
    for f in files:
        name = f.filename or "upload"
        if not name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".webp", ".bmp")):
            raise HTTPException(400, f"{name}: upload PDF or image files.")
        path = os.path.join(config.DATA, "uploads", uuid.uuid4().hex + os.path.splitext(name)[1].lower())
        with open(path, "wb") as fh: fh.write(await f.read())
        doc_id = db.add_document(name, received, user["username"])
        JOBS.put((doc_id, path, name, received, sheet))
        out.append(db.get_document(doc_id))
    db.audit(user["username"], "uploaded", files=[o["filename"] for o in out])
    return out

@app.get("/api/documents/{doc_id}")
def document(doc_id: int, _=Depends(require_admin)):
    d = db.get_document(doc_id)
    if not d: raise HTTPException(404)
    return d

@app.get("/api/pages/{page_id}")
def page_image(page_id: int, user=Depends(require_user)):
    p = db.page_file(page_id)
    if not p: raise HTTPException(404)
    if p["sensitive"] and user["role"] != "admin": raise HTTPException(403)
    path = os.path.join(config.IMAGES, p["image"])
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

# ================================================================== review queue
@app.get("/api/payments")
def payments(status: str = "review,validated", _=Depends(require_admin)):
    return db.list_payments(status.split(","))

class NewPayment(BaseModel):
    fields: dict = {}

@app.post("/api/payments")
def new_payment(p: NewPayment, user=Depends(require_admin)):
    """Manual entry (e.g. cash with no paperwork scanned)."""
    f = dict(p.fields); f.setdefault("method", "cash"); f.setdefault("received", datetime.date.today().isoformat())
    if f.get("customer"): f.update({k: v for k, v in db.registry().defaults_for(f["customer"], f["method"]).items() if not f.get(k)})
    pid = db.add_payment(None, f, {}, ["manual"], [])
    db.audit(user["username"], "payment_added", pid)
    return db.get_payment(pid)

class Patch(BaseModel):
    fields: dict | None = None
    status: str | None = None

@app.patch("/api/payments/{pid}")
def patch_payment(pid: int, p: Patch, user=Depends(require_admin)):
    if p.status and p.status not in ("review", "validated", "pending"): raise HTTPException(400, "Bad status")
    try: r = db.update_payment(pid, p.fields, p.status)
    except ValueError as e: raise HTTPException(409, str(e))
    if not r: raise HTTPException(404)
    if p.status: db.audit(user["username"], "status_" + p.status, pid)
    return r

@app.delete("/api/payments/{pid}")
def delete_payment(pid: int, user=Depends(require_admin)):
    try: db.delete_payment(pid)
    except ValueError as e: raise HTTPException(409, str(e))
    db.audit(user["username"], "payment_deleted", pid)
    return {"ok": True}

class PageMove(BaseModel):
    page_id: int
    to: int | None = None

@app.post("/api/payments/{pid}/move-page")
def move_page(pid: int, m: PageMove, user=Depends(require_admin)):
    new = db.move_page(m.page_id, pid, m.to)
    return dict(source=db.get_payment(pid), target=db.get_payment(new))

# ================================================================== submit to Excel
class Submit(BaseModel):
    ids: list[int]

REQUIRED = {"customer": "customer", "sheet": "payee sheet", "amount": "amount", "received": "date received", "method": "payment method"}

@app.post("/api/submit")
def submit(s: Submit, user=Depends(require_admin)):
    items, skipped, rows = [], [], {p["id"]: p for p in db.list_payments(["validated"])}
    valid = set(sheets())
    for pid in s.ids:
        p = rows.get(pid)
        if not p: skipped.append(dict(id=pid, reason="Not validated.")); continue
        f = p["fields"]
        missing = [label for k, label in REQUIRED.items() if not f.get(k)]
        if missing: skipped.append(dict(id=pid, reason="Missing " + ", ".join(missing) + ".")); continue
        if f["sheet"] not in valid: skipped.append(dict(id=pid, reason=f"Sheet '{f['sheet']}' is not in the workbook.")); continue
        if (p["warns"].get("duplicate") or "").startswith("Already sent"): skipped.append(dict(id=pid, reason=p["warns"]["duplicate"])); continue
        items.append(dict(id=pid, **{k: f.get(k, "") for k in ("sheet", "received", "customer", "order", "ticket", "payref", "method",
                                                                 "amount", "taxable", "deposit_bank")}))
    written = {}
    if items:
        path = workbook_path()
        try:
            with WB_LOCK: written = writer.write_payments(path, items)
        except writer.WorkbookError as e:
            raise HTTPException(409, str(e))
        reg = db.registry()
        for it in items:
            sheet, row = written[it["id"]]
            db.mark_submitted(it["id"], path, sheet, row, user["username"])
            reg.learn(rows[it["id"]]["fields"])
        _relocate({(it["sheet"], it["received"]) for it in items})
        db.audit(user["username"], "submitted", ids=list(written), sheets=sorted({v[0] for v in written.values()}))
    per = {}
    for sheet, _ in written.values(): per[sheet] = per.get(sheet, 0) + 1
    return dict(written=len(written), sheets=per, skipped=skipped, workbook=workbook_path())

def _relocate(days):
    """After a day block is rebuilt, earlier rows of that day moved: refresh the remembered row numbers."""
    import openpyxl
    from .excel.layout import Layout
    try: wb = openpyxl.load_workbook(workbook_path(), read_only=False)
    except Exception: return
    upd = {}
    for sheet, day in days:
        if sheet not in wb.sheetnames: continue
        lay = Layout(wb[sheet])
        for p in db.submitted_on(sheet, day):
            r = writer.find_row(lay, p["fields"], p["row"])
            if r and r != p["row"]: upd[p["id"]] = r
    db.set_rows(upd)

# ================================================================== ledger
@app.get("/api/ledger")
def ledger(user=Depends(require_user)):
    rows = db.ledger_rows()
    if user["role"] != "admin":
        for r in rows: r["pages"] = [p for p in r["pages"] if not p["sensitive"]]
    return dict(rows=rows, sheets=sheets(), deposit_banks=[b.strip() for b in (db.get_setting("deposit_banks") or "").split(",") if b.strip()])

class LedgerPatch(BaseModel):
    taxable: str | None = None
    deposit_bank: str | None = None

def push_to_excel():
    rows = db.dirty_rows()
    if not rows: return 0, ""
    ups = []
    for r in rows:
        f = r["fields"]
        ups.append(dict(id=r["id"], sheet=r["sheet"], row=r["row"], received=f.get("received"), customer=f.get("customer"),
                        amount=f.get("amount"), taxable=f.get("taxable", ""), deposit_bank=f.get("deposit_bank", "")))
    try:
        with WB_LOCK: res = writer.update_rows(workbook_path(), ups)
    except writer.WorkbookError as e:
        msg = "The workbook is open in Excel. Your change is saved and will be written automatically once it is closed." \
              if "open in Excel" in str(e) else str(e)
        for r in rows: db.sync_result(r["id"], note=msg)
        return len(rows), msg
    left, msg = 0, ""
    for pid, (st, v) in res.items():
        if st == "ok": db.sync_result(pid, row=v)
        else: db.sync_result(pid, note=v); left += 1; msg = v
    return left, msg

@app.patch("/api/ledger/{pid}")
def ledger_patch(pid: int, p: LedgerPatch, user=Depends(require_user)):
    if user["role"] != "admin" and p.deposit_bank is not None: raise HTTPException(403, "You can only change the Taxable field.")
    if p.taxable not in (None, "Yes", "No", ""): raise HTTPException(400, "Taxable must be Yes, No or blank.")
    before = db.get_payment(pid)
    if not before or before["status"] != "submitted": raise HTTPException(404, "Payment not found in the ledger.")
    db.set_ledger(pid, taxable=p.taxable, deposit_bank=(p.deposit_bank.strip().upper() if p.deposit_bank is not None else None))
    db.audit(user["username"], "ledger_edit", pid, **{k: [before["fields"].get(k), v] for k, v in p.model_dump(exclude_none=True).items()})
    if before["imported"] and not before.get("excel", {}).get("row"):
        return dict(ok=True, excel="skipped", message="")
    left, msg = push_to_excel()
    return dict(ok=True, excel="pending" if left else "synced", message=msg)

def _sync_loop():
    import time
    while True:
        time.sleep(30)
        try:
            if db.dirty_rows(): push_to_excel()
        except Exception: traceback.print_exc()

threading.Thread(target=_sync_loop, daemon=True).start()

# ================================================================== learned data + import
@app.get("/api/learned")
def learned(_=Depends(require_admin)): return db.learned()

@app.put("/api/learned/{table}")
def learned_put(table: str, row: dict, key: str | None = None, user=Depends(require_admin)):
    if table not in db.TABLES: raise HTTPException(404)
    db.learned_upsert(table, row, key)
    db.audit(user["username"], "learned_" + table, key=key, row=row)
    return db.learned()

@app.delete("/api/learned/{table}")
def learned_del(table: str, key: str, user=Depends(require_admin)):
    if table not in db.TABLES: raise HTTPException(404)
    db.learned_delete(table, key)
    db.audit(user["username"], "learned_delete_" + table, key=key)
    return db.learned()

class ImportReq(BaseModel):
    what: str = "customers"          # customers | history
    sheets: list[str] = []
    since: str = ""

@app.post("/api/import")
def do_import(r: ImportReq, user=Depends(require_admin)):
    path = workbook_path()
    sh = r.sheets or sheets()
    try:
        if r.what == "customers":
            n = db.import_customers(importer.customers(path, sh))
        else:
            recs = [x for x in importer.history(path, sh) if not r.since or (x["received"] or "") >= r.since]
            n = db.import_history(recs, user["username"])
            db.import_customers(importer.customers(path, sh))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read the workbook: {e}")
    db.audit(user["username"], "import_" + r.what, count=n, sheets=sh)
    return dict(imported=n)

# ------------------------------------------------------------------ spreadsheet upload into the ledger
IMPORT_DIR = os.path.join(config.DATA, "imports")

def _import_file(token):
    if not token.isalnum(): raise HTTPException(404)
    for ext in (".xlsx", ".xlsm", ".csv"):
        p = os.path.join(IMPORT_DIR, token + ext)
        if os.path.exists(p): return p
    raise HTTPException(404, "That upload expired. Choose the file again.")

def _read_upload(path, filename, date_policy="fix", parsed=None):
    """Read (or reuse the preview's parsed copy), apply the date policy, then mark rows already in the ledger."""
    from .excel import ledger_import
    if parsed is None:
        try: res = ledger_import.read_file(path, filename, sheets(), db.registry())
        except ValueError as e: raise HTTPException(400, str(e))
    else:
        res = parsed
    res["flagged"] = [dict(source=r.get("source", ""), sheet=r["sheet"], row=r["row"], customer=r["customer"], amount=r["amount"], **r["date_issue"])
                      for r in res["records"] if r.get("date_issue")]
    res["records"], res["fixed"], res["dropped"] = ledger_import.apply_date_policy(res["records"], date_policy)
    ledger_import.mark_duplicates(res["records"], db.ledger_fingerprints())
    return res

@app.post("/api/import/excel")
async def import_excel_preview(file: UploadFile = File(...), user=Depends(require_admin)):
    """Step 1: read the spreadsheet and show what would be added. Nothing is written yet."""
    from .excel import ledger_import
    name = os.path.basename(file.filename or "upload.xlsx")
    ext = os.path.splitext(name.lower())[1]
    if ext not in (".xlsx", ".xlsm", ".csv"): raise HTTPException(400, "Choose an .xlsx, .xlsm or .csv file. (Old .xls files: open in Excel and Save As .xlsx.)")
    os.makedirs(IMPORT_DIR, exist_ok=True)
    for f in os.listdir(IMPORT_DIR):                 # uploads that were never committed
        fp = os.path.join(IMPORT_DIR, f)
        if os.path.getmtime(fp) < datetime.datetime.now().timestamp() - 86400: os.remove(fp)
    token = uuid.uuid4().hex
    path = os.path.join(IMPORT_DIR, token + ext)
    with open(path, "wb") as fh: fh.write(await file.read())
    with open(os.path.join(IMPORT_DIR, token + ".name"), "w", encoding="utf-8") as fh: fh.write(name)
    from .excel import ledger_import as li
    try: parsed = li.read_file(path, name, sheets(), db.registry())
    except ValueError as e:
        os.remove(path); raise HTTPException(400, str(e))
    with open(os.path.join(IMPORT_DIR, token + ".json"), "w", encoding="utf-8") as fh: json.dump(parsed, fh)
    res = _read_upload(path, name, parsed=json.loads(json.dumps(parsed)))
    recs = res["records"]
    new = [r for r in recs if not r["duplicate"]]
    return dict(token=token, filename=name, formats=res["sheets"], warnings=res["warnings"], skipped=res["skipped"],
                flagged_dates=res["flagged"], fixable=sum(1 for f in res["flagged"] if f["fix"]),
                rows=len(recs), new=len(new), duplicates=len(recs) - len(new), total_new=round(sum(float(r["amount"]) for r in new), 2),
                first=min(r["received"] for r in recs), last=max(r["received"] for r in recs),
                per_sheet=ledger_import.summary(recs), needs_sheet=any(not r["sheet"] for r in recs), known_sheets=sheets(),
                sample=[{k: r[k] for k in ("sheet", "received", "customer", "method", "payref", "ticket", "amount", "taxable", "duplicate", "source")}
                        for r in (new[:12] or recs[:12])])

class ImportCommit(BaseModel):
    default_sheet: str = ""
    date_policy: str = "fix"            # fix | skip | keep
    include_duplicates: bool = False
    sheets: list[str] = []
    also_customers: bool = True

@app.post("/api/import/excel/{token}")
def import_excel_commit(token: str, r: ImportCommit, user=Depends(require_admin)):
    """Step 2: add the previewed rows to the ledger as one batch (Undo removes the batch)."""
    path = _import_file(token)
    side = os.path.join(IMPORT_DIR, token + ".name")
    name = open(side, encoding="utf-8").read().strip() if os.path.exists(side) else os.path.basename(path)
    if r.date_policy not in ("fix", "skip", "keep"): raise HTTPException(400, "date_policy must be fix, skip or keep.")
    cache = os.path.join(IMPORT_DIR, token + ".json")
    parsed = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else None
    res = _read_upload(path, path, r.date_policy, parsed)
    recs = [x for x in res["records"] if r.include_duplicates or not x["duplicate"]]
    for x in recs:
        if not x["sheet"]: x["sheet"] = r.default_sheet.strip().upper()
    if any(not x["sheet"] for x in recs): raise HTTPException(400, "Some rows don't say which payee they belong to. Pick a payee for them.")
    if r.sheets: recs = [x for x in recs if x["sheet"] in r.sheets]
    batch = token[:16]
    filename = name
    n = db.import_upload(recs, user["username"], batch, filename)
    if r.also_customers and recs:
        names = {}
        for x in recs: names.setdefault(x["customer"], set()).add(x["sheet"])
        db.import_customers({k: sorted(v) for k, v in names.items() if len(k) >= 2})
    for f in (path, side, cache):
        try: os.remove(f)
        except OSError: pass
    db.audit(user["username"], "import_excel", count=n, batch=batch, file=filename)
    return dict(imported=n, batch=batch, skipped_duplicates=sum(1 for x in res["records"] if x["duplicate"]) if not r.include_duplicates else 0)

@app.get("/api/import/batches")
def import_batches(_=Depends(require_admin)): return db.import_batches()

@app.delete("/api/import/batches/{batch}")
def import_undo(batch: str, user=Depends(require_admin)):
    n = db.undo_import(batch)
    if not n: raise HTTPException(404, "Import not found.")
    db.audit(user["username"], "import_undone", count=n, batch=batch)
    return dict(removed=n, batches=db.import_batches())

# ================================================================== analytics
@app.get("/api/analytics")
def analytics_view(start: str = "", end: str = "", grain: str = "month", by: str = "sheet", sheet_list: str = Query("", alias="sheets"), customer: str = "",
                   methods: str = "", banks: str = "", horizon: int = 3, _=Depends(require_admin)):
    from . import analytics
    split = lambda v: [x for x in v.split(",") if x]
    try:
        return analytics.analytics(start or None, end or None, grain, by, split(sheet_list), customer, split(methods), split(banks), horizon,
                                   [b.strip().upper() for b in (db.get_setting("deposit_banks") or "").split(",") if b.strip()])
    except ValueError as e:
        raise HTTPException(400, f"Bad filter: {e}")

@app.get("/api/audit")
def audit_log(limit: int = 200, _=Depends(require_admin)):
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 2000),))]

@app.get("/api/meta")
def meta(_=Depends(require_user)):
    return dict(methods=config.METHODS, sheets=sheets(),
                deposit_banks=[b.strip() for b in (db.get_setting("deposit_banks") or "").split(",") if b.strip()],
                payees=[dict(name=n, sheet=s) for n, s, _ in db.registry().payees()],
                customers=db.registry().customers())

# ================================================================== UI
if os.path.isdir(os.path.join(config.STATIC, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(config.STATIC, "assets")), name="assets")

@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"): raise HTTPException(404)
    f = os.path.join(config.STATIC, path)
    if path and os.path.isfile(f): return FileResponse(f)
    idx = os.path.join(config.STATIC, "index.html")
    if os.path.exists(idx): return FileResponse(idx)
    return JSONResponse({"error": "UI not built. Run: cd frontend && npm install && npm run build"}, status_code=500)
