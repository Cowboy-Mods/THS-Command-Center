@echo off
setlocal
title Open Maeve Command Console
powershell.exe -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:48176/' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }"
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
