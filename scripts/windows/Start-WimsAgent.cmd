@echo off
setlocal EnableExtensions
REM Seat agent only — NOT the site server. Local UI + optional export to wrangler.

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

REM Prefer pinned interpreter from full install, else py/python on PATH
set "PYTHON_EXE="
if exist "%~dp0python-path.txt" (
  set /p PYTHON_EXE=<"%~dp0python-path.txt"
)
if not defined PYTHON_EXE set "PYTHON_EXE=py"
where %PYTHON_EXE% >nul 2>&1
if errorlevel 1 set "PYTHON_EXE=python"

REM Site server for export (override before launch or set system env WIMS_SERVER)
if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

REM Optional seat label: set WIMS_SEAT_ID=ROY-222
set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"

echo.
echo  WIMS Agent (station PC)
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
echo  Local:  http://127.0.0.1:8790/
echo  Export: %WIMS_SERVER%
echo.

"%PYTHON_EXE%" -m wims.agent --server "%WIMS_SERVER%" %SEAT_ARGS% %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
