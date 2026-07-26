@echo off
setlocal
title Stop THS Dashboard

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ths-dashboard.ps1" -Action stop
set "THS_EXIT=%ERRORLEVEL%"

echo.
if not "%THS_EXIT%"=="0" (
    echo THS Dashboard was not stopped.
    pause
)
exit /b %THS_EXIT%
