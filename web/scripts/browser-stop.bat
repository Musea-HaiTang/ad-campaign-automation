@echo off
rem One-click: stop the shared ("public") browser.
rem Nothing breaks: the next fetch / script starts it again automatically.
chcp 65001 >nul
cd /d "%~dp0.."
"%~dp0..\..\.venv\Scripts\python.exe" -u "%~dp0..\..\automation\scripts\browser_broker.py" --stop
pause
