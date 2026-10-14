"""Basic username/password auth with two roles: admin and ar (accounts receivable)."""
import hashlib, secrets, time
from fastapi import Request, HTTPException
import db

COOKIE, TTL = "cf_session", 12 * 3600
_fails = {}

def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()

def user_count():
    with db.conn() as c: return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]

def create_user(username, pw, role):
    username = username.strip()
    if not username or len(pw) < 6: raise HTTPException(400, "Use a username and a password of at least 6 characters.")
    if role not in ("admin", "ar"): raise HTTPException(400, "Unknown role.")
    salt, h = hash_pw(pw)
    with db._lock, db.conn() as c:
        try: c.execute("INSERT INTO users(username,salt,hash,role,active,created_at) VALUES(?,?,?,?,1,?)", (username, salt, h, role, db.now()))
        except Exception: raise HTTPException(400, "That username already exists.")

def set_password(uid, pw):
    if len(pw) < 6: raise HTTPException(400, "Password must be at least 6 characters.")
    salt, h = hash_pw(pw)
    with db._lock, db.conn() as c:
        c.execute("UPDATE users SET salt=?, hash=? WHERE id=?", (salt, h, uid)); c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))

def login(username, pw, ip):
    key = (username.lower(), ip); now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < 300]
    if len(_fails[key]) >= 5: raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    with db.conn() as c: u = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
    ok = u and u["active"] and secrets.compare_digest(hash_pw(pw, u["salt"])[1], u["hash"])
    if not ok:
        _fails[key].append(now); raise HTTPException(401, "Wrong username or password.")
    tok = secrets.token_urlsafe(32)
    with db._lock, db.conn() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (now,))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, u["id"], now + TTL))
    return tok

def logout(tok):
    with db._lock, db.conn() as c: c.execute("DELETE FROM sessions WHERE token=?", (tok,))

def current_user(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok: return None
    with db.conn() as c:
        r = c.execute("SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1", (tok, time.time())).fetchone()
    return dict(r) if r else None

def require_user(request: Request):
    u = current_user(request)
    if not u: raise HTTPException(401, "Please sign in.")
    return u

def require_admin(request: Request):
    u = require_user(request)
    if u["role"] != "admin": raise HTTPException(403, "Only an admin can do this.")
    return u
