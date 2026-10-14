import os, sys, threading, webbrowser, time, datetime, socket
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import uuid
import db, extract, excel_writer, auth
from auth import require_user, require_admin

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="CheckFlow")
db.init()
REG = db.Registry()
DEFAULT_IGNORE = "FORMAT, DEPOSIT TAXES"
WB_LOCK = threading.Lock()

def workbook_path():
    p = db.get_setting("workbook")
    if not p:                                    # first run: create a practice workbook so everything can be tested safely
        p = os.path.join(db.DATA, "Practice_Workbook.xlsx")
        if not os.path.exists(p): excel_writer.make_sample(p)
        db.set_setting("workbook", p)
    return p

def ignore_list(): return [s.strip() for s in db.get_setting("ignore", DEFAULT_IGNORE).split(",") if s.strip()]

@app.get("/")
def index(): return FileResponse(os.path.join(BASE, "static", "index.html"))

@app.get("/api/settings")
def settings(_=Depends(require_admin)):
    p = workbook_path()
    try: sheets = excel_writer.list_sheets(p, ignore_list())
    except Exception as e: sheets = []
    return dict(workbook=p, exists=os.path.exists(p), ignore=db.get_setting("ignore", DEFAULT_IGNORE), sheets=sheets)

class Settings(BaseModel):
    workbook: str | None = None
    ignore: str | None = None
    practice: bool = False

@app.post("/api/settings")
def save_settings(s: Settings, _=Depends(require_admin)):
    if s.practice:
        p = os.path.join(db.DATA, "Practice_Workbook.xlsx"); excel_writer.make_sample(p); db.set_setting("workbook", p)
    elif s.workbook is not None:
        p = s.workbook.strip().strip('"')
        if not os.path.exists(p): raise HTTPException(400, "That file doesn't exist. Check the path.")
        if not p.lower().endswith((".xlsx", ".xlsm")): raise HTTPException(400, "Choose an .xlsx or .xlsm workbook.")
        db.set_setting("workbook", p)
    if s.ignore is not None: db.set_setting("ignore", s.ignore)
    return settings()

@app.post("/api/extract")
async def extract_one(file: UploadFile = File(...), _=Depends(require_admin)):
    data = await file.read()
    try:
        F, W, img = await run_in_threadpool(extract.extract, data, REG)
    except Exception as e:
        raise HTTPException(422, f"Could not read this image: {e}")
    name = uuid.uuid4().hex + ".jpg"
    with open(os.path.join(db.DATA, "images", name), "wb") as fh: fh.write(extract.jpeg(img))
    F["received"] = datetime.date.today().isoformat(); F["deposit_bank"] = ""
    return db.add_check(name, F, W)

@app.get("/api/checks")
def checks(status: str = "review,validated", _=Depends(require_admin)):
    return db.list_checks(status.split(","))

class Patch(BaseModel):
    fields: dict | None = None
    status: str | None = None

@app.patch("/api/checks/{cid}")
def patch(cid: int, p: Patch, _=Depends(require_admin)):
    if p.status and p.status not in ("review", "validated", "pending"): raise HTTPException(400, "Bad status")
    c = db.update_check(cid, p.fields, p.status)
    if not c: raise HTTPException(404)
    return c

@app.delete("/api/checks/{cid}")
def delete(cid: int, _=Depends(require_admin)): db.delete_check(cid); return {"ok": True}

@app.get("/api/image/{cid}")
def image(cid: int, _=Depends(require_user)):
    p = db.image_file(cid)
    if not p or not os.path.exists(p): raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")

class Submit(BaseModel):
    ids: list[int]

@app.post("/api/submit")
def submit(s: Submit, _=Depends(require_admin)):
    """Write validated checks to Excel. Remaining checks from the review session become pending."""
    items, skipped, rows = [], [], db.list_checks(["review", "validated"])
    ids = set(s.ids)
    for c in rows:
        if c["id"] not in ids: continue
        f = c["fields"]
        if c["status"] != "validated": continue
        if not f["sheet"] or not f["amount"] or not f["payer"] or not (f.get("received") or f["date"]):
            skipped.append(dict(id=c["id"], reason="Missing payer, sheet, amount or received date.")); continue
        dup = db.dedupe_key(f)
        with db.conn() as con:
            d = con.execute("SELECT 1 FROM checks WHERE dedupe=? AND status='submitted' AND id!=?", (dup, c["id"])).fetchone()
        if d: skipped.append(dict(id=c["id"], reason="Already sent to Excel before.")); continue
        items.append(dict(id=c["id"], sheet=f["sheet"], date=f["date"] or "01/01/00", received=f.get("received", ""), payer=f["payer"],
                          ticket=f["ticket"], check=f["check"], taxable=f["taxable"], amount=f["amount"], deposit_bank=f.get("deposit_bank", "")))
    written = {}
    if items:
        try:
            with WB_LOCK: written = excel_writer.write_checks(workbook_path(), items)
        except excel_writer.WorkbookError as e:
            raise HTTPException(409, str(e))
        for it in items:
            db.mark_submitted(it["id"], workbook_path(), *written[it["id"]])
            REG.learn(next(c for c in rows if c["id"] == it["id"])["fields"])
    for c in db.list_checks(["review", "validated"]):          # everything not sent goes to the pending list
        db.update_check(c["id"], status="pending")
    per = {}
    for sheet, _ in written.values(): per[sheet] = per.get(sheet, 0) + 1
    return dict(written=len(written), sheets=per, skipped=skipped)

# ---------------- ledger ----------------
@app.get("/api/ledger/sheets")
def ledger_sheets(_=Depends(require_user)):
    try: return excel_writer.list_sheets(workbook_path(), ignore_list())
    except Exception: return []

@app.get("/api/ledger")
def ledger(sheet: str = "", _=Depends(require_user)): return db.ledger_rows(sheet or None)

@app.get("/api/deposit_banks")
def deposit_banks(_=Depends(require_user)): return db.deposit_banks()

class LedgerPatch(BaseModel):
    taxable: str | None = None
    deposit_bank: str | None = None

def push_to_excel():
    """Write any edited ledger rows to Excel. Returns (pending_count, message)."""
    rows = db.dirty_rows()
    if not rows: return 0, ""
    ups = [dict(id=r["id"], sheet=r["sheet"], row=r["row"], payer=r["fields"]["payer"], check=r["fields"]["check"],
                taxable=r["fields"]["taxable"], deposit_bank=r["fields"].get("deposit_bank", "")) for r in rows]
    try:
        with WB_LOCK: res = excel_writer.update_rows(workbook_path(), ups)
    except excel_writer.WorkbookError as e:
        return len(rows), "The workbook is open in Excel. Your change is saved and will be written automatically once it is closed." if "open in Excel" in str(e) else str(e)
    left, msg = 0, ""
    for cid, (st, v) in res.items():
        if st == "ok": db.sync_result(cid, row=v)
        else: db.sync_result(cid, note=v); left += 1; msg = v
    return left, msg

@app.patch("/api/ledger/{cid}")
def ledger_patch(cid: int, p: LedgerPatch, user=Depends(require_user)):
    if user["role"] != "admin" and p.deposit_bank is not None: raise HTTPException(403, "You can only change the Taxable field.")
    if p.taxable not in (None, "Yes", "No"): raise HTTPException(400, "Taxable must be Yes or No.")
    if not db.set_ledger(cid, p.taxable, p.deposit_bank): raise HTTPException(404, "Check not found in the ledger.")
    left, msg = push_to_excel()
    return dict(ok=True, excel="pending" if left else "synced", message=msg)

def sync_loop():
    while True:
        time.sleep(30)
        try:
            if db.dirty_rows(): push_to_excel()
        except Exception: pass

# ---------------- auth + users ----------------
class Cred(BaseModel):
    username: str
    password: str

@app.get("/api/me")
def me(request: Request):
    u = auth.current_user(request)
    return dict(user=u, setup=auth.user_count() == 0)

@app.post("/api/setup")
def setup(c: Cred, request: Request):
    if auth.user_count() > 0: raise HTTPException(400, "Setup is already done.")
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "The first admin account must be created on the computer running CheckFlow.")
    auth.create_user(c.username, c.password, "admin")
    return {"ok": True}

@app.post("/api/login")
def login(c: Cred, request: Request, response: Response):
    tok = auth.login(c.username, c.password, request.client.host if request.client else "")
    response.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax", max_age=auth.TTL)
    return {"ok": True}

@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE, "")); response.delete_cookie(auth.COOKIE); return {"ok": True}

@app.get("/api/users")
def users(_=Depends(require_admin)):
    with db.conn() as c: return [dict(r) for r in c.execute("SELECT id,username,role,active FROM users ORDER BY id")]

class NewUser(BaseModel):
    username: str
    password: str
    role: str = "ar"

@app.post("/api/users")
def add_user(u: NewUser, _=Depends(require_admin)): auth.create_user(u.username, u.password, u.role); return users()

class UserPatch(BaseModel):
    password: str | None = None
    active: bool | None = None

@app.patch("/api/users/{uid}")
def edit_user(uid: int, p: UserPatch, me_=Depends(require_admin)):
    if p.password: auth.set_password(uid, p.password)
    if p.active is not None:
        if uid == me_["id"] and not p.active: raise HTTPException(400, "You can't deactivate your own account.")
        with db._lock, db.conn() as c:
            c.execute("UPDATE users SET active=? WHERE id=?", (1 if p.active else 0, uid))
            if not p.active: c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    return users()

def lan_ip():
    try:
        k = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); k.connect(("8.8.8.8", 80)); ip = k.getsockname()[0]; k.close(); return ip
    except Exception: return None

def main():
    port = int(os.environ.get("PORT", 8765))
    local_only = bool(os.environ.get("CHECKFLOW_LOCAL"))
    import uvicorn
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    extract.engine()                                            # warm the OCR models
    threading.Thread(target=sync_loop, daemon=True).start()
    ip = lan_ip()
    print(f"CheckFlow is running.\n  On this computer: http://127.0.0.1:{port}" + ("" if local_only or not ip else f"\n  Other computers on your network: http://{ip}:{port}"))
    uvicorn.run(app, host="127.0.0.1" if local_only else "0.0.0.0", port=port, log_level="warning")

if __name__ == "__main__": main()
