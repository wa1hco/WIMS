@echo off
REM Always start the 6 m (50 MHz) WSJT-X instance (tired-op safe).
REM Uses a separate named config from 144 MHz (WSJTX-144 / IC-9700).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"

set "WSJTX_EXE="
set "RIG=WSJTX-50"

if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
if exist "%HERE%radio-flex50.cmd" call "%HERE%radio-flex50.cmd"
call "%HERE%_resolve-wsjtx.cmd"
set "EXE=!WSJTX_EXE!"
if defined WSJTX_RIG_NAME set "RIG=!WSJTX_RIG_NAME!"

if not exist "%EXE%" (
  echo ERROR: WSJT-X not found: %EXE%
  pause
  exit /b 1
)
wmic process where "name='wsjtx.exe'" get CommandLine 2>nul | find /I "--rig-name=%RIG%" >nul
if not errorlevel 1 (
  echo WSJT-X %RIG% already running.
  exit /b 0
)
echo Starting WSJT-X --rig-name=%RIG%
echo Config: %LOCALAPPDATA%\WSJT-X - %RIG%\
start "WSJT-X %RIG%" "%EXE%" --rig-name=%RIG%
exit /b 0
