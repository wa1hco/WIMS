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

REM Solo single-PC WIMS: server on this machine alongside local WSJT-X + N1MM.
REM In WSJT-X: Settings -> Reporting -> UDP Server 224.0.0.73 : 2237, Accept UDP requests ON.

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

echo.
echo  WIMS solo: %ROOT%
echo  Console:   http://localhost:8787/
echo.

"%PYTHON_EXE%" -m wims.solo %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
