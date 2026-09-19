@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
if not exist ".venv\memo-installed" (
  .venv\Scripts\python.exe -m pip install -r requirements.lock.txt
  if errorlevel 1 goto failed
  type nul > .venv\memo-installed
)
echo Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C to stop memo before backing up data.
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failed
exit /b
:failed
echo memo could not start. Please check the error above.
pause
