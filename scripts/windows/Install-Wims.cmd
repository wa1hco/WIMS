@echo off
setlocal
REM Double-click installer entry point for tired operators.
REM Bypasses PowerShell execution policy for this run only (no permanent policy change).

cd /d "%~dp0"
echo.
echo  WIMS Windows install
echo  ====================
echo.

REM Prefer elevated install for winget + firewall; continue if user declines UAC.
net session >nul 2>&1
if errorlevel 1 (
  echo  Requesting Administrator for Python/Git install and firewall...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%ComSpec%' -Verb RunAs -ArgumentList '/c cd /d \"%~dp0\" && powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0Install-Wims.ps1\" %* & pause' "
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Wims.ps1" %*
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
  echo  Install finished with errors ^(code %ERR%^).
) else (
  echo  Install finished.
  echo  Start WIMS: double-click Start-WimsServer.cmd
)
echo.
pause
exit /b %ERR%
