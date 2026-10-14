"""Authentication: Active Directory (LDAP bind) with local-account fallback, cookie sessions, HTTP Basic for scripts.

Roles: admin (everything) and ar (accounts receivable: ledger only, may change Taxable).
Flow on login:
  1. If AD is configured (auth_mode=ldap), try an LDAP bind as the user. Success -> role from AD groups,
     a local 'ldap' user record is created/updated (no password stored).
  2. Otherwise, or if AD is unreachable / rejects the password, check local accounts (PBKDF2-hashed passwords).
First run seeds a local admin/admin account flagged must_change (the UI keeps nagging until it is changed)."""
import base64, hashlib, secrets, time
from fastapi import Request, HTTPException
from . import db

COOKIE, TTL = "cf_session", 12 * 3600
_fails = {}

# ------------------------------------------------------------------ passwords / users
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()

def user_count():
    with db.conn() as c: return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]

def seed_admin():
    """First run: local admin/admin so nobody is locked out. Flagged must_change."""
    if user_count() == 0:
        create_user("admin", "admin", "admin", must_change=True, min_len=1)

def create_user(username, pw, role, must_change=False, min_len=6, source="local", display_name=""):
    username = (username or "").strip()
    if not username: raise HTTPException(400, "Enter a username.")
    if source == "local" and len(pw or "") < min_len: raise HTTPException(400, f"Password must be at least {min_len} characters.")
    if role not in ("admin", "ar"): raise HTTPException(400, "Unknown role.")
    salt, h = hash_pw(pw) if source == "local" else ("", "")
    with db._lock, db.conn() as c:
        try:
            c.execute("""INSERT INTO users(username, salt, hash, role, source, display_name, active, must_change, created_at)
                         VALUES(?,?,?,?,?,?,1,?,?)""", (username, salt, h, role, source, display_name, int(must_change), db.now()))
        except Exception:
            raise HTTPException(400, "That username already exists.")

def set_password(uid, pw, min_len=6):
    if len(pw or "") < min_len: raise HTTPException(400, f"Password must be at least {min_len} characters.")
    salt, h = hash_pw(pw)
    with db._lock, db.conn() as c:
        c.execute("UPDATE users SET salt=?, hash=?, must_change=0 WHERE id=?", (salt, h, uid))

def _local_check(username, pw):
    with db.conn() as c:
        u = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND source='local'", (username.strip(),)).fetchone()
    if u and u["active"] and u["hash"] and secrets.compare_digest(hash_pw(pw, u["salt"])[1], u["hash"]): return dict(u)
    return None

def _ldap_user(username, info):
    """Create/refresh the local record of an AD user. Role always follows AD groups."""
    with db._lock, db.conn() as c:
        u = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if u and u["source"] == "local":
            return None            # a local account with the same name wins; never let AD take it over silently
        if u:
            if not u["active"]: return None
            c.execute("UPDATE users SET role=?, display_name=? WHERE id=?", (info["role"], info.get("display_name", ""), u["id"]))
        else:
            c.execute("""INSERT INTO users(username, salt, hash, role, source, display_name, active, must_change, created_at)
                         VALUES(?,?,?,?,'ldap',?,1,0,?)""", (username, "", "", info["role"], info.get("display_name", ""), db.now()))
        return dict(c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone())

def authenticate(username, pw):
    """-> (user dict, how) or (None, reason). Tries AD first when configured, then local accounts."""
    username = (username or "").strip()
    if not username or not pw: return None, "Enter your username and password."
    reason = None
    if db.get_setting("auth_mode") == "ldap" and db.get_setting("ldap_server"):
        from . import ldap_auth
        try:
            info = ldap_auth.login(username, pw, db.settings())
            if info:
                u = _ldap_user(username, info)
                if u: return u, "ldap"
            else:
                reason = "ad_rejected"
        except ldap_auth.NotAllowed as e:
            return None, str(e)
        except ldap_auth.Unreachable:
            reason = "ad_unreachable"
    u = _local_check(username, pw)
    if u: return u, "local"
    if reason == "ad_unreachable": return None, "Active Directory is unreachable and no local account matched."
    return None, "Wrong username or password."

def login(username, pw, ip):
    key = ((username or "").lower(), ip); now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < 300]
    if len(_fails[key]) >= 5: raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    u, how = authenticate(username, pw)
    if not u:
        _fails[key].append(now); raise HTTPException(401, how)
    _fails.pop(key, None)
    tok = secrets.token_urlsafe(32)
    with db._lock, db.conn() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (now,))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, u["id"], now + TTL))
        c.execute("UPDATE users SET last_login=? WHERE id=?", (db.now(), u["id"]))
    db.audit(u["username"], "login", via=how)
    return tok

def logout(tok):
    with db._lock, db.conn() as c: c.execute("DELETE FROM sessions WHERE token=?", (tok,))

def _public(u):
    return dict(id=u["id"], username=u["username"], role=u["role"], source=u["source"],
                display_name=u["display_name"] or "", must_change=bool(u["must_change"]))

def current_user(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        with db.conn() as c:
            r = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                             WHERE s.token=? AND s.expires>? AND u.active=1""", (tok, time.time())).fetchone()
        if r: return _public(r)
    h = request.headers.get("authorization", "")
    if h.lower().startswith("basic "):                     # scripts / curl: Authorization: Basic base64(user:pass)
        try: user, pw = base64.b64decode(h[6:]).decode().split(":", 1)
        except Exception: return None
        u, _ = authenticate(user, pw)
        if u: return _public(u)
    return None

def require_user(request: Request):
    u = current_user(request)
    if not u: raise HTTPException(401, "Please sign in.")
    return u

def require_admin(request: Request):
    u = require_user(request)
    if u["role"] != "admin": raise HTTPException(403, "Only an admin can do this.")
    return u
