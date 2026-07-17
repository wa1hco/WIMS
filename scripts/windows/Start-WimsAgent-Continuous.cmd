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

setlocal EnableExtensions
REM Seat agent — continuous mode for fleet seats / Startup folder.
REM Rescans and POSTs to the site server; local UI at http://127.0.0.1:8790/
REM Use Start-WimsAgent.cmd for a one-shot operator check that exits.

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"

echo.
echo  WIMS Agent — CONTINUOUS ^(reports to site server^)
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
echo  Local:  http://127.0.0.1:8790/
echo  Export: %WIMS_SERVER%  every ~30s
echo  Stop:   Ctrl+C
echo.

if exist "%ROOT%\scripts\run_agent.py" (
  "%PYTHON_EXE%" "%ROOT%\scripts\run_agent.py" --daemon --server "%WIMS_SERVER%" %SEAT_ARGS% %*
) else (
  "%PYTHON_EXE%" -m wims.agent --daemon --server "%WIMS_SERVER%" %SEAT_ARGS% %*
)
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  echo Exit %ERR%
  echo Tip: PYTHONPATH must include %ROOT%\src for "python -m wims.agent"
  pause
)
exit /b %ERR%
