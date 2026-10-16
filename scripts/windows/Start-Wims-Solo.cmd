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

REM Home H0 Operate (single-PC): server on this machine alongside local WSJT-X + N1MM.
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
  echo Python was not found, so WIMS cannot start.
  echo Double-click Install-Wims.cmd in this folder, then try again.
  pause
  exit /b 1
)

REM 0 = port free. 11 = something is listening. Then 10 = that something is WIMS.
"%PYTHON_EXE%" -c "import socket,sys;s=socket.socket();s.settimeout(0.4);r=s.connect_ex(('127.0.0.1',8787));s.close();sys.exit(0 if r else 11)"
if errorlevel 11 (
  "%PYTHON_EXE%" -c "import json,sys,urllib.request;d={};exec('try:\n d=json.loads(urllib.request.urlopen(\'http://127.0.0.1:8787/healthz\',timeout=0.8).read().decode())\nexcept Exception:\n pass');sys.exit(10 if d.get('ok') and d.get('role')=='wims-site-server' else 11)"
)
set PROBE=%ERRORLEVEL%
if "%PROBE%"=="10" (
  echo WIMS is already open. Showing the console.
  start "" "http://localhost:8787/"
  exit /b 0
)
if "%PROBE%"=="11" (
  echo Port 8787 is in use, but it is not WIMS.
  echo Close the other program, or use the WIMS window if it is already open.
  echo The console, when WIMS is up, is http://localhost:8787/
  pause
  exit /b 1
)

echo.
echo  WIMS home Operate (H0): %ROOT%
echo  Console:   http://localhost:8787/
echo.

"%PYTHON_EXE%" -m wims.solo %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
