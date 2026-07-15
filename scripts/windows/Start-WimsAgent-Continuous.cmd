@echo off
setlocal EnableExtensions
REM Seat agent — continuous mode for fleet seats / Startup folder.
REM Rescans and POSTs to the site server; local UI at http://127.0.0.1:8790/
REM Use Start-WimsAgent.cmd for a one-shot operator check that exits.

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"

echo.
echo  WIMS Agent — CONTINUOUS ^(reports to site server^)
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
echo  Local:  http://127.0.0.1:8790/
echo  Export: %WIMS_SERVER%  every ~30s
echo  Stop:   Ctrl+C
echo.

"%PYTHON_EXE%" -m wims.agent --daemon --server "%WIMS_SERVER%" %SEAT_ARGS% %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
