@echo off
setlocal EnableExtensions
REM Desktop "WIMS" shortcut -> GUI launcher (peer to N1MM / WSJT-X).
REM Uses assets\wims.ico when present.

cd /d "%~dp0"
set "HERE=%~dp0"
set "TARGET=%~dp0Start-WimsLauncher.cmd"
set "ICON=%~dp0assets\wims.ico"
set "DESK=%USERPROFILE%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\OneDrive\Desktop"
set "LNK=%DESK%\WIMS.lnk"

if not exist "%TARGET%" (
  echo ERROR: Start-WimsLauncher.cmd not found next to this script.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%LNK%'); " ^
  "$s.TargetPath = '%TARGET%'; " ^
  "$s.WorkingDirectory = '%HERE%'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Description = 'WIMS — start Solo console, site server, or seat agent'; " ^
  "if (Test-Path -LiteralPath '%ICON%') { $s.IconLocation = '%ICON%,0' }; " ^
  "$s.Save(); Write-Host 'Created:' '%LNK%'"

if not exist "%LNK%" (
  echo ERROR: could not create Desktop shortcut
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

echo.
echo  Desktop shortcut ready: WIMS
echo  Double-click "WIMS" on the Desktop for the GUI launcher.
if exist "%ICON%" (echo  Icon: assets\wims.ico)
echo.
REM Also offer the dedicated agent launcher (stations often only need the agent).
if exist "%HERE%Install-WimsAgent-Desktop-Shortcut.cmd" (
  call "%HERE%Install-WimsAgent-Desktop-Shortcut.cmd" /nopause
)
if /I not "%~1"=="/nopause" pause
exit /b 0
