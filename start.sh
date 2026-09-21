#!/usr/bin/env bash
# macOS/Linux launcher for memo (equivalent of start.bat on Windows).
# Creates the venv on first run, installs pinned deps once, stops any
# instance already listening on the port, then starts uvicorn.
set -euo pipefail

cd "$(dirname "$0")"

HOST="127.0.0.1"
PORT="8000"
VENV_PY=".venv/bin/python"

# 1. Create the virtual environment on first run.
if [ ! -x "$VENV_PY" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# 2. Install pinned dependencies once (marker file avoids reinstalling).
if [ ! -f ".venv/memo-installed" ]; then
  echo "Installing dependencies (needs network the first time)..."
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r requirements.lock.txt
  touch .venv/memo-installed
fi

# 3. Stop any instance already listening on the port (this is the "restart").
EXISTING_PID="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN || true)"
if [ -n "$EXISTING_PID" ]; then
  echo "Stopping existing memo on port ${PORT} (PID ${EXISTING_PID})..."
  kill "$EXISTING_PID" 2>/dev/null || true
  # Give it a moment to release the port.
  for _ in 1 2 3 4 5; do
    sleep 1
    lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || break
  done
fi

# 4. Start the app.
echo "Open http://${HOST}:${PORT} in your browser."
echo "Press Ctrl+C to stop memo before backing up data."
exec "$VENV_PY" -m uvicorn app:app --host "$HOST" --port "$PORT"
