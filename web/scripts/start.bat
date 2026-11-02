@echo off
rem One-click: start the dashboard service and open its actual URL.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -u automation\scripts\board_service.py --start
set "URL="
for /f "delims=" %%U in ('".venv\Scripts\python.exe" -u automation\scripts\board_service.py --url') do set "URL=%%U"
if defined URL start "" "%URL%"
pause
