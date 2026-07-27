@echo off
setlocal EnableExtensions
REM Desktop "WIMS Agent" shortcut for radio seats — continuous agent + local UI.
REM Icon: scripts\windows\assets\wims-agent.ico

cd /d "%~dp0"
set "HERE=%~dp0"
set "TARGET=%~dp0Start-WimsAgent-Continuous.cmd"
set "ICON=%~dp0assets\wims-agent.ico"
set "DESK=%USERPROFILE%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\OneDrive\Desktop"
set "LNK=%DESK%\WIMS Agent.lnk"

if not exist "%TARGET%" (
  echo ERROR: Start-WimsAgent-Continuous.cmd not found next to this script.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%LNK%'); " ^
  "$s.TargetPath = '%TARGET%'; " ^
  "$s.WorkingDirectory = '%HERE%'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Description = 'WIMS seat agent — reports config to site server; local UI http://127.0.0.1:8790/'; " ^
  "if (Test-Path -LiteralPath '%ICON%') { $s.IconLocation = '%ICON%,0' }; " ^
  "$s.Save(); Write-Host 'Created:' '%LNK%'"

if not exist "%LNK%" (
  echo ERROR: could not create Desktop shortcut
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

echo.
echo  Desktop shortcut ready: WIMS Agent
echo  Double-click to run the continuous seat agent.
echo  Local page: http://127.0.0.1:8790/
if exist "%ICON%" (echo  Icon:    assets\wims-agent.ico) else (echo  Icon:    ^(default — assets missing^))
echo.
if /I not "%~1"=="/nopause" pause
exit /b 0
