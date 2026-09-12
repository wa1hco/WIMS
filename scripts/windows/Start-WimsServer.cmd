@echo off

REM WIMS - WSJT-X Instance Management System
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

REM Optional: prefer profile Databases when present.
REM Server also multi-scans UserDir/Documents. Override: set WIMS_SEED_DB_DIR=...
if not defined WIMS_SEED_DB_DIR (
  if exist "%USERPROFILE%\Databases\" set "WIMS_SEED_DB_DIR=%USERPROFILE%\Databases"
)

REM Optional GridTracker merge: set WIMS_GT_FORWARD=host:22370
REM GT Receive UDP = 22370; WIMS reverse defaults to 22371. See --gt-forward help.

REM Server picks the contest LAN for multicast joins; pass --iface if needed.
REM Extra args (lab only): %*
if defined WIMS_SEED_DB_DIR if defined WIMS_GT_FORWARD (
  "%PYTHON_EXE%" -m wims.server.app --iface 0.0.0.0 --n1mm-group 224.0.0.73 --http-port 8787 --seed-db-dir "%WIMS_SEED_DB_DIR%" --gt-forward %WIMS_GT_FORWARD% %*
) else if defined WIMS_SEED_DB_DIR (
  "%PYTHON_EXE%" -m wims.server.app --iface 0.0.0.0 --n1mm-group 224.0.0.73 --http-port 8787 --seed-db-dir "%WIMS_SEED_DB_DIR%" %*
) else if defined WIMS_GT_FORWARD (
  "%PYTHON_EXE%" -m wims.server.app --iface 0.0.0.0 --n1mm-group 224.0.0.73 --http-port 8787 --gt-forward %WIMS_GT_FORWARD% %*
) else (
  "%PYTHON_EXE%" -m wims.server.app --iface 0.0.0.0 --n1mm-group 224.0.0.73 --http-port 8787 %*
)
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
