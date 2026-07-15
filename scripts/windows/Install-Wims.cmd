@echo off
setlocal EnableExtensions
REM Double-click install. Elevates for machine Python + firewall.
REM Always pass real repo path. Results in install-log.txt next to this file.

cd /d "%~dp0"
set "HERE=%~dp0"
set "PS1=%~dp0Install-Wims.ps1"
for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
set "LOG=%~dp0install-log.txt"

echo.
echo  WIMS Windows install
echo  ====================
echo  Repo: %REPO%
echo  Script: %PS1%
echo.

if not exist "%REPO%\src\wims\server\app.py" (
  echo  ERROR: Not a full WIMS checkout:
  echo    %REPO%
  echo  git clone https://github.com/wa1hco/WIMS.git
  echo.
  pause
  exit /b 1
)

if not exist "%PS1%" (
  echo  ERROR: Missing Install-Wims.ps1 next to this .cmd
  pause
  exit /b 1
)

net session >nul 2>&1
if errorlevel 1 (
  echo  Need Administrator for Python ^(all users^) and firewall.
  echo  Accept the UAC prompt...
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%PS1%','-RepoPath','%REPO%'"
) else (
  echo  Already Administrator — installing...
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -RepoPath "%REPO%" %*
)

echo.
echo  ---------- install-log.txt ^(tail^) ----------
if exist "%LOG%" (
  powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 50"
) else (
  echo  No log file — UAC may have been cancelled, or script failed to start.
)
echo  --------------------------------------------
echo.

if exist "%~dp0python-path.txt" (
  echo  python-path.txt:
  type "%~dp0python-path.txt"
  echo.
)

if exist "%LOG%" (
  findstr /C:"SUCCESS" "%LOG%" >nul 2>&1
  if not errorlevel 1 (
    echo  RESULT: SUCCESS
    echo  Next: double-click Start-WimsServer.cmd
    goto :end
  )
)

echo  RESULT: NOT SUCCESSFUL
echo  Read FAIL lines in install-log.txt above.
echo  Fix: right-click Install-Wims.cmd -^> Run as administrator
echo  Or install Python from https://www.python.org/downloads/ with
echo  "Add python.exe to PATH", then run this again.

:end
echo.
pause
exit /b 0
