@echo off
setlocal
set "MAEVE_ROOT=%~dp0"
set "MAEVE_LAUNCHER=%MAEVE_ROOT%scripts\start-windows.py"
set "PYTHONDONTWRITEBYTECODE=1"
if not defined MAEVE_PYTHON goto unavailable
if not exist "%MAEVE_PYTHON%" goto unavailable
cd /d "%MAEVE_ROOT%"
"%MAEVE_PYTHON%" -B "%MAEVE_LAUNCHER%" --open-browser --voice-provider elevenlabs
if errorlevel 1 goto failed
exit /b 0
:unavailable
echo Configure MAEVE_PYTHON with the exact local Python executable first.
:failed
echo Maeve did not complete normally. No automatic retry was attempted.
pause
exit /b 1
