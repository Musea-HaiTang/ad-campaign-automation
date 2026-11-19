@echo off
rem One-click: start the dashboard service and open its actual URL.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -u -m automation.scripts board-service --start
set "URL="
for /f "delims=" %%U in ('".venv\Scripts\python.exe" -u -m automation.scripts board-service --url') do set "URL=%%U"
if defined URL start "" "%URL%"
pause
