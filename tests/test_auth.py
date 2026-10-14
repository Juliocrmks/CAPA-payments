"""Sign-in: default admin, local accounts, lockout, roles, HTTP Basic, and Active Directory (mocked LDAP) with local fallback."""
import base64
import pytest
from checkflow import ldap_auth, db

def test_default_admin_admin_works_and_is_flagged(client):
    r = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    me = client.get("/api/me").json()["user"]
    assert me["role"] == "admin" and me["must_change"] is True

def test_wrong_password_and_lockout(client):
    for _ in range(5):
        assert client.post("/api/login", json={"username": "ghost", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"username": "ghost", "password": "nope"}).status_code == 429

def test_protected_without_session(client):
    for path in ("/api/payments", "/api/ledger", "/api/settings", "/api/learned"):
        assert client.get(path).status_code == 401

def test_change_password_clears_flag(admin, client):
    admin.post("/api/users", json={"username": "temp_admin", "password": "secret1", "role": "admin"})
    from fastapi.testclient import TestClient
    c = TestClient(client.app); c.post("/api/login", json={"username": "temp_admin", "password": "secret1"})
    assert c.post("/api/me/password", json={"current": "wrong", "new": "secret22"}).status_code == 400
    assert c.post("/api/me/password", json={"current": "secret1", "new": "secret22"}).status_code == 200
    assert c.post("/api/login", json={"username": "temp_admin", "password": "secret22"}).status_code == 200

def test_ar_role_is_ledger_only(admin, client):
    admin.post("/api/users", json={"username": "ar_user", "password": "arpass1", "role": "ar"})
    from fastapi.testclient import TestClient
    ar = TestClient(client.app); ar.post("/api/login", json={"username": "ar_user", "password": "arpass1"})
    assert ar.get("/api/ledger").status_code == 200
    for method, path in (("get", "/api/payments"), ("get", "/api/settings"), ("get", "/api/users"), ("get", "/api/learned"),
                         ("post", "/api/submit"), ("post", "/api/import")):
        r = getattr(ar, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code in (403, 422), (path, r.status_code)

def test_http_basic(client):
    h = {"Authorization": "Basic " + base64.b64encode(b"admin:admin").decode()}
    assert client.get("/api/ledger", headers=h).status_code == 200
    h = {"Authorization": "Basic " + base64.b64encode(b"admin:bad").decode()}
    assert client.get("/api/ledger", headers=h).status_code == 401

# ------------------------------------------------------------------ Active Directory, mocked
class Attr:
    def __init__(self, v): self.value = v; self.values = v if isinstance(v, list) else [v]
    def __str__(self): return str(self.value)

class Entry:
    def __init__(self, **attrs): self._a = {k: Attr(v) for k, v in attrs.items()}
    def __contains__(self, k): return k in self._a
    def __getattr__(self, k): return self._a[k]

DIRECTORY = {   # bind name -> (password, groups, display name)
    "boss@capa.local": ("adpass", ["CN=CheckFlow Admins,OU=Groups,DC=capa,DC=local"], "Big Boss"),
    "maria@capa.local": ("adpass", ["CN=Accounts Receivable,OU=Groups,DC=capa,DC=local"], "Maria AR"),
    "intern@capa.local": ("adpass", ["CN=Interns,OU=Groups,DC=capa,DC=local"], "Intern"),
    "admin@capa.local": ("adpass", ["CN=CheckFlow Admins,OU=Groups,DC=capa,DC=local"], "Domain admin"),
}

class FakeConn:
    def __init__(self, user, password, down=False):
        self.user, self.password, self.down, self.entries, self.result = user, password, down, [], {}
    def bind(self):
        if self.down:
            from ldap3.core.exceptions import LDAPSocketOpenError
            raise LDAPSocketOpenError("connection refused")
        ok = DIRECTORY.get(self.user, (None,))[0] == self.password
        self.result = {} if ok else {"result": 49, "description": "invalidCredentials"}
        return ok
    def search(self, base, flt, attributes=None):
        pw, groups, name = DIRECTORY[self.user]
        self.entries = [Entry(memberOf=groups, displayName=name, cn=name)]
    def unbind(self): pass

@pytest.fixture()
def ad(monkeypatch):
    state = {"down": False}
    monkeypatch.setattr(ldap_auth, "_connection", lambda server, user, pw: FakeConn(user, pw, state["down"]))
    for k, v in dict(auth_mode="ldap", ldap_server="ldaps://dc01.capa.local", ldap_upn_suffix="capa.local", ldap_base_dn="DC=capa,DC=local",
                     ldap_admin_group="CN=CheckFlow Admins,OU=Groups,DC=capa,DC=local", ldap_ar_group="Accounts Receivable").items():
        db.set_setting(k, v)
    yield state
    db.set_setting("auth_mode", "local")

def login(client, u, p): return client.post("/api/login", json={"username": u, "password": p})

def test_ad_admin_group(client, ad):
    assert login(client, "boss", "adpass").status_code == 200
    me = client.get("/api/me").json()["user"]
    assert me["role"] == "admin" and me["source"] == "ldap" and me["display_name"] == "Big Boss"

def test_ad_ar_group_by_cn(client, ad):
    assert login(client, "maria", "adpass").status_code == 200
    assert client.get("/api/me").json()["user"]["role"] == "ar"

def test_ad_user_outside_groups_refused(client, ad):
    r = login(client, "intern", "adpass")
    assert r.status_code == 401 and "not in the CheckFlow group" in r.json()["detail"]

def test_ad_wrong_password(client, ad):
    assert login(client, "maria", "nope").status_code == 401

def test_local_fallback_when_ad_down(client, ad):
    ad["down"] = True
    assert login(client, "admin", "admin").status_code == 200          # local admin still gets in
    assert login(client, "boss", "adpass").status_code == 401           # AD-only user can't while AD is down

def test_ad_cannot_take_over_local_account(client, ad):
    # 'admin' exists locally; an AD account with the same name must not become that user
    r = login(client, "admin", "adpass")
    assert r.status_code == 401

def test_ldap_settings_test_endpoint(admin, ad):
    r = admin.post("/api/settings/test-ldap", json={"username": "maria", "password": "adpass"}).json()
    assert r["ok"] and "role ar" in r["message"]
