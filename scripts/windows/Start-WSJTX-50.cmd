@echo off
REM Always start the 6 m (50 MHz) WSJT-X instance (tired-op safe).
setlocal
set "EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
set "RIG=WSJTX-50"
if not exist "%EXE%" (
  echo ERROR: WSJT-X not found: %EXE%
  pause
  exit /b 1
)
wmic process where "name='wsjtx.exe'" get CommandLine 2>nul | find /I "--rig-name=WSJTX-50" >nul
if not errorlevel 1 (
  echo WSJT-X WSJTX-50 already running.
  exit /b 0
)
start "WSJT-X WSJTX-50" "%EXE%" --rig-name=%RIG%
exit /b 0