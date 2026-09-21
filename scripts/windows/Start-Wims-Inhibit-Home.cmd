@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM This program is free software: you can redistribute it and/or modify
REM it under the terms of the GNU General Public License as published by
REM the Free Software Foundation, either version 3 of the License, or
REM (at your option) any later version.
REM
REM This program is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
REM GNU General Public License for more details.
REM
REM You should have received a copy of the GNU General Public License
REM along with this program.  If not, see <https://www.gnu.org/licenses/>.

REM Home H1 Inhibit: KEY → localhost digi gate (no site server, no RadioInfo band).
REM Needs patched WSJT-X TxInhibit on UDP 22372. Set WIMS_KEY_DEVICE to COM port
REM (or sim:up for lab). See docs\home_h0_h1.md.

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

if "%WIMS_KEY_TARGETS%"=="" set "WIMS_KEY_TARGETS=127.0.0.1:22372"

echo.
echo  WIMS home Inhibit (H1): %ROOT%
echo  Targets: %WIMS_KEY_TARGETS%
if defined WIMS_KEY_DEVICE (
  echo  Device:  %WIMS_KEY_DEVICE%
) else (
  echo  Device:  ^(not set — set WIMS_KEY_DEVICE=COMx or use launcher KEY combobox^)
)
echo  Docs:    docs\home_h0_h1.md
echo.

"%PYTHON_EXE%" -m wims.seat --key --targets "%WIMS_KEY_TARGETS%" %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
