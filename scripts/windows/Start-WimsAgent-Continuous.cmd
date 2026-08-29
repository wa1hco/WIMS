@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later

setlocal EnableExtensions
REM Seat agent — continuous mode for fleet seats / Startup folder.
REM Local UI: http://127.0.0.1:8790/   Site console: %WIMS_SERVER%/
REM Use Start-WimsAgent.cmd for a one-shot check that exits.

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

if exist "%~dp0seat-common.cmd" call "%~dp0seat-common.cmd"
if not exist "%~dp0seat-common.cmd" if exist "%~dp0seat-local.cmd" call "%~dp0seat-local.cmd"
if not defined WIMS_SEAT_ID (
  if /I "%SEAT_DEFAULT_RADIO%"=="ic9700-144" (
    if exist "%~dp0radio-ic9700-144.cmd" call "%~dp0radio-ic9700-144.cmd"
  ) else (
    if exist "%~dp0radio-flex50.cmd" call "%~dp0radio-flex50.cmd"
  )
)

if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"

REM Prefer console python.exe (not pythonw) so bind errors are visible.
for %%I in ("%PYTHON_EXE%") do set "PYDIR=%%~dpI"
if exist "%PYDIR%python.exe" set "PYTHON_EXE=%PYDIR%python.exe"

echo.
echo  WIMS Agent — CONTINUOUS (station seat)
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
echo  Local:  http://127.0.0.1:8790/
echo  Site:   %WIMS_SERVER%/
echo  Stop:   close the minimized "WIMS Agent" window
echo.

start "WIMS Agent" /MIN /D "%ROOT%" "%PYTHON_EXE%" -u -m wims.agent --daemon --local-port 8790 --server "%WIMS_SERVER%" %SEAT_ARGS% %*

REM Wait up to ~25s for 8790 (avoids Chrome "Unable to connect" race).
set /a _n=0
:wait8790
netstat -ano 2>nul | findstr /R /C:":8790 .*LISTENING" >nul
if not errorlevel 1 goto open8790
set /a _n+=1
if %_n% GEQ 50 (
  echo.
  echo  ERROR: nothing listening on 127.0.0.1:8790 after ~25s.
  echo  Open the minimized "WIMS Agent" window for a Python traceback.
  echo  Then on this VM:  git pull
  echo  Confirm: set PYTHONPATH=%ROOT%\src
  pause
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto wait8790

:open8790
echo  Port 8790 is LISTENING — opening browser.
if /I not "%WIMS_AGENT_NO_BROWSER%"=="1" (
  start "" "http://127.0.0.1:8790/"
)
pause
exit /b 0
