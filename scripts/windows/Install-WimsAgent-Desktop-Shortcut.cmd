@echo off
setlocal EnableExtensions
REM Desktop "WIMS Agent" shortcut — sticky green icon via wscript + VBS.

cd /d "%~dp0"
set "HERE=%~dp0"
set "VBS=%~dp0Start-WimsAgent-Continuous.vbs"
set "TARGET=%~dp0Start-WimsAgent-Continuous.cmd"
set "ICON=%~dp0assets\wims-agent.ico"
set "WSCRIPT=%SystemRoot%\System32\wscript.exe"
set "DESK=%USERPROFILE%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\OneDrive\Desktop"
set "LNK=%DESK%\WIMS Agent.lnk"

if not exist "%TARGET%" (
  echo ERROR: Start-WimsAgent-Continuous.cmd not found next to this script.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)
if not exist "%VBS%" (
  echo ERROR: Start-WimsAgent-Continuous.vbs missing — pull latest WIMS.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)
if not exist "%ICON%" (
  echo ERROR: assets\wims-agent.ico missing — pull latest WIMS.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$wscript = '%WSCRIPT%'; " ^
  "$vbs = (Resolve-Path -LiteralPath '%VBS%').Path; " ^
  "$ico = (Resolve-Path -LiteralPath '%ICON%').Path; " ^
  "$lnk = '%LNK%'; " ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut($lnk); " ^
  "$s.TargetPath = $wscript; " ^
  "$s.Arguments = '//nologo \"' + $vbs + '\"'; " ^
  "$s.WorkingDirectory = '%HERE%'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Description = 'WIMS seat agent — local UI http://127.0.0.1:8790/'; " ^
  "$s.IconLocation = $ico + ',0'; " ^
  "$s.Save(); " ^
  "Write-Host 'Created:' $lnk; Write-Host 'Icon:' $ico"

if not exist "%LNK%" (
  echo ERROR: could not create Desktop shortcut
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

echo.
echo  Desktop shortcut ready: WIMS Agent
echo  Double-click to run the continuous seat agent.
echo  Local page: http://127.0.0.1:8790/
echo  Icon: assets\wims-agent.ico
echo.
if /I not "%~1"=="/nopause" pause
exit /b 0
