@echo off
setlocal EnableExtensions
REM Register seat apps to start at logon (user Startup folder — no admin required).
REM This PC already auto-logs in as W2SZ; Startup runs after desktop is ready.

cd /d "%~dp0"
set "HERE=%~dp0"
set "SEAT=%~dp0Start-WimsSeat.cmd"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\WIMS Seat.lnk"

if not exist "%SEAT%" (
  echo ERROR: missing Start-WimsSeat.cmd
  pause
  exit /b 1
)

if not exist "%STARTUP%" mkdir "%STARTUP%" 2>nul

echo.
echo  Install WIMS seat auto-start
echo  ============================
echo  Launcher: %SEAT%
echo  Startup:  %LNK%
echo.

if not exist "%HERE%seat-local.cmd" (
  if exist "%HERE%seat-config.example.cmd" (
    copy /Y "%HERE%seat-config.example.cmd" "%HERE%seat-local.cmd" >nul
    echo  Created seat-local.cmd from example — edit paths/seat id if needed.
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = '%SEAT%'; $s.Arguments = '/silent'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 7; $s.Description = 'Start N1MM, WSJT-X, WIMS agent at logon'; $s.Save(); Write-Host 'Shortcut written.'"

if not exist "%LNK%" (
  echo ERROR: could not create Startup shortcut
  pause
  exit /b 1
)

echo.
echo  RESULT: OK — at next logon this user will run Start-WimsSeat.cmd
echo  Edit:   %HERE%seat-local.cmd
echo  Remove: double-click Remove-WimsSeatStartup.cmd
echo  Test now: double-click Start-WimsSeat.cmd
echo.
pause
exit /b 0
