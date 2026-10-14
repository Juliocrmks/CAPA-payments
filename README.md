# CheckFlow · CAPA payments

Scan the day's payment packets, check what was read, and write them into the payee workbook (MVC, UPPER, RIO, VCP)
as day blocks with subtotals, the way the sheets are kept by hand. Everything runs on one office computer: no cloud
OCR, no per-check cost.

## Run it

| | |
|---|---|
| **Mac** | Double-click `CheckFlow.command` (first time: right-click → Open). Needs Python 3.10–3.12 from python.org. |
| **Windows** | Double-click `run.bat`. |
| **Terminal** | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python run.py` |

It opens `http://127.0.0.1:8765`. The terminal also prints a network address (`http://192.168.x.x:8765`) that
accounts-receivable users open from their own computers. Use `--local-only` to keep it on this machine.

**First sign-in: `admin` / `admin`.** A banner stays up until you change it (your name → Change password).

Out of the box CheckFlow writes to a practice workbook in `data/`. Point it at the real one in **Settings → Workbook**.

A live demo on AWS EC2 is one `terraform apply` away: see [deploy/terraform](deploy/terraform/README.md).

## What it does

1. **Payments** (admin): drop a day's scanned PDF (or photos). Each page is classified and read:

   | Page | Becomes |
   |---|---|
   | Paper check (+ remittance stub) | **Check**: MICR routing/account/check #, amount, payer, bank |
   | TransactPro "You Just Got Paid!" e-mail | **Credit card** (Visa/MC/Amex …) or **ACH** (`CHECKING ****1234`), amount incl. fees |
   | CAPA receipt slip | Its red number becomes the **Ticket ref** of the payment it documents; a slip with nothing else is **Cash** |
   | Bank posting ("… ACH Entry … Posted Today") | **Wire transfer** |
   | Day-sheet printout, statements, quotes | skipped / attached as supporting pages |
   | Driver licence, card photos | attached, stored blurred (Settings can keep them readable) |

   The received date comes from the file name (`MVC OCT_09-26.pdf` → Oct 9 2026), the sheet from the file name
   prefix or what's printed. Review each card (uncertain fields are amber), **Validate**, or set **Pending** for later.
   **Continue → Send to Excel** writes all validated payments.
2. **Excel**: one block per sheet per *day received*: header row, CREDIT / CHECKS / CASH groups with `=SUM`
   subtotals, TOTAL. Column positions, labels, group order and spacing are read from each sheet, so MVC, UPPER, RIO
   and VCP each keep their own look. A second batch on the same day merges into that day's block. A timestamped
   backup is saved to `checkflow_backups/` next to the workbook first. If the workbook is open in Excel, nothing is
   written and you're told to close it.
3. **Ledger** (admin + AR): search, quick period filters, sheet/method/taxable filters, group by day / week /
   month / quarter / company / sheet / method / deposit bank / taxable, sortable columns, subtotals, taxable totals
   per deposit bank, CSV export, page images. **AR users can only change Taxable.** **Admins can correct any detail**
   of a sent payment (date, payee, customer, method, amount, refs, bank) from its side panel. Every edit takes the
   same road: saved at once, then written to the workbook (retried every 30 s while it's open in Excel). Same day,
   payee and method group: the changed cells are rewritten in place. Otherwise the payment moves to its new day block
   and its old row is emptied, so no rows shift and every `=SUM` stays right.

   **Daily bank totals** (everyone): for one day received, what went into each deposit bank as cash, checks and
   card/ACH/wire, how much is taxable, not taxable and not set yet, by bank or by bank and payee, with CSV. It is
   computed from the ledger on screen, so it changes the moment a Taxable, bank or amount is edited.

   **Import Excel** (admin): add past payments from any spreadsheet. The payee workbook itself (day blocks, any
   year) or a plain table with Date, Customer and Amount columns (Method, Check #, Ticket, Payee, Deposit bank and
   Taxable are used when present; .csv works too). A preview shows rows per payee, what's already in the ledger
   (same payee, day, client and amount: skipped), withdrawals left out, and dates that don't fit the rows around
   them (a 2026 typed among 2025 rows is corrected by default). Each import is one batch with **Undo**. Imported
   rows never change the live workbook.
4. **Analytics** (admin): one filter row (dates, day/week/month/quarter/year, payee, client, method) scopes
   everything: KPIs with change vs the previous period, receipts over time with a **projection** (straight-line
   trend, monthly seasonality once there are 24 months, 80% range; the current period by run-rate), a breakdown
   by payee, client, method or deposit bank (share, change, trend, next-period estimate, how often a client usually
   pays), and **storylines**: plain-language findings such as the leader and biggest movers, client concentration,
   new clients, regular clients who have gone quiet, the shift to electronic payments and the projection.
   Click a client or a storyline to focus on it. Every chart has a table view.
5. **Learned data** (admin): customers (import names from the workbook so scans snap to them), bank account →
   customer, division → sheet, banks, wire-posting text → customer. Everything confirmed is learned; everything is
   editable. **Import from workbook** can also bring past rows into the ledger once (optional migration).
6. **Settings** (admin): workbook, deposit banks and per-method defaults, sign-in, users, activity log.

## Sign-in

* **Local accounts** (PBKDF2-hashed). Admin creates AR users in Settings → Users.
* **Active Directory**: Settings → Sign-in → *Active Directory + local fallback*. Server (`ldaps://dc01…`), sign-in
  suffix or domain, search base, admin group, AR group; **Test with an account…** checks it. AD users appear after
  their first sign-in with the role their group gives them. Local accounts keep working when the domain controller
  is down; an AD account can never take over a local account with the same name.
* Scripts can use HTTP Basic (`curl -u user:pass http://host:8765/api/ledger`).

## Project layout

```
run.py                     start the server (+ open the browser)
checkflow/
  app.py                   FastAPI routes, background extraction worker, Excel sync loop
  auth.py, ldap_auth.py    sessions, local accounts, AD/LDAP
  db.py                    SQLite: payments, pages, ledger, learned data, users, audit log, import batches
  analytics.py             KPIs, periods, breakdowns, projection and storylines for the Analytics page
  registry.py              learned-data lookups used by the extractor
  extract/                 ocr.py (RapidOCR, PDF pages, orientation) · check.py (MICR) · docs.py (confirmations,
                           receipts, bank postings, page classification) · __init__.py (pipeline + grouping)
  excel/                   layout.py (reads a sheet's layout) · writer.py · importer.py · practice.py ·
                           ledger_import.py (spreadsheet upload: workbook or plain table, date checks, duplicates)
frontend/                  React 19 + MUI 7 source (npm install && npm run build → static/)
static/                    built UI, committed so no Node.js is needed to run
tests/                     pytest suite (80 tests)
tools/benchmark.py         extraction accuracy against the real packets' printed day sheets
```

## Tests

```
.venv/bin/python -m pytest              # everything (real-packet tests skip without references/)
.venv/bin/python -m tools.benchmark     # per-payment accuracy report on references/*.pdf
```

`references/` (real scans, phone photos, the real workbook) is git-ignored: it holds account numbers, card photos and an
ID. Accuracy on the 3 packets of Oct 9 2026 plus 2 phone photos (23 payments): found 22/23 · method 96% · check/ref #
96% · amount 87% · customer 74% · ticket 78%. Misses are handwritten amounts and receipt numbers, which the review
screen highlights. A page with no readable payment still becomes a card ("fill it in from the image"); nothing is
dropped silently. OCR is pinned to rapidocr-onnxruntime 1.2.3: the benchmark is the tool for judging an upgrade.

## Frontend development

```
cd frontend && npm install && npm run dev    # http://localhost:5173, proxies /api to a running run.py
npm run build                                # writes ../static
```
