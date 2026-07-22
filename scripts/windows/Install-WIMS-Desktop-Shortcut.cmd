@echo off
setlocal EnableExtensions
REM Creates Desktop\WIMS.lnk -> WIMS.cmd menu (no paths to remember).

cd /d "%~dp0"
set "HERE=%~dp0"
set "MENU=%~dp0WIMS.cmd"
set "DESK=%USERPROFILE%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\OneDrive\Desktop"
set "LNK=%DESK%\WIMS.lnk"

if not exist "%MENU%" (
  echo ERROR: WIMS.cmd not found next to this script.
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = '%MENU%'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 1; $s.Description = 'WIMS Seat menu — check agent, start seat, open dashboards'; $s.Save(); Write-Host 'Created:' '%LNK%'"

if not exist "%LNK%" (
  echo ERROR: could not create Desktop shortcut
  if /I not "%~1"=="/nopause" pause
  exit /b 1
)

echo.
echo  Desktop shortcut ready: WIMS
echo  Double-click "WIMS" on the Desktop for the seat menu.
echo.
if /I not "%~1"=="/nopause" pause
exit /b 0
