@echo off
rem One-click: stop the dashboard service recorded in runtime state.
rem This does NOT stop the shared browser - use browser-stop.bat for that.
chcp 65001 >nul
cd /d "%~dp0.."
"%~dp0..\..\.venv\Scripts\python.exe" -u "%~dp0..\..\automation\scripts\board_service.py" --stop
pause
