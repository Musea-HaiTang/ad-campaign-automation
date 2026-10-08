@echo off
rem One-click: start the dashboard service and open it in the default browser.
rem Close this window (or press Ctrl+C) to stop the service.
cd /d "%~dp0"
start "" http://127.0.0.1:8770/
%~dp0..\.venv\Scripts\python.exe -u app.py %*
pause
