"""Paths and static configuration. Everything runtime-editable lives in the settings table."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("CHECKFLOW_DATA", os.path.join(ROOT, "data"))
IMAGES = os.path.join(DATA, "images")
WORKBOOKS = os.path.join(DATA, "workbooks")       # workbooks created or uploaded in CheckFlow
DB_PATH = os.path.join(DATA, "checkflow.db")
STATIC = os.environ.get("CHECKFLOW_STATIC", os.path.join(ROOT, "static"))

# Payment methods and the workbook column family each one is written to.
METHODS = {
    "check": {"label": "Check", "column": "check"},
    "cash": {"label": "Cash", "column": "cash"},
    "card": {"label": "Credit card", "column": "credit"},
    "ach": {"label": "ACH / e-check", "column": "credit"},
    "wire": {"label": "Wire transfer", "column": "credit"},
}

# Subtotal group order inside a day block, and default labels (overridden by what the sheet already uses).
GROUPS = ["credit", "check", "cash"]
GROUP_LABELS = {"check": "CHECKS", "cash": "CASH", "credit": "CREDIT"}

# Seeds for learned data on first run (all editable in the app).
SEED_PAYEES = [
    # name on checks / emails, workbook sheet, aliases used in file names
    ("Magic Valley Concrete", "MVC", ["MVC", "MAGIC VALLEY"]),
    ("Rio Valley Pipe", "RIO", ["RVP", "RIO", "RIO VALLEY"]),
    ("Upper Valley Materials", "UPPER", ["UVM", "UPPER", "UPPER VALLEY"]),
    ("Valley Concrete Pumps", "VCP", ["VCP", "VALLEY CONCRETE PUMP"]),
]
SEED_BANKS = {"114915447": "Rio Bank", "114917623": "IBC Bank"}
DEFAULT_SETTINGS = {
    "ignore_sheets": "Sheet1, Sheet2, FORMAT, DEPOSIT TAXES",
    "deposit_bank_check": "TNB",
    "deposit_bank_cash": "",
    "deposit_bank_card": "",
    "deposit_bank_ach": "",
    "deposit_bank_wire": "",
    "deposit_banks": "TNB, LSB, LONE STAR, BPS, MID",
    "keep_sensitive_pages": "0",
    "auth_mode": "local",            # local | ldap (ldap always falls back to local accounts)
    "ldap_server": "",               # ldap://dc01.company.local or ldaps://...
    "ldap_domain": "",               # COMPANY  (NetBIOS) -> binds as COMPANY\\user
    "ldap_upn_suffix": "",           # company.local -> binds as user@company.local
    "ldap_base_dn": "",              # DC=company,DC=local
    "ldap_admin_group": "",          # CN=CheckFlow Admins,OU=Groups,DC=company,DC=local
    "ldap_ar_group": "",             # CN=Accounts Receivable,...  (empty = any domain user is AR)
}

os.makedirs(IMAGES, exist_ok=True)
