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

REM Prefer pythonw.exe so no console flashes behind the GUI when available.
set "GUI_EXE=%PYTHON_EXE%"
if /I "%PYTHON_EXE%"=="py" goto :run
if /I "%PYTHON_EXE%"=="python" goto :run
set "CAND=%~dp0"
for %%I in ("%PYTHON_EXE%") do set "PYDIR=%%~dpI"
if exist "%PYDIR%pythonw.exe" set "GUI_EXE=%PYDIR%pythonw.exe"

:run
start "WIMS" "%GUI_EXE%" -m wims.launcher %*
exit /b 0
