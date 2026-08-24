@echo off
setlocal EnableExtensions

REM Windows Firewall allow-rules for N1MM, WSJT-X, GridTracker, WIMS
REM on the Private profile. Keep the firewall ON. Ethernet must be Private.

cd /d "%~dp0"
set "HERE=%~dp0"
set "PS1=%~dp0Set-ContestAppFirewall.ps1"
set "PAUSE=1"
if /I "%~1"=="/nopause" set "PAUSE=0"
if /I "%~1"=="elevated" set "PAUSE=0"

if not exist "%PS1%" (
  echo  ERROR: Missing %PS1%
  if "%PAUSE%"=="1" pause
  exit /b 1
)

echo.
echo  WIMS — contest app firewall (Private)
echo  =====================================
echo  N1MM, WSJT-X, GridTracker, WIMS inbound allow on Private only.
echo.

net session >nul 2>&1
if errorlevel 1 (
  echo  Administrator required. A UAC prompt should appear - click Yes.
  echo.
  set "ELEV=%TEMP%\wims-elevate-app-fw.ps1"
  > "%ELEV%" echo $ErrorActionPreference = 'Stop'
  >>"%ELEV%" echo $cmd = '%ComSpec%'
  >>"%ELEV%" echo $bat = '%~f0'
  >>"%ELEV%" echo $p = Start-Process -FilePath $cmd -Verb RunAs -Wait -PassThru -ArgumentList @('/c','"'+$bat+' elevated"')
  >>"%ELEV%" echo exit $p.ExitCode
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ELEV%"
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -NoElevate
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  Done. Restart N1MM / WSJT-X if Send/Receive or Work-click still fails.
) else (
  echo  Failed ^(exit %RC%^). Run as Administrator.
)
if "%PAUSE%"=="1" pause
exit /b %RC%
