@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: installing CheckFlow. This needs internet once and takes a few minutes...
  py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -3.10 -m venv .venv 2>nul || python -m venv .venv
  if not exist .venv\Scripts\python.exe (
    echo Python 3.10 to 3.12 was not found. Install Python 3.12 from python.org, tick "Add python.exe to PATH", then run this again.
    pause
    exit /b 1
  )
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
echo Starting CheckFlow. Keep this window open while you work. Close it to stop the app.
.venv\Scripts\python run.py
pause
