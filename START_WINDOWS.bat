@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "TODAYGO_PROJECT_ROOT=%~dp0"
echo TodayGo - Windows launcher
powershell.exe -NoLogo -NoProfile -Command "& ([scriptblock]::Create([System.IO.File]::ReadAllText((Join-Path $env:TODAYGO_PROJECT_ROOT 'scripts\bootstrap_windows.ps1'))))"
set "TODAYGO_EXIT_CODE=%ERRORLEVEL%"
if not "%TODAYGO_EXIT_CODE%"=="0" (
    echo.
    echo Startup failed. Copy the error text above and send it for help.
    pause
)
exit /b %TODAYGO_EXIT_CODE%
