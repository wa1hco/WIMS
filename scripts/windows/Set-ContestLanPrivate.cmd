@echo off
setlocal EnableExtensions

REM Set connected Windows network(s) to Private so N1MM/WSJT firewall
REM allow-rules match. After a VM clone, Ethernet often comes up Public
REM and N1MM Send/Receive stays red even though other stations are visible.
REM This .cmd only launches the .ps1; the .ps1 handles UAC itself.

cd /d "%~dp0"
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
echo  WIMS - set contest LAN to Private
echo  =================================
echo  N1MM allow-rules apply on Private; Public blocks TCP 12070 send/receive.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  Done. On N1MM Network Status, Send/Receive should go OK after a reconnect.
) else (
  echo  Failed ^(exit %RC%^). Click Yes on UAC, or Run as administrator.
)
if "%PAUSE%"=="1" pause
exit /b %RC%
