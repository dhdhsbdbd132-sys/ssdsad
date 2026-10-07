@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "TODAYGO_PROJECT_ROOT=%~dp0"
set "TODAYGO_ANDROID_SERVER=1"
echo TodayGo - Android server for your local Wi-Fi network
powershell.exe -NoLogo -NoProfile -Command "& ([scriptblock]::Create([System.IO.File]::ReadAllText((Join-Path $env:TODAYGO_PROJECT_ROOT 'scripts\bootstrap_windows.ps1'))))"
set "TODAYGO_EXIT_CODE=%ERRORLEVEL%"
if not "%TODAYGO_EXIT_CODE%"=="0" (
    echo.
    echo Server stopped. Copy the error text above if help is needed.
    pause
)
exit /b %TODAYGO_EXIT_CODE%
