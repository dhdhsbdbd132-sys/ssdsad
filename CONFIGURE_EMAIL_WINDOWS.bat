@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".windows-venv\Scripts\python.exe" (
    echo First run START_WINDOWS.bat to install the app, then close it.
    pause
    exit /b 1
)
".windows-venv\Scripts\python.exe" -X utf8 "scripts\configure_email.py"
set "TODAYGO_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %TODAYGO_EXIT_CODE%
