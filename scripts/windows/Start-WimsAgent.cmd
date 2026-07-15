@echo off
setlocal EnableExtensions
REM Seat agent — one-shot config check (default). NOT the site server.
REM For continuous dashboard reporting, use Start-WimsAgent-Continuous.cmd

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

REM Optional: set WIMS_SERVER to also push one report to the site dashboard
REM if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"
set "SRV_ARGS="
if defined WIMS_SERVER set "SRV_ARGS=--server %WIMS_SERVER%"

echo.
echo  WIMS Agent — one-shot seat check
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
if defined WIMS_SERVER (
  echo  Export: %WIMS_SERVER%
) else (
  echo  Export: ^(local only — set WIMS_SERVER to push to dashboard^)
)
echo.

"%PYTHON_EXE%" -m wims.agent %SRV_ARGS% %SEAT_ARGS% %*
set ERR=%ERRORLEVEL%
echo.
if %ERR%==0 (
  echo  RESULT: OK
) else (
  echo  RESULT: problems found ^(exit %ERR%^)
)
echo.
pause
exit /b %ERR%
