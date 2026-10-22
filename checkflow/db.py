"""SQLite storage: users, documents/pages, payments, ledger submissions, learned data, audit log."""
import sqlite3, json, os, re, hashlib, datetime, threading
from .config import DB_PATH, SEED_PAYEES, SEED_BANKS, DEFAULT_SETTINGS
from .registry import StaticRegistry, nkey

SCHEMA_VERSION = 2
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE, salt TEXT, hash TEXT,
  role TEXT, source TEXT DEFAULT 'local', display_name TEXT, active INTEGER DEFAULT 1, must_change INTEGER DEFAULT 0,
  created_at TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, received TEXT, pages INTEGER DEFAULT 0,
  status TEXT DEFAULT 'queued', progress REAL DEFAULT 0, error TEXT, uploaded_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER, idx INTEGER, kind TEXT, image TEXT,
  sensitive INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER, status TEXT DEFAULT 'review',
  fields TEXT, warns TEXT, sources TEXT, dedupe TEXT, imported INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT,
  submitted_at TEXT, submitted_by TEXT);
CREATE INDEX IF NOT EXISTS payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS payments_dedupe ON payments(dedupe);
CREATE TABLE IF NOT EXISTS payment_pages(payment_id INTEGER, page_id INTEGER, ord INTEGER, PRIMARY KEY(payment_id, page_id));
CREATE TABLE IF NOT EXISTS submissions(payment_id INTEGER PRIMARY KEY, workbook TEXT, sheet TEXT, row INTEGER,
  dirty INTEGER DEFAULT 0, note TEXT, written_at TEXT);
CREATE TABLE IF NOT EXISTS payees(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE COLLATE NOCASE, sheet TEXT, aliases TEXT);
CREATE TABLE IF NOT EXISTS customers(name TEXT PRIMARY KEY, sheets TEXT, source TEXT, taxable_default TEXT DEFAULT '',
  deposit_bank_default TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS accounts(routing TEXT, account TEXT, customer TEXT, updated_at TEXT, PRIMARY KEY(routing, account));
CREATE TABLE IF NOT EXISTS banks(routing TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS memos(pattern TEXT PRIMARY KEY, customer TEXT);
CREATE TABLE IF NOT EXISTS reset_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT, user_id INTEGER, created_at TEXT,
  status TEXT DEFAULT 'open', handled_by TEXT, handled_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, action TEXT, payment_id INTEGER, detail TEXT);
"""

def now(): return datetime.datetime.now().isoformat(timespec="seconds")

def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, conn() as c:
        legacy = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checks'").fetchone()
        c.executescript(SCHEMA)
        for table, col in (("users", "source TEXT DEFAULT 'local'"), ("users", "display_name TEXT"), ("users", "must_change INTEGER DEFAULT 0"),
                           ("users", "last_login TEXT"), ("documents", "found INTEGER DEFAULT 0"), ("submissions", "excel_fields TEXT"),
                           ("users", "email TEXT DEFAULT ''"), ("payments", "deleted_at TEXT"), ("payments", "deleted_by TEXT"),
                           ("payments", "delete_reason TEXT"), ("submissions", "pending_op TEXT DEFAULT ''")):
            try: c.execute(f"ALTER TABLE {table} ADD COLUMN " + col)
            except sqlite3.OperationalError: pass
        if legacy: _migrate_v1(c)
        c.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        for k, v in DEFAULT_SETTINGS.items(): c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
        if not c.execute("SELECT 1 FROM payees").fetchone():
            for name, sheet, aliases in SEED_PAYEES:
                c.execute("INSERT OR IGNORE INTO payees(name, sheet, aliases) VALUES(?,?,?)", (name, sheet, ", ".join(aliases)))
        for r, n in SEED_BANKS.items(): c.execute("INSERT OR IGNORE INTO banks VALUES(?,?)", (r, n))

def _migrate_v1(c):
    """v1 (single 'checks' table) -> v2 payments. Runs once; the old table is renamed, not deleted."""
    for r in c.execute("SELECT * FROM checks").fetchall():
        f = json.loads(r["fields"] or "{}")
        d = f.get("date", "")
        doc_date = f"20{d[6:8]}-{d[0:2]}-{d[3:5]}" if len(d) == 8 else ""
        nf = dict(method="check", customer=f.get("payer", ""), payee=f.get("payee", ""), sheet=f.get("sheet", ""),
                  received=f.get("received") or doc_date, doc_date=doc_date, amount=f.get("amount", ""), ticket=f.get("ticket", ""),
                  payref=f.get("check", ""), check_no=f.get("check", ""), routing=f.get("routing", ""), account=f.get("account", ""),
                  bank=f.get("bank", ""), taxable=f.get("taxable", ""), deposit_bank=f.get("deposit_bank", ""))
        c.execute("INSERT INTO payments(status, fields, warns, sources, dedupe, created_at, updated_at, submitted_at) VALUES(?,?,?,?,?,?,?,?)",
                  (r["status"], json.dumps(nf), r["warns"] or "{}", json.dumps(["check"]), dedupe_key(nf), r["created_at"], now(), r["submitted_at"]))
    c.execute("ALTER TABLE checks RENAME TO legacy_checks_v1")
    try: c.execute("ALTER TABLE submissions RENAME TO legacy_submissions_v1"); c.executescript(SCHEMA)
    except sqlite3.OperationalError: pass

# ------------------------------------------------------------------ settings
def get_setting(k, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r["value"] if r else (default if default is not None else DEFAULT_SETTINGS.get(k))

def set_setting(k, v):
    with _lock, conn() as c: c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, "" if v is None else str(v)))

def settings():
    with conn() as c: return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}

def audit(user, action, payment_id=None, **detail):
    with _lock, conn() as c:
        c.execute("INSERT INTO audit(ts, username, action, payment_id, detail) VALUES(?,?,?,?,?)",
                  (now(), user or "", action, payment_id, json.dumps(detail, default=str)))

# ------------------------------------------------------------------ learned data
class DbRegistry(StaticRegistry):
    def __init__(self):
        super().__init__()
    def payees(self):
        with conn() as c:
            return [(r["name"], r["sheet"], [a.strip() for a in (r["aliases"] or "").split(",") if a.strip()])
                    for r in c.execute("SELECT * FROM payees ORDER BY id")]
    def banks(self):
        with conn() as c: return {r["routing"]: r["name"] for r in c.execute("SELECT * FROM banks")}
    def customers(self):
        with conn() as c: return [r["name"] for r in c.execute("SELECT name FROM customers")]
    def _accounts_get(self, routing, account):
        with conn() as c:
            r = c.execute("SELECT customer FROM accounts WHERE routing=? AND account=?", (routing, account)).fetchone()
        return r["customer"] if r else None
    def customer_for_memo(self, memo):
        k = nkey(memo)
        with conn() as c:
            for r in c.execute("SELECT * FROM memos"):
                if r["pattern"] and nkey(r["pattern"]) in k: return r["customer"]
        return None
    def defaults_for(self, customer, method):
        d = {"deposit_bank": get_setting("deposit_bank_" + (method or "check"), "")}
        with conn() as c:
            r = c.execute("SELECT taxable_default, deposit_bank_default FROM customers WHERE name=?", ((customer or "").upper(),)).fetchone()
        if r:
            if r["taxable_default"]: d["taxable"] = r["taxable_default"]
            if r["deposit_bank_default"]: d["deposit_bank"] = r["deposit_bank_default"]
        return d

    def learn(self, f, sheet=None):
        """Remember what a person confirmed: account -> customer, bank names, the customer itself, memo -> customer."""
        cust = (f.get("customer") or "").strip().upper()
        with _lock, conn() as c:
            if cust:
                row = c.execute("SELECT sheets FROM customers WHERE name=?", (cust,)).fetchone()
                sheets = set((row["sheets"] or "").split(",")) if row else set()
                if f.get("sheet"): sheets.add(f["sheet"])
                c.execute("""INSERT INTO customers(name, sheets, source, updated_at) VALUES(?,?,?,?)
                             ON CONFLICT(name) DO UPDATE SET sheets=excluded.sheets, updated_at=excluded.updated_at""",
                          (cust, ",".join(sorted(s for s in sheets if s)), "learned", now()))
            if f.get("routing") and f.get("account") and cust:
                c.execute("INSERT OR REPLACE INTO accounts VALUES(?,?,?,?)", (f["routing"], f["account"], cust, now()))
            if f.get("routing") and f.get("bank"):
                c.execute("INSERT OR REPLACE INTO banks VALUES(?,?)", (f["routing"], f["bank"]))
            if f.get("method") == "wire" and f.get("memo") and cust:
                pat = " ".join(w for w in f["memo"].split() if not any(ch.isdigit() for ch in w))[:60].strip()
                if len(pat) >= 6: c.execute("INSERT OR REPLACE INTO memos VALUES(?,?)", (pat, cust))

REG = None
def registry():
    global REG
    if REG is None: REG = DbRegistry()
    return REG

# ------------------------------------------------------------------ payments
KEYS = ["method", "customer", "payee", "sheet", "received", "doc_date", "amount", "ticket", "order", "payref", "check_no",
        "routing", "account", "bank", "card_brand", "last4", "confirmation", "invoice", "taxable", "deposit_bank", "memo", "customer_raw"]

def blank_fields():
    return {k: "" for k in KEYS} | {"method": "check"}

def dedupe_key(f):
    m = f.get("method", "check")
    if m == "check": parts = (f.get("routing"), f.get("account"), f.get("check_no") or f.get("payref"), f.get("amount"))
    elif m in ("card", "ach"): parts = (f.get("confirmation") or f.get("last4"), f.get("amount"), f.get("doc_date") or f.get("received"))
    elif m == "wire": parts = (f.get("customer"), f.get("amount"), f.get("received"))
    else: parts = (f.get("ticket") or f.get("customer"), f.get("amount"), f.get("received"))
    if not all(parts): return ""
    return hashlib.sha1(("|".join([m] + [str(p) for p in parts])).encode()).hexdigest()

def _row(r, c=None):
    f = blank_fields() | json.loads(r["fields"] or "{}")
    out = dict(id=r["id"], document_id=r["document_id"], status=r["status"], fields=f, warns=json.loads(r["warns"] or "{}"),
               sources=json.loads(r["sources"] or "[]"), imported=bool(r["imported"]), created_at=r["created_at"],
               submitted_at=r["submitted_at"], submitted_by=r["submitted_by"])
    c = c or conn()
    out["pages"] = [dict(id=p["id"], kind=p["kind"], sensitive=bool(p["sensitive"]), image=f"/api/pages/{p['id']}")
                    for p in c.execute("""SELECT p.* FROM payment_pages pp JOIN pages p ON p.id=pp.page_id
                                          WHERE pp.payment_id=? ORDER BY pp.ord, p.idx""", (r["id"],))]
    s = c.execute("SELECT * FROM submissions WHERE payment_id=?", (r["id"],)).fetchone()
    out["excel"] = dict(sheet=s["sheet"], row=s["row"], pending=bool(s["dirty"]), note=s["note"] or "") if s else None
    return out

def dup_warning(c, pid, f):
    k = dedupe_key(f)
    if not k: return None
    r = c.execute("SELECT id, status, submitted_at FROM payments WHERE dedupe=? AND id!=? ORDER BY id LIMIT 1", (k, pid)).fetchone()
    if not r: return None
    if r["status"] == "submitted": return f"Already sent to Excel on {(r['submitted_at'] or '')[:10]} (payment #{r['id']})."
    return f"Same payment is also loaded as #{r['id']}."

def add_document(filename, received, user):
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO documents(filename, received, status, uploaded_by, created_at) VALUES(?,?,?,?,?)",
                        (filename, received or "", "queued", user, now()))
        return cur.lastrowid

def update_document(doc_id, **kw):
    if not kw: return
    with _lock, conn() as c:
        c.execute(f"UPDATE documents SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), doc_id))

def get_document(doc_id):
    with conn() as c:
        r = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(r) if r else None

def add_page(doc_id, idx, kind, image, sensitive):
    with _lock, conn() as c:
        return c.execute("INSERT INTO pages(document_id, idx, kind, image, sensitive) VALUES(?,?,?,?,?)",
                         (doc_id, idx, kind, image, int(sensitive))).lastrowid

def page_file(page_id):
    with conn() as c:
        r = c.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    return dict(r) if r else None

def add_payment(doc_id, fields, warns, sources, page_ids, status="review", imported=False):
    f = blank_fields() | {k: ("" if v is None else str(v)) for k, v in fields.items() if k in KEYS}
    with _lock, conn() as c:
        cur = c.execute("""INSERT INTO payments(document_id, status, fields, warns, sources, dedupe, imported, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (doc_id, status, json.dumps(f), json.dumps(warns or {}), json.dumps(sources or []), dedupe_key(f), int(imported), now(), now()))
        pid = cur.lastrowid
        for n, pg in enumerate(page_ids): c.execute("INSERT OR IGNORE INTO payment_pages VALUES(?,?,?)", (pid, pg, n))
        if not imported:
            d = dup_warning(c, pid, f)
            if d:
                w = dict(warns or {}); w["duplicate"] = d
                c.execute("UPDATE payments SET warns=? WHERE id=?", (json.dumps(w), pid))
        return pid

def get_payment(pid):
    with conn() as c:
        r = c.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        return _row(r, c) if r else None

def list_payments(statuses):
    q = ",".join("?" * len(statuses))
    with conn() as c:
        return [_row(r, c) for r in c.execute(f"SELECT * FROM payments WHERE status IN ({q}) ORDER BY id", statuses)]

def update_payment(pid, fields=None, status=None):
    from .extract.common import aba_ok
    with _lock, conn() as c:
        r = c.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if not r: return None
        if r["status"] == "submitted" and (fields or status): raise ValueError("Already sent to Excel. Edit it from the ledger.")
        f = blank_fields() | json.loads(r["fields"]); w = json.loads(r["warns"] or "{}")
        for k, v in (fields or {}).items():
            if k in KEYS:
                f[k] = "" if v is None else str(v).strip()
                w.pop(k, None)
        if fields:
            if "routing" in fields and f["routing"] and not aba_ok(f["routing"]):
                w["routing"] = "Fails the ABA checksum. One digit is probably misread."
            if "routing" in fields and f["routing"] and "bank" not in fields:
                b = registry().bank(f["routing"])
                if b: f["bank"] = b
            if "payee" in fields and "sheet" not in fields:
                m = registry().match_payee(f["payee"])
                if m: f["sheet"] = m[1]
            if "check_no" in fields and f["method"] == "check" and "payref" not in fields: f["payref"] = f["check_no"]
            if "amount" in fields:
                try: f["amount"] = f"{float(f['amount'].replace(',', '').replace('$', '')):.2f}"
                except ValueError: w["amount"] = "Not a number."
            w.pop("duplicate", None)
            d = dup_warning(c, pid, f)
            if d: w["duplicate"] = d
        c.execute("UPDATE payments SET fields=?, warns=?, status=?, dedupe=?, updated_at=? WHERE id=?",
                  (json.dumps(f), json.dumps(w), status or r["status"], dedupe_key(f), now(), pid))
        return _row(c.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone(), c)

def delete_payment(pid):
    with _lock, conn() as c:
        r = c.execute("SELECT status FROM payments WHERE id=?", (pid,)).fetchone()
        if not r: return False
        if r["status"] == "submitted": raise ValueError("Already sent to Excel; it can't be deleted here.")
        c.execute("DELETE FROM payment_pages WHERE payment_id=?", (pid,))
        c.execute("DELETE FROM payments WHERE id=?", (pid,))
        return True

def move_page(page_id, from_pid, to_pid=None):
    """Detach a page into its own new payment (to_pid None) or move it onto another payment."""
    with _lock, conn() as c:
        c.execute("DELETE FROM payment_pages WHERE payment_id=? AND page_id=?", (from_pid, page_id))
        if to_pid is None:
            src = c.execute("SELECT * FROM payments WHERE id=?", (from_pid,)).fetchone()
            f = json.loads(src["fields"])
            nf = blank_fields() | {k: f.get(k, "") for k in ("sheet", "payee", "received")}
            to_pid = c.execute("""INSERT INTO payments(document_id, status, fields, warns, sources, dedupe, created_at, updated_at)
                                  VALUES(?,?,?,?,?,?,?,?)""", (src["document_id"], "review", json.dumps(nf),
                               json.dumps({"amount": "Split from another payment. Fill in the details."}), "[]", "", now(), now())).lastrowid
        c.execute("INSERT OR IGNORE INTO payment_pages VALUES(?,?,?)", (to_pid, page_id, 99))
        return to_pid

# ------------------------------------------------------------------ ledger / submissions
def mark_submitted(pid, workbook, sheet, row, user):
    with _lock, conn() as c:
        c.execute("UPDATE payments SET status='submitted', submitted_at=?, submitted_by=? WHERE id=?", (now(), user, pid))
        f = c.execute("SELECT fields FROM payments WHERE id=?", (pid,)).fetchone()["fields"]
        c.execute("""INSERT OR REPLACE INTO submissions(payment_id, workbook, sheet, row, dirty, note, written_at, excel_fields)
                     VALUES(?,?,?,?,0,'',?,?)""", (pid, workbook, sheet, row, now(), f))

def set_rows(updates):
    with _lock, conn() as c:
        for pid, row in updates.items(): c.execute("UPDATE submissions SET row=? WHERE payment_id=?", (row, pid))

def ledger_rows():
    with conn() as c:
        rows = c.execute("""SELECT p.*, s.sheet AS s_sheet, s.row AS s_row, s.dirty AS s_dirty, s.note AS s_note
                            FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                            WHERE p.status='submitted' ORDER BY p.id""").fetchall()
        pages = {}
        for pp in c.execute("""SELECT pp.payment_id, p.id, p.kind, p.sensitive FROM payment_pages pp JOIN pages p ON p.id=pp.page_id
                               ORDER BY pp.ord, p.idx"""):
            pages.setdefault(pp["payment_id"], []).append(dict(id=pp["id"], kind=pp["kind"], sensitive=bool(pp["sensitive"]),
                                                                image=f"/api/pages/{pp['id']}"))
    out = []
    for r in rows:
        f = blank_fields() | json.loads(r["fields"])
        out.append(dict(id=r["id"], fields=f, imported=bool(r["imported"]), submitted_at=r["submitted_at"], submitted_by=r["submitted_by"],
                        sheet=f.get("sheet") or r["s_sheet"], row=r["s_row"], pending=bool(r["s_dirty"]), note=r["s_note"] or "",
                        pages=pages.get(r["id"], [])))
    return out

def set_ledger(pid, **changes):
    """Any ledger edit (AR: Taxable; admin: any field). The row is queued for Excel: the sync loop finds it by what
    was last written there (excel_fields) and rewrites it, or moves it when the sheet, day or method group changed."""
    with _lock, conn() as c:
        r = c.execute("""SELECT p.fields, s.excel_fields, s.sheet FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                         WHERE p.id=? AND p.status='submitted'""", (pid,)).fetchone()
        if not r: return False
        f = json.loads(r["fields"])
        if not r["excel_fields"]:                         # first edit since it was written: remember what Excel holds now
            c.execute("UPDATE submissions SET excel_fields=? WHERE payment_id=?", (json.dumps(f | {"sheet": r["sheet"] or f.get("sheet")}), pid))
        for k, v in changes.items():
            if v is not None: f[k] = v
        c.execute("UPDATE payments SET fields=?, dedupe=?, updated_at=? WHERE id=?", (json.dumps(f), dedupe_key(f), now(), pid))
        # only rows that live in the workbook sync back; uploaded imports (row NULL) stay in CheckFlow
        c.execute("UPDATE submissions SET dirty=1, note='' WHERE payment_id=? AND row IS NOT NULL", (pid,))
        c.execute("UPDATE submissions SET sheet=? WHERE payment_id=? AND row IS NULL", (f.get("sheet") or "", pid))
        return True

def dirty_rows():
    with conn() as c:
        rows = c.execute("""SELECT p.id, p.fields, s.sheet, s.row, s.excel_fields, s.pending_op FROM payments p JOIN submissions s ON s.payment_id=p.id
                            WHERE s.dirty=1""").fetchall()
    out = []
    for r in rows:
        f = json.loads(r["fields"])
        x = json.loads(r["excel_fields"]) if r["excel_fields"] else dict(f)
        x["sheet"] = r["sheet"] or x.get("sheet")
        out.append(dict(id=r["id"], fields=f, excel=x, sheet=r["sheet"], row=r["row"], op=r["pending_op"] or ""))
    return out

def sync_result(pid, row=None, note="", sheet=None, fields=None, removed=False):
    with _lock, conn() as c:
        if note: c.execute("UPDATE submissions SET note=? WHERE payment_id=?", (note, pid))
        elif removed:                                   # taken out of the workbook (deleted from the ledger)
            c.execute("""UPDATE submissions SET dirty=0, note='', row=NULL, excel_fields=NULL, pending_op='', written_at=?
                         WHERE payment_id=?""", (now(), pid))
        else: c.execute("""UPDATE submissions SET dirty=0, note='', pending_op='', row=COALESCE(?, row), sheet=COALESCE(?, sheet),
                           excel_fields=COALESCE(?, excel_fields), written_at=? WHERE payment_id=?""",
                        (row, sheet, json.dumps(fields) if fields else None, now(), pid))

def submitted_on(sheet, received):
    """Payments already written for one sheet/day (their rows move when a day block is rebuilt)."""
    with conn() as c:
        rows = c.execute("""SELECT p.id, p.fields, s.row FROM payments p JOIN submissions s ON s.payment_id=p.id
                            WHERE s.sheet=? AND p.imported=0""", (sheet,)).fetchall()
    return [dict(id=r["id"], fields=json.loads(r["fields"]), row=r["row"]) for r in rows if json.loads(r["fields"]).get("received") == received]

# ------------------------------------------------------------------ learned data CRUD
def learned():
    with conn() as c:
        return dict(
            payees=[dict(r) for r in c.execute("SELECT * FROM payees ORDER BY id")],
            customers=[dict(r) for r in c.execute("SELECT * FROM customers ORDER BY name")],
            accounts=[dict(r) for r in c.execute("SELECT * FROM accounts ORDER BY customer")],
            banks=[dict(r) for r in c.execute("SELECT * FROM banks ORDER BY name")],
            memos=[dict(r) for r in c.execute("SELECT * FROM memos ORDER BY customer")])

TABLES = {"payees": ("id", ["name", "sheet", "aliases"]), "customers": ("name", ["name", "sheets", "taxable_default", "deposit_bank_default"]),
          "accounts": (("routing", "account"), ["routing", "account", "customer"]), "banks": ("routing", ["routing", "name"]),
          "memos": ("pattern", ["pattern", "customer"])}

def learned_upsert(table, row, key=None):
    pk, cols = TABLES[table]
    vals = {k: str(row.get(k, "") or "").strip() for k in cols}
    if table == "customers": vals["name"] = vals["name"].upper()
    with _lock, conn() as c:
        if key is not None: learned_delete(table, key, c)
        if table == "payees":
            c.execute("INSERT INTO payees(name, sheet, aliases) VALUES(?,?,?)", (vals["name"], vals["sheet"], vals["aliases"]))
        else:
            extra = {"customers": {"source": "manual", "updated_at": now()}, "accounts": {"updated_at": now()}}.get(table, {})
            allv = vals | extra
            c.execute(f"INSERT OR REPLACE INTO {table}({','.join(allv)}) VALUES({','.join('?' * len(allv))})", tuple(allv.values()))

def learned_delete(table, key, c=None):
    pk, _ = TABLES[table]
    own = c is None
    c = c or conn()
    try:
        if isinstance(pk, tuple): c.execute(f"DELETE FROM {table} WHERE routing=? AND account=?", tuple(key.split("|", 1)))
        else: c.execute(f"DELETE FROM {table} WHERE {pk}=?", (key,))
        if own: c.commit()
    finally:
        if own: c.close()

def import_customers(names_to_sheets):
    with _lock, conn() as c:
        n = 0
        for name, sheets in names_to_sheets.items():
            cur = c.execute("""INSERT INTO customers(name, sheets, source, updated_at) VALUES(?,?,?,?)
                               ON CONFLICT(name) DO NOTHING""", (name, ",".join(sheets), "workbook", now()))
            n += cur.rowcount
        return n

def import_history(records, user):
    """One-time migration of past workbook rows into the ledger (no images). Idempotent per sheet+row+amount."""
    with _lock, conn() as c:
        have = {(r["sheet"], r["row"]) for r in c.execute("SELECT s.sheet, s.row FROM submissions s JOIN payments p ON p.id=s.payment_id WHERE p.imported=1")}
        n = 0
        for rec in records:
            if (rec["sheet"], rec["row"]) in have: continue
            f = blank_fields() | {k: rec.get(k, "") for k in KEYS if k in rec}
            pid = c.execute("""INSERT INTO payments(status, fields, warns, sources, dedupe, imported, created_at, updated_at, submitted_at, submitted_by)
                               VALUES('submitted',?,?,?,?,1,?,?,?,?)""", (json.dumps(f), "{}", '["import"]', dedupe_key(f), now(), now(),
                                                                         rec.get("received") or now(), f"import:{user}")).lastrowid
            c.execute("INSERT INTO submissions(payment_id, workbook, sheet, row, dirty, note, written_at) VALUES(?,?,?,?,0,'',?)",
                      (pid, "", rec["sheet"], rec["row"], now()))
            n += 1
        return n

# ------------------------------------------------------------------ spreadsheet uploads (Ledger -> Import Excel)
def ledger_fingerprints():
    """Counter of sheet|day|cents|customer for every payment already in the ledger (scanned or imported)."""
    from collections import Counter
    from .excel.ledger_import import fingerprint
    with conn() as c:
        rows = c.execute("""SELECT p.fields, s.sheet FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                            WHERE p.status='submitted'""").fetchall()
    out = Counter()
    for r in rows:
        f = json.loads(r["fields"] or "{}")
        out[fingerprint(r["sheet"] or f.get("sheet"), f.get("received"), f.get("amount"), f.get("customer"))] += 1
    return out

def import_upload(records, user, batch, filename):
    """Add uploaded rows to the ledger as one batch (undo removes the whole batch). row is left NULL so ledger edits
    never write into the live workbook for rows that came from another file."""
    tag = f"upload:{batch}:{filename}"[:200]
    with _lock, conn() as c:
        n = 0
        for rec in records:
            f = blank_fields() | {k: str(rec.get(k, "") or "") for k in KEYS if k in rec}
            pid = c.execute("""INSERT INTO payments(status, fields, warns, sources, dedupe, imported, created_at, updated_at, submitted_at, submitted_by)
                               VALUES('submitted',?,?,?,?,1,?,?,?,?)""", (json.dumps(f), "{}", '["import"]', dedupe_key(f), now(), now(),
                                                                         rec.get("received") or now(), f"import:{user}")).lastrowid
            c.execute("INSERT INTO submissions(payment_id, workbook, sheet, row, dirty, note, written_at) VALUES(?,?,?,NULL,0,'',?)",
                      (pid, tag, rec.get("sheet") or "", now()))
            n += 1
        return n

def import_batches():
    with conn() as c:
        rows = c.execute("""SELECT s.workbook, COUNT(*) AS n, MIN(s.written_at) AS at, MIN(p.submitted_by) AS by_,
                                   MIN(json_extract(p.fields, '$.received')) AS first, MAX(json_extract(p.fields, '$.received')) AS last,
                                   SUM(CAST(json_extract(p.fields, '$.amount') AS REAL)) AS total
                            FROM submissions s JOIN payments p ON p.id=s.payment_id
                            WHERE s.workbook LIKE 'upload:%' GROUP BY s.workbook ORDER BY at DESC""").fetchall()
    out = []
    for r in rows:
        _, batch, name = (r["workbook"].split(":", 2) + ["", ""])[:3]
        out.append(dict(batch=batch, filename=name, rows=r["n"], imported_at=r["at"], by=(r["by_"] or "").replace("import:", ""),
                        first=r["first"], last=r["last"], total=round(r["total"] or 0, 2)))
    return out

def undo_import(batch):
    if not re.fullmatch(r"[0-9a-f]{8,40}", batch or ""): return 0
    with _lock, conn() as c:
        ids = [r["payment_id"] for r in c.execute("SELECT payment_id FROM submissions WHERE workbook LIKE ?", (f"upload:{batch}:%",))]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]; q = ",".join("?" * len(chunk))
            c.execute(f"DELETE FROM submissions WHERE payment_id IN ({q})", chunk)
            c.execute(f"DELETE FROM payments WHERE id IN ({q}) AND imported=1", chunk)
        return len(ids)

# ------------------------------------------------------------------ ledger: delete / restore (the ledger is the source of truth)
def ledger_delete(pid, user, reason=""):
    """Move a sent payment to the Deleted section. Its workbook row (if any) is queued for removal."""
    with _lock, conn() as c:
        r = c.execute("""SELECT p.fields, s.row, s.sheet, s.excel_fields FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                         WHERE p.id=? AND p.status='submitted'""", (pid,)).fetchone()
        if not r: return False
        c.execute("UPDATE payments SET status='deleted', deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), user, reason or "", pid))
        if r["row"]:
            f = json.loads(r["fields"])
            if not r["excel_fields"]:
                c.execute("UPDATE submissions SET excel_fields=? WHERE payment_id=?", (json.dumps(f | {"sheet": r["sheet"] or f.get("sheet")}), pid))
            c.execute("UPDATE submissions SET dirty=1, pending_op='remove', note='' WHERE payment_id=?", (pid,))
        return True

def ledger_restore(pid):
    """Back into the ledger. If its workbook row was already removed, it is queued to be written again."""
    with _lock, conn() as c:
        r = c.execute("""SELECT s.row, s.dirty, s.pending_op, s.workbook FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                         WHERE p.id=? AND p.status='deleted'""", (pid,)).fetchone()
        if not r: return False
        c.execute("UPDATE payments SET status='submitted', deleted_at=NULL, deleted_by=NULL, delete_reason=NULL WHERE id=?", (pid,))
        if r["pending_op"] == "remove" and r["dirty"]:           # never left the workbook: just cancel the removal
            c.execute("UPDATE submissions SET dirty=0, pending_op='', note='' WHERE payment_id=?", (pid,))
        elif not r["row"] and r["workbook"] is not None and not str(r["workbook"]).startswith("upload:"):
            c.execute("UPDATE submissions SET dirty=1, pending_op='write', note='' WHERE payment_id=?", (pid,))
        return True

def deleted_rows():
    with conn() as c:
        rows = c.execute("""SELECT p.*, s.sheet AS s_sheet FROM payments p LEFT JOIN submissions s ON s.payment_id=p.id
                            WHERE p.status='deleted' ORDER BY p.deleted_at DESC""").fetchall()
    out = []
    for r in rows:
        f = blank_fields() | json.loads(r["fields"])
        out.append(dict(id=r["id"], fields=f, sheet=f.get("sheet") or r["s_sheet"], imported=bool(r["imported"]),
                        deleted_at=r["deleted_at"], deleted_by=r["deleted_by"], reason=r["delete_reason"] or ""))
    return out

# ------------------------------------------------------------------ attachments (extra pages added to a payment by hand)
def attach_pages(pid, page_ids):
    with _lock, conn() as c:
        top = c.execute("SELECT COALESCE(MAX(ord), -1) m FROM payment_pages WHERE payment_id=?", (pid,)).fetchone()["m"]
        for k, pg in enumerate(page_ids): c.execute("INSERT OR IGNORE INTO payment_pages VALUES(?,?,?)", (pid, pg, top + 1 + k))

def remove_attachment(pid, page_id):
    """Only pages added as attachments can be removed; returns the image file name to delete, or None."""
    with _lock, conn() as c:
        r = c.execute("""SELECT p.image FROM pages p JOIN payment_pages pp ON pp.page_id=p.id
                         WHERE pp.payment_id=? AND p.id=? AND p.kind='attachment'""", (pid, page_id)).fetchone()
        if not r: return None
        c.execute("DELETE FROM payment_pages WHERE payment_id=? AND page_id=?", (pid, page_id))
        c.execute("DELETE FROM pages WHERE id=?", (page_id,))
        return r["image"]

def payment_pages(pid):
    with conn() as c:
        return [dict(r) for r in c.execute("""SELECT p.* FROM payment_pages pp JOIN pages p ON p.id=pp.page_id
                                              WHERE pp.payment_id=? ORDER BY pp.ord, p.idx""", (pid,))]

# ------------------------------------------------------------------ password reset requests ("I forgot my password")
def add_reset_request(login, user_id):
    with _lock, conn() as c:
        if c.execute("SELECT 1 FROM reset_requests WHERE user_id IS ? AND login=? AND status='open'", (user_id, login)).fetchone(): return
        c.execute("INSERT INTO reset_requests(login, user_id, created_at) VALUES(?,?,?)", (login, user_id, now()))

def reset_requests():
    with conn() as c:
        return [dict(r) for r in c.execute("""SELECT r.id, r.login, r.user_id, r.created_at, u.display_name, u.username, u.email
                                              FROM reset_requests r LEFT JOIN users u ON u.id=r.user_id
                                              WHERE r.status='open' ORDER BY r.id""")]

def close_reset_requests(user_id=None, req_id=None, by=""):
    with _lock, conn() as c:
        if req_id: c.execute("UPDATE reset_requests SET status='closed', handled_by=?, handled_at=? WHERE id=?", (by, now(), req_id))
        if user_id: c.execute("UPDATE reset_requests SET status='closed', handled_by=?, handled_at=? WHERE user_id=? AND status='open'", (by, now(), user_id))
