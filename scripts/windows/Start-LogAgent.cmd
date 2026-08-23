@echo off
REM Test log agent — run on the N1MM PC (e.g. wims-test-50).
REM Joins 224.0.0.73:2237, forwards this-band Logged QSO to 127.0.0.1:2333.
REM N1MM WSJT UDP reader on 2237 must be OFF.

setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"
if not defined PYTHON_EXE (
  echo No Python. Run Install-Wims.cmd first.
  pause
  exit /b 1
)

echo.
echo  WIMS test log agent
echo  ===================
echo  Host: %COMPUTERNAME%
echo  Pin:  trailing -50/-144/… on hostname, or pass --band 6m
echo  N1MM: 127.0.0.1:2333
echo.

REM First arg --dry-run prints only. Extra args passed through.
"%PYTHON_EXE%" "%ROOT%\testbed\log_agent.py" %*
if errorlevel 1 pause
