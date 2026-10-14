#!/bin/bash
# Double-click to start CheckFlow on a Mac.
cd "$(dirname "$0")"
PY=""
for c in python3.12 python3.11 python3.10; do
  if command -v $c >/dev/null 2>&1; then PY=$c; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 to 3.12 was not found."
  echo "Install it from https://www.python.org/downloads/ (pick 3.12), then double-click this file again."
  read -p "Press Enter to close"; exit 1
fi
# (re)install when the environment is missing or requirements changed
if [ ! -x .venv/bin/python ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing CheckFlow (first run or after an update). Needs internet once; takes a few minutes..."
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null && .venv/bin/python -m pip install -r requirements.txt \
    && touch .venv/.installed || { echo "Install failed."; read -p "Press Enter to close"; exit 1; }
fi
echo "Starting CheckFlow. Keep this window open while you work; close it to stop the app."
.venv/bin/python run.py "$@"
