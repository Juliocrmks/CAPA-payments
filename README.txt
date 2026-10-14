CheckFlow - local check reader (no cloud, no AI service, no per-check cost)

START
  Mac: double-click CheckFlow.command (first time: right-click it, choose Open, then Open again). Needs Python 3.10 to 3.12.
  Windows: double-click run.bat (first run installs everything; needs Python 3.10 to 3.12).
  The app opens in your browser at http://127.0.0.1:8765

TEST SAFELY FIRST
  Out of the box it writes to data\Practice_Workbook.xlsx (sheets RVP, VCP, Magic Valley Concrete).
  When ready, open Settings in the app and paste the full path of your real workbook.
  A backup copy is saved in a "checkflow_backups" folder next to the workbook before every send.
  Close the workbook in Excel before pressing Send to Excel.

WHERE THINGS ARE
  data\checkflow.db   saved checks, pending list, learned names (payer / payee / bank)
  data\images\        the check images

USERS AND ROLES
  First launch: the app asks you to create the admin account (this must be done on the computer running CheckFlow).
  Admin: loads and reviews checks, edits everything, manages users (Users button), changes Settings.
  Accounts receivable: can only open the Ledger and change the Taxable field (the change is written to Excel).
  Add AR users from Users > Add a user.

OTHER COMPUTERS ON YOUR NETWORK
  When the app starts, the window prints a line like  http://192.168.1.20:8765  - AR users type that into their browser.
  The computer running CheckFlow must be on and the app window open. The first time, macOS may ask to allow incoming
  connections: choose Allow. To keep the app private to this computer, set the environment variable CHECKFLOW_LOCAL=1.

UPDATING FROM THE PREVIOUS VERSION
  Copy your old "data" folder into the new checkflow folder before starting; it is upgraded automatically.
