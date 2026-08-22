@echo off
setlocal
title Open Maeve Command Console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maeve-console.ps1" -Action start
if errorlevel 1 exit /b %ERRORLEVEL%
start "" "http://127.0.0.1:48176/"
exit /b 0
