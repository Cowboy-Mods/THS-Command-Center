@echo off
setlocal
title Open Maeve Command Console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maeve-console.ps1" -Action status >nul 2>&1
if not errorlevel 1 goto open_console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maeve-console.ps1" -Action start
if errorlevel 1 (
    echo.
    echo Maeve could not be opened. The error above has been left visible.
    pause
    exit /b %ERRORLEVEL%
)
:open_console
start "" "http://127.0.0.1:48176/"
exit /b 0
