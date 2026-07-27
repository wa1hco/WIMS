@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-WSJTX-RigNameShortcuts.ps1"
set "EC=%ERRORLEVEL%"
if /I not "%~1"=="/nopause" (
  echo.
  pause
)
exit /b %EC%
