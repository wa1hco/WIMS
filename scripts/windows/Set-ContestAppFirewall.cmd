@echo off
setlocal EnableExtensions

REM Windows Firewall allow-rules for N1MM, WSJT-X, GridTracker, WIMS
REM on the Private profile. Keep the firewall ON. Ethernet must be Private.
REM This .cmd only launches the .ps1; the .ps1 handles UAC itself.

cd /d "%~dp0"
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
echo  WIMS - contest app firewall (Private)
echo  =====================================
echo  N1MM, WSJT-X, GridTracker, WIMS inbound allow on Private only.
echo  Click YES on UAC. Watch the new PowerShell window for [OK] lines.
echo.

REM Do not pass /nopause through; the .ps1 self-elevates unless already admin.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  Done. Restart N1MM / WSJT-X if Send/Receive or Work-click still fails.
) else (
  echo  Failed ^(exit %RC%^). Click Yes on UAC, or Run as administrator.
)
if "%PAUSE%"=="1" pause
exit /b %RC%
