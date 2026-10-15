@echo off
rem STUDY_IN_UNIV local preview server - double-click to run, close this window to stop
cd /d "%~dp0"
start "" http://127.0.0.1:8000
python -X utf8 -m uvicorn app.server:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
pause
