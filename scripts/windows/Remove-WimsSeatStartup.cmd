@echo off
setlocal EnableExtensions
REM Remove seat auto-start from this user's Startup folder.

set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS Seat.lnk"

echo.
echo  Remove WIMS seat auto-start
echo  ===========================
echo  Target: %LNK%
echo.

if exist "%LNK%" (
  del /F /Q "%LNK%"
  echo  Removed.
) else (
  echo  Not installed ^(no shortcut^).
)

echo.
pause
exit /b 0
