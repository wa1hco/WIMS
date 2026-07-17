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
REM Seat agent — one-shot config check (default). NOT the site server.
REM For continuous dashboard reporting, use Start-WimsAgent-Continuous.cmd

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

REM Optional: set WIMS_SERVER to also push one report to the site dashboard
REM if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=%SEAT_ARGS% --agent-id %WIMS_AGENT_ID%"
set "SRV_ARGS="
if defined WIMS_SERVER set "SRV_ARGS=--server %WIMS_SERVER%"

echo.
echo  WIMS Agent — one-shot seat check
echo  Repo:   %ROOT%
echo  Python: %PYTHON_EXE%
if defined WIMS_SERVER (
  echo  Export: %WIMS_SERVER%
) else (
  echo  Export: ^(local only — set WIMS_SERVER to push to dashboard^)
)
echo.

REM Prefer scripts\run_agent.py (sets up src path). Falls back to -m with PYTHONPATH.
if exist "%ROOT%\scripts\run_agent.py" (
  "%PYTHON_EXE%" "%ROOT%\scripts\run_agent.py" %SRV_ARGS% %SEAT_ARGS% %*
) else (
  "%PYTHON_EXE%" -m wims.agent %SRV_ARGS% %SEAT_ARGS% %*
)
set ERR=%ERRORLEVEL%
echo.
if %ERR%==0 (
  echo  RESULT: OK
) else if %ERR%==1 (
  echo  RESULT: WSJT-X config ERROR^(s^) — see !! lines above ^(exit 1 is intentional^)
) else if %ERR%==2 (
  echo  RESULT: could not export to site server ^(exit 2^)
) else (
  echo  RESULT: failed ^(exit %ERR%^)
  echo  Tip: use this .cmd, or:  set PYTHONPATH=%ROOT%\src
  echo        python -m wims.agent
)
echo.
pause
exit /b %ERR%
