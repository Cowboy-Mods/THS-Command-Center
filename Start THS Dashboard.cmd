@echo off
setlocal
title Start THS Dashboard

set "THS_DATABASE=%USERPROFILE%\Documents\THS-Command-Center-Data\inventory.sqlite3"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ths-dashboard.ps1" -Action start -DatabasePath "%THS_DATABASE%"
set "THS_EXIT=%ERRORLEVEL%"

echo.
if not "%THS_EXIT%"=="0" (
    echo THS Dashboard did not start successfully.
    pause
)
exit /b %THS_EXIT%
