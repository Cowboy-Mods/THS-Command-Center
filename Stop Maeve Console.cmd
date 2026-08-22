@echo off
setlocal
title Stop Maeve Console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maeve-console.ps1" -Action stop
exit /b %ERRORLEVEL%
