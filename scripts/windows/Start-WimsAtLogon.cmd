@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Logon: start WSJT-X / N1MM / WIMS from saved seat intent
REM (%APPDATA%\wims\seat_intent.json). Use /silent from Startup.

setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || exit /b 1
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"
if not exist "%PYTHON_EXE%" if /I not "%PYTHON_EXE%"=="py" if /I not "%PYTHON_EXE%"=="python" (
  exit /b 1
)

if exist "%~dp0seat-common.cmd" call "%~dp0seat-common.cmd"
if exist "%~dp0seat-local.cmd" call "%~dp0seat-local.cmd"

set "MODE="
if /I "%~1"=="/silent" set "MODE=--logon"
if /I "%~1"=="--logon" set "MODE=--logon"
if /I "%~1"=="--dry-run" set "MODE=--dry-run"

"%PYTHON_EXE%" -m wims.launcher.boot %MODE%
exit /b %ERRORLEVEL%
