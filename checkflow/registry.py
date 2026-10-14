"""Learned data the extractor consults: payees (division -> sheet), customers, banks, per-customer defaults.

StaticRegistry works from in-memory seeds (benchmarks/tests). db.DbRegistry subclasses it with SQLite storage."""
import re
from rapidfuzz import fuzz, process as rfprocess
from .config import SEED_PAYEES, SEED_BANKS

def nkey(s): return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

class StaticRegistry:
    def __init__(self, payees=None, banks=None, customers=None, accounts=None, deposit_defaults=None):
        self._payees = payees if payees is not None else [(n, s, a) for n, s, a in SEED_PAYEES]
        self._banks = dict(SEED_BANKS if banks is None else banks)
        self._customers = list(customers or [])
        self._accounts = dict(accounts or {})          # (routing, account) -> customer
        self._dep = dict(deposit_defaults or {"check": "TNB"})
        self._cust_defaults = {}                       # customer -> {taxable, deposit_bank}

    # ---- lookups used by the extractor
    def payees(self): return self._payees
    def banks(self): return self._banks
    def customers(self): return self._customers
    def bank(self, routing): return self.banks().get(routing)

    def match_payee(self, text):
        """Find a division name (e.g. 'Magic Valley Concrete') in free text -> (name, sheet)."""
        t = nkey(text)
        best, bs = None, 0
        for name, sheet, _aliases in self.payees():
            n = nkey(name)
            if len(n) < 6: continue
            s = 100 if n in t else fuzz.partial_ratio(n, t) if len(t) < 4000 else 0
            if s > bs: best, bs = (name, sheet), s
        return best if bs >= 90 else None

    def payee_from_filename(self, filename):
        base = re.sub(r"\.[a-z0-9]+$", "", (filename or "").upper())
        first = re.split(r"[ _\-]+", base)[0] if base else ""
        for name, sheet, aliases in self.payees():
            if first and (first == sheet.upper() or first in [a.upper() for a in aliases]): return (name, sheet)
        for name, sheet, aliases in self.payees():
            if any(len(a) > 3 and a.upper() in base for a in aliases): return (name, sheet)
        return None

    def customer_for_account(self, routing, account):
        if not (routing and account): return None
        return self._accounts_get(routing, account)
    def _accounts_get(self, routing, account): return self._accounts.get((routing, account))

    def snap_customer(self, name):
        """Snap an OCR'd name to a known customer when it is clearly the same one."""
        if not name: return name
        known = self.customers()
        if not known: return name
        m = rfprocess.extractOne(name, known, scorer=fuzz.token_sort_ratio)
        if m and m[1] >= 92: return m[0]
        k = nkey(name)
        for c in known:                      # same letters, different spacing/punctuation ('JRGARCIACOMPANY')
            if nkey(c) == k: return c
        m = rfprocess.extractOne(k, {c: nkey(c) for c in known}, scorer=fuzz.ratio)
        if m and m[1] >= 93: return m[2]
        return name

    def is_known_customer(self, name):
        k = nkey(name)
        return bool(k) and any(nkey(c) == k for c in self.customers())

    def defaults_for(self, customer, method):
        d = {"deposit_bank": self._dep.get(method, "")}
        d.update({k: v for k, v in self._cust_defaults.get(nkey(customer), {}).items() if v})
        return d
