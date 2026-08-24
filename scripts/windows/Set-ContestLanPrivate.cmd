@echo off
setlocal EnableExtensions

REM Set connected Windows network(s) to Private so N1MM/WSJT firewall
REM allow-rules match. After a VM clone, Ethernet often comes up Public
REM and N1MM Send/Receive stays red even though other stations are visible.

cd /d "%~dp0"
set "HERE=%~dp0"
set "PS1=%~dp0Set-ContestLanPrivate.ps1"
set "PAUSE=1"
if /I "%~1"=="/nopause" set "PAUSE=0"
if /I "%~1"=="elevated" set "PAUSE=0"

if not exist "%PS1%" (
  echo  ERROR: Missing %PS1%
  if "%PAUSE%"=="1" pause
  exit /b 1
)

echo.
echo  WIMS — set contest LAN to Private
echo  =================================
echo  N1MM allow-rules apply on Private; Public blocks TCP 12070 send/receive.
echo.

net session >nul 2>&1
if errorlevel 1 (
  echo  Administrator required. A UAC prompt should appear - click Yes.
  echo.
  set "ELEV=%TEMP%\wims-elevate-lan-private.ps1"
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
  echo  Done. On N1MM Network Status, Send/Receive should go OK after a reconnect.
) else (
  echo  Failed ^(exit %RC%^). Run as Administrator and confirm Ethernet exists.
)
if "%PAUSE%"=="1" pause
exit /b %RC%
