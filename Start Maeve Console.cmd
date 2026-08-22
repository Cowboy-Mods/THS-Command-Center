@echo off
setlocal
title Start Maeve Console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maeve-console.ps1" -Action start
exit /b %ERRORLEVEL%
