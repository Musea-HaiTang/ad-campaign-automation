@echo off
rem One-click: show the shared ("public") browser status.
rem The shared browser is the one Edge/Chrome instance used by the board and commands.
chcp 65001 >nul
cd /d "%~dp0.."
".venv\Scripts\python.exe" -u -m automation.scripts browser --status
pause
