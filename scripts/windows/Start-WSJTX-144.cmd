@echo off
REM Always start the 2 m (144 MHz) WSJT-X instance (tired-op safe).
REM Uses a separate named config from 50 MHz (WSJTX-50 / Flex).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"

set "EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
set "RIG=WSJTX-144"

if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
if exist "%HERE%radio-ic9700-144.cmd" call "%HERE%radio-ic9700-144.cmd"
if defined WSJTX_EXE set "EXE=!WSJTX_EXE!"
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
