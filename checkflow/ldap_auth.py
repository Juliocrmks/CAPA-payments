"""Active Directory login over LDAP (ldap3, pure Python).

Settings used (Settings > Sign-in in the app):
  ldap_server       ldap://dc01.company.local  or  ldaps://dc01.company.local:636
  ldap_upn_suffix   company.local          -> binds as  user@company.local      (preferred)
  ldap_domain       COMPANY                -> binds as  COMPANY\\user            (if no UPN suffix)
  ldap_base_dn      DC=company,DC=local    -> where to look the user up for group membership
  ldap_admin_group  CN=CheckFlow Admins,OU=Groups,DC=company,DC=local   (DN or just the CN)
  ldap_ar_group     CN=Accounts Receivable,... (empty: any authenticated domain user gets the AR role)"""
import re

class Unreachable(Exception): pass
class NotAllowed(Exception): pass

def _connection(server_url, user, password):
    """Separated so tests can swap in ldap3's MOCK_SYNC strategy."""
    import ldap3
    server = ldap3.Server(server_url, get_info=ldap3.NONE, connect_timeout=5)
    return ldap3.Connection(server, user=user, password=password, auto_bind=False, receive_timeout=8, raise_exceptions=False)

def bind_name(username, s):
    if "@" in username or "\\" in username: return username
    if s.get("ldap_upn_suffix"): return f"{username}@{s['ldap_upn_suffix']}"
    if s.get("ldap_domain"): return f"{s['ldap_domain']}\\{username}"
    return username

def _cn(group):
    m = re.match(r"\s*CN=([^,]+)", group or "", re.I)
    return (m.group(1) if m else (group or "")).strip().lower()

def login(username, password, s):
    """-> {'role', 'display_name', 'groups'} on success, None if AD rejects the credentials.
    Raises Unreachable when the server can't be contacted, NotAllowed when the user is in neither group."""
    import ldap3
    from ldap3.core.exceptions import LDAPSocketOpenError, LDAPException
    sam = username.split("\\")[-1].split("@")[0]
    try:
        conn = _connection(s["ldap_server"], bind_name(username, s), password)
        if not conn.bind():
            res = (conn.result or {}).get("description", "")
            if res in ("invalidCredentials",) or conn.result.get("result") == 49: return None
            if conn.result.get("result") in (-1, None) or "socket" in str(conn.result).lower(): raise Unreachable(str(conn.result))
            return None
    except LDAPSocketOpenError as e:
        raise Unreachable(str(e))
    except LDAPException as e:
        raise Unreachable(str(e))
    groups, display = [], ""
    try:
        if s.get("ldap_base_dn"):
            conn.search(s["ldap_base_dn"], f"(|(sAMAccountName={ldap3.utils.conv.escape_filter_chars(sam)})"
                                           f"(userPrincipalName={ldap3.utils.conv.escape_filter_chars(bind_name(username, s))}))",
                        attributes=["memberOf", "displayName", "cn"])
            if conn.entries:
                e = conn.entries[0]
                groups = [str(g) for g in (e.memberOf.values if "memberOf" in e else [])]
                display = str(e.displayName) if "displayName" in e and e.displayName.value else (str(e.cn) if "cn" in e else "")
    finally:
        conn.unbind()
    names = {_cn(g) for g in groups} | {g.lower() for g in groups}
    adm, ar = s.get("ldap_admin_group", ""), s.get("ldap_ar_group", "")
    if adm and (_cn(adm) in names or adm.lower() in names): role = "admin"
    elif not ar or _cn(ar) in names or ar.lower() in names: role = "ar"
    else: raise NotAllowed("Your account is not in the CheckFlow group. Ask an admin for access.")
    return dict(role=role, display_name=display, groups=groups)

def test(s, username, password):
    """Settings screen 'Test connection' button."""
    try:
        r = login(username, password, s)
        return {"ok": bool(r), "message": f"Signed in as {r['display_name'] or username}, role {r['role']}." if r else "AD rejected the username or password."}
    except Unreachable as e:
        return {"ok": False, "message": f"Can't reach the AD server: {e}"}
    except NotAllowed as e:
        return {"ok": False, "message": str(e)}
