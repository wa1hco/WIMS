@echo off
setlocal EnableExtensions
REM Double-click install. Installs Python/Git if needed. No Set-ExecutionPolicy.
REM Always pass this tree's repo root so elevated UAC still finds the right folder.

cd /d "%~dp0"
set "HERE=%CD%"
REM scripts\windows -> repo root
for %%I in ("%HERE%\..\..") do set "REPO=%%~fI"

echo.
echo  WIMS Windows install
echo  ====================
echo  Repo: %REPO%
echo.

if not exist "%REPO%\src\wims\server\app.py" (
  echo  ERROR: This does not look like a WIMS checkout:
  echo    %REPO%
  echo  Clone or copy the full repo, then run Install-Wims.cmd from scripts\windows.
  echo.
  pause
  exit /b 1
)

REM Elevate for winget machine install + firewall when possible.
net session >nul 2>&1
if errorlevel 1 (
  echo  Requesting Administrator ^(Python install + firewall^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0Install-Wims.ps1\" -RepoPath \"%REPO%\"'"
  set ERR=!ERRORLEVEL!
  REM After elevation, child already ran; show result in this window.
  echo.
  if exist "%HERE%\python-path.txt" (
    echo  Python path recorded:
    type "%HERE%\python-path.txt"
  )
  echo  If install succeeded: double-click Start-WimsServer.cmd
  echo.
  pause
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Wims.ps1" -RepoPath "%REPO%" %*
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
  echo  Install finished with errors ^(code %ERR%^).
  echo  If Python failed: re-run as Administrator, or install from https://www.python.org/downloads/
  echo  ^(check "Add python.exe to PATH"^), then run Install-Wims.cmd again.
) else (
  echo  Install finished.
  echo  Start WIMS: double-click Start-WimsServer.cmd
)
echo.
pause
exit /b %ERR%
