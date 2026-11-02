@echo off
rem One-click: show the shared ("public") browser status.
rem The shared browser is the one Edge/Chrome instance that the dashboard / scripts / wait_login attach to.
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0..\automation\scripts\browser_broker.py" --status
pause
