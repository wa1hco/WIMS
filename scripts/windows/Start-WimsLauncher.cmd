@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later

REM Desktop peer launcher (GUI). Double-click or use Desktop "WIMS" shortcut.

setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"
if not exist "%PYTHON_EXE%" if /I not "%PYTHON_EXE%"=="py" if /I not "%PYTHON_EXE%"=="python" (
  echo Python missing. Run Install-Wims.cmd again.
  pause
  exit /b 1
)

REM Seat defaults (site server URL) before GUI — same as other seat scripts.
if exist "%~dp0seat-common.cmd" call "%~dp0seat-common.cmd"
if exist "%~dp0seat-local.cmd" call "%~dp0seat-local.cmd"
if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

REM Prefer pythonw.exe for the GUI only (no console flash). Child roles use python.exe.
set "GUI_EXE=%PYTHON_EXE%"
if /I "%PYTHON_EXE%"=="py" goto :run
if /I "%PYTHON_EXE%"=="python" goto :run
for %%I in ("%PYTHON_EXE%") do set "PYDIR=%%~dpI"
if exist "%PYDIR%pythonw.exe" set "GUI_EXE=%PYDIR%pythonw.exe"

:run
echo  WIMS launcher
echo  Site server URL: %WIMS_SERVER%
echo  Seat monitor UI will be http://127.0.0.1:8790/ on THIS PC
echo  Site Operate/Status is %WIMS_SERVER%/  — not localhost unless server is here
echo.
start "WIMS" "%GUI_EXE%" -m wims.launcher %*
exit /b 0
