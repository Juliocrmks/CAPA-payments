import sqlite3, json, os, hashlib, datetime, threading
from extract import norm

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(os.path.join(DATA, "images"), exist_ok=True)
DB_PATH = os.path.join(DATA, "checkflow.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY AUTOINCREMENT, image TEXT, fields TEXT, warns TEXT,
  status TEXT DEFAULT 'review', dedupe TEXT, created_at TEXT, submitted_at TEXT);
CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY AUTOINCREMENT, check_id INTEGER, workbook TEXT, sheet TEXT, row INTEGER, written_at TEXT);
CREATE TABLE IF NOT EXISTS payer_map(routing TEXT, account TEXT, name TEXT, PRIMARY KEY(routing, account));
CREATE TABLE IF NOT EXISTS payee_map(norm TEXT PRIMARY KEY, name TEXT, sheet TEXT);
CREATE TABLE IF NOT EXISTS bank_map(routing TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE, salt TEXT, hash TEXT, role TEXT, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
"""

def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        for col in ("dirty INTEGER DEFAULT 0", "note TEXT"):
            try: c.execute("ALTER TABLE submissions ADD COLUMN " + col)
            except sqlite3.OperationalError: pass
        # Seeds (editable by simply correcting cards during review; they are learned from then on)
        c.execute("INSERT OR IGNORE INTO payee_map VALUES(?,?,?)", (norm("Rio Valley Pipe LLC"), "Rio Valley Pipe LLC", "RVP"))
        c.execute("INSERT OR IGNORE INTO bank_map VALUES('114915447','Rio Bank')")
        c.execute("INSERT OR IGNORE INTO bank_map VALUES('114917623','IBC Bank')")

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

# ---- settings
def get_setting(k, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r["value"] if r else default
def set_setting(k, v):
    with _lock, conn() as c: c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))

# ---- registry used by the extractor
class Registry:
    def bank(self, routing):
        with conn() as c: r = c.execute("SELECT name FROM bank_map WHERE routing=?", (routing,)).fetchone()
        return r["name"] if r else None
    def payees(self):
        with conn() as c: return [(r["name"], r["sheet"]) for r in c.execute("SELECT name,sheet FROM payee_map")]
    def payer(self, routing, account):
        with conn() as c: r = c.execute("SELECT name FROM payer_map WHERE routing=? AND account=?", (routing, account)).fetchone()
        return r["name"] if r else None
    def learn(self, f):
        with _lock, conn() as c:
            if f.get("routing") and f.get("account") and f.get("payer"):
                c.execute("INSERT OR REPLACE INTO payer_map VALUES(?,?,?)", (f["routing"], f["account"], f["payer"]))
            if f.get("payee") and f.get("sheet"):
                c.execute("INSERT OR REPLACE INTO payee_map VALUES(?,?,?)", (norm(f["payee"]), f["payee"], f["sheet"]))
            if f.get("routing") and f.get("bank"):
                c.execute("INSERT OR REPLACE INTO bank_map VALUES(?,?)", (f["routing"], f["bank"]))

# ---- checks
def dedupe_key(f):
    return hashlib.sha1("|".join(str(f.get(k, "")) for k in ("routing", "account", "check", "amount")).encode()).hexdigest()

def row_to_check(r):
    f = json.loads(r["fields"]); f.setdefault("received", ""); f.setdefault("deposit_bank", "")
    return dict(id=r["id"], status=r["status"], fields=f, warns=json.loads(r["warns"]),
                image=f"/api/image/{r['id']}", created_at=r["created_at"], submitted_at=r["submitted_at"])

def dup_warning(c, cid, f):
    if not (f.get("routing") and f.get("check")): return None
    k = dedupe_key(f)
    r = c.execute("SELECT id,status,submitted_at FROM checks WHERE dedupe=? AND id!=? ORDER BY id LIMIT 1", (k, cid)).fetchone()
    if not r: return None
    if r["status"] == "submitted": return f"This check was already sent to Excel on {r['submitted_at'][:10]}."
    return "The same check is also loaded elsewhere in the app."

def add_check(image_name, fields, warns):
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO checks(image,fields,warns,status,dedupe,created_at) VALUES(?,?,?,?,?,?)",
                        (image_name, json.dumps(fields), json.dumps(warns), "review", dedupe_key(fields), now()))
        cid = cur.lastrowid
        d = dup_warning(c, cid, fields)
        if d: warns["check"] = d; c.execute("UPDATE checks SET warns=? WHERE id=?", (json.dumps(warns), cid))
        return row_to_check(c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone())

def get_check(cid):
    with conn() as c:
        r = c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
    return row_to_check(r) if r else None

def list_checks(statuses):
    q = ",".join("?" * len(statuses))
    with conn() as c:
        return [row_to_check(r) for r in c.execute(f"SELECT * FROM checks WHERE status IN ({q}) ORDER BY id", statuses)]

def image_file(cid):
    with conn() as c: r = c.execute("SELECT image FROM checks WHERE id=?", (cid,)).fetchone()
    return os.path.join(DATA, "images", r["image"]) if r else None

def update_check(cid, fields=None, status=None, warns=None):
    from extract import aba_ok
    with _lock, conn() as c:
        r = c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
        if not r: return None
        f, w = json.loads(r["fields"]), json.loads(r["warns"])
        f.setdefault("received", ""); f.setdefault("deposit_bank", "")
        for k, v in (fields or {}).items():
            if k in f: f[k] = v; w.pop(k, None)
        if fields and "routing" in fields:
            if f["routing"] and not aba_ok(f["routing"]): w["routing"] = "Fails the ABA checksum. One digit is probably misread."
            b = Registry().bank(f["routing"]) if f["routing"] else None
            if b and "bank" not in fields: f["bank"] = b; w.pop("bank", None)
        if fields and "payee" in fields and "sheet" not in fields:
            for n, s in Registry().payees():
                if norm(n) == norm(f["payee"]): f["sheet"] = s; w.pop("sheet", None)
        if fields and any(k in fields for k in ("routing", "account", "check", "amount")):
            d = dup_warning(c, cid, f)
            if d: w["check"] = d
        c.execute("UPDATE checks SET fields=?, warns=?, status=?, dedupe=? WHERE id=?",
                  (json.dumps(f), json.dumps(w), status or r["status"], dedupe_key(f), cid))
        return row_to_check(c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone())

def delete_check(cid):
    with _lock, conn() as c:
        r = c.execute("SELECT image,status FROM checks WHERE id=?", (cid,)).fetchone()
        if r and r["status"] != "submitted":
            c.execute("DELETE FROM checks WHERE id=?", (cid,))
            try: os.remove(os.path.join(DATA, "images", r["image"]))
            except OSError: pass

def mark_submitted(cid, workbook, sheet, row):
    with _lock, conn() as c:
        c.execute("UPDATE checks SET status='submitted', submitted_at=? WHERE id=?", (now(), cid))
        c.execute("INSERT INTO submissions(check_id,workbook,sheet,row,written_at) VALUES(?,?,?,?,?)", (cid, workbook, sheet, row, now()))

def ledger_rows(sheet=None):
    q = "SELECT c.id,c.fields,c.submitted_at,s.sheet,s.row,s.dirty,s.note FROM checks c JOIN submissions s ON s.check_id=c.id"
    with conn() as c: rows = c.execute(q + (" WHERE s.sheet=?" if sheet else "") + " ORDER BY s.id", [sheet] if sheet else []).fetchall()
    out = []
    for r in rows:
        f = json.loads(r["fields"]); f.setdefault("received", ""); f.setdefault("deposit_bank", "")
        out.append(dict(id=r["id"], fields=f, image=f"/api/image/{r['id']}", submitted_at=r["submitted_at"], sheet=r["sheet"],
                        row=r["row"], pending=bool(r["dirty"]), note=r["note"] or ""))
    return out

def set_ledger(cid, taxable=None, deposit_bank=None):
    with _lock, conn() as c:
        r = c.execute("SELECT fields FROM checks WHERE id=? AND status='submitted'", (cid,)).fetchone()
        if not r: return False
        f = json.loads(r["fields"])
        if taxable is not None: f["taxable"] = taxable
        if deposit_bank is not None: f["deposit_bank"] = deposit_bank.strip()
        c.execute("UPDATE checks SET fields=? WHERE id=?", (json.dumps(f), cid))
        c.execute("UPDATE submissions SET dirty=1, note='' WHERE check_id=?", (cid,))
        return True

def dirty_rows():
    with conn() as c:
        rows = c.execute("SELECT c.id,c.fields,s.sheet,s.row FROM checks c JOIN submissions s ON s.check_id=c.id WHERE s.dirty=1").fetchall()
    return [dict(id=r["id"], fields=json.loads(r["fields"]), sheet=r["sheet"], row=r["row"]) for r in rows]

def sync_result(cid, row=None, note=""):
    with _lock, conn() as c:
        if note: c.execute("UPDATE submissions SET note=? WHERE check_id=?", (note, cid))
        else: c.execute("UPDATE submissions SET dirty=0, note='', row=COALESCE(?,row) WHERE check_id=?", (row, cid))

def deposit_banks():
    with conn() as c: rows = c.execute("SELECT fields FROM checks").fetchall()
    return sorted({json.loads(r["fields"]).get("deposit_bank", "").strip() for r in rows} - {""}, key=str.lower)
