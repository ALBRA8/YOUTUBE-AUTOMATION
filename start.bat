@echo off
REM Arranque rapido — Windows
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo 🎬 YT Automation v2.0 → http://127.0.0.1:8000
start "" http://127.0.0.1:8000
uvicorn main:app --host 127.0.0.1 --port 8000
pause
