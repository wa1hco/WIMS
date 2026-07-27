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

setlocal EnableExtensions EnableDelayedExpansion
REM Start contest seat apps after auto-logon: wfview first (CAT), then N1MM / WSJT-X
REM if needed, always refresh agent. Does NOT start the site WIMS server.
REM
REM Order: wfview → delay → N1MM → delay → WSJT-X → agent
REM   wfview owns radio COM and must be up (RigCtld/TCP) before N1MM/WSJT-X CAT.
REM
REM wfview + N1MM + WSJT-X: start only if not already running (no force-kill —
REM avoids blank WSJT dialogs and mid-log disruption).
REM Agent: kill any existing wims.agent then start fresh (dev-friendly).
REM
REM Paths may contain parentheses (Program Files (x86)). Use delayed expansion !VAR!.

cd /d "%~dp0"
set "HERE=%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul
if errorlevel 1 (
  echo Bad repo root
  pause
  exit /b 1
)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

set "WIMS_SERVER=http://192.168.1.119:8787"
set "WIMS_SEAT_ID="
set "START_WFVIEW=1"
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"
REM Kill only the WIMS agent before restart (not wfview/N1MM/WSJT-X)
set "START_AGENT_RESTART=1"
set "WFVIEW_EXE=C:\Program Files\wfview\wfview.exe"
set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
REM Overridden by seat-local.cmd — must be non-empty or WSJT-X is refused.
set "WSJTX_RIG_NAME="
set "START_DELAY_SEC=5"
set "AGENT_INTERVAL=30"

if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not exist "%HERE%seat-local.cmd" if exist "%HERE%seat-config.example.cmd" call "%HERE%seat-config.example.cmd"

set "LOG=%HERE%seat-startup-log.txt"
echo [%DATE% %TIME%] Start-WimsSeat begin > "%LOG%"
echo Repo=%ROOT%>> "%LOG%"
echo Server=%WIMS_SERVER% seat=%WIMS_SEAT_ID% agent_restart=!START_AGENT_RESTART!>> "%LOG%"

echo.
echo  WIMS seat startup
echo  =================
echo  Repo:   %ROOT%
echo  Server: %WIMS_SERVER%
if defined WIMS_SEAT_ID echo  Seat:   %WIMS_SEAT_ID%
echo  Apps:   wfview/N1MM/WSJT-X start if missing; agent restart=!START_AGENT_RESTART!
echo  Log:    %LOG%
echo.

if "!START_DELAY_SEC!"=="" set "START_DELAY_SEC=5"

REM ---- wfview FIRST: owns radio COM; RigCtld/TCP must be up before N1MM/WSJT CAT ----
if not "!START_WFVIEW!"=="1" goto skip_wfview
if not exist "!WFVIEW_EXE!" goto wfview_missing
tasklist /FI "IMAGENAME eq wfview.exe" 2>nul | find /I "wfview.exe" >nul
if not errorlevel 1 goto wfview_running
echo  Starting wfview...
start "wfview" "!WFVIEW_EXE!"
echo started wfview>> "%LOG%"
goto after_wfview_start

:wfview_missing
echo  WARN: wfview not found: !WFVIEW_EXE!
echo wfview missing>> "%LOG%"
goto after_wfview

:wfview_running
echo  wfview already running - leave it
echo wfview already running>> "%LOG%"
goto after_wfview

:skip_wfview
echo  Skip wfview START_WFVIEW=0
echo skip wfview>> "%LOG%"
goto after_wfview

:after_wfview_start
echo  Waiting !START_DELAY_SEC!s for wfview / RigCtld...
set /a _PING_N=!START_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul

:after_wfview
REM ---- N1MM: start only if not running ----
if not "!START_N1MM!"=="1" goto skip_n1mm
if not exist "!N1MM_EXE!" goto n1mm_missing
tasklist /FI "IMAGENAME eq N1MMLogger.net.exe" 2>nul | find /I "N1MMLogger.net.exe" >nul
if not errorlevel 1 goto n1mm_running
echo  Starting N1MM...
start "N1MM" /MIN "!N1MM_EXE!"
echo started N1MM>> "%LOG%"
goto after_n1mm

:n1mm_missing
echo  WARN: N1MM not found: !N1MM_EXE!
echo N1MM missing>> "%LOG%"
goto after_n1mm

:n1mm_running
echo  N1MM already running - leave it
echo N1MM already running>> "%LOG%"
goto after_n1mm

:skip_n1mm
echo  Skip N1MM START_N1MM=0
echo skip N1MM>> "%LOG%"

:after_n1mm
echo  Waiting !START_DELAY_SEC!s...
set /a _PING_N=!START_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul

REM ---- WSJT-X: ALWAYS require --rig-name; replace bare (no rig-name) instances ----
if not "!START_WSJTX!"=="1" goto skip_wsjtx
if not exist "!WSJTX_EXE!" goto wsjtx_missing
if not defined WSJTX_RIG_NAME goto wsjtx_no_rig
if "!WSJTX_RIG_NAME!"=="" goto wsjtx_no_rig

REM If any wsjtx is running WITHOUT our --rig-name, stop it so we do not keep a default id.
set "WSJTX_HAS_NAMED="
set "WSJTX_HAS_ANY="
for /f "skip=1 tokens=*" %%L in ('wmic process where "name='wsjtx.exe'" get CommandLine /value 2^>nul') do (
  set "CL=%%L"
  if /I "!CL:~0,12!"=="CommandLine=" (
    set "WSJTX_HAS_ANY=1"
    echo !CL! | find /I "--rig-name=!WSJTX_RIG_NAME!" >nul
    if not errorlevel 1 set "WSJTX_HAS_NAMED=1"
  )
)
if defined WSJTX_HAS_NAMED goto wsjtx_running
if defined WSJTX_HAS_ANY (
  echo  WSJT-X running without --rig-name=!WSJTX_RIG_NAME! — restarting correctly...
  taskkill /IM jt9.exe /F >nul 2>&1
  taskkill /IM wsjtx.exe /F >nul 2>&1
  ping -n 2 127.0.0.1 >nul
  echo killed bare/wrong WSJTX>> "%LOG%"
)

echo  Starting WSJT-X --rig-name=!WSJTX_RIG_NAME!...
start "WSJTX" "!WSJTX_EXE!" --rig-name=!WSJTX_RIG_NAME!
echo started WSJTX rig=!WSJTX_RIG_NAME!>> "%LOG%"
goto after_wsjtx

:wsjtx_no_rig
echo  ERROR: WSJTX_RIG_NAME is empty — refusing to start WSJT-X without --rig-name.
echo  Set it in seat-local.cmd ^(e.g. set "WSJTX_RIG_NAME=W10VM-50"^).
echo WSJTX refused: empty WSJTX_RIG_NAME>> "%LOG%"
goto after_wsjtx

:wsjtx_missing
echo  WARN: WSJT-X not found: !WSJTX_EXE!
echo WSJTX missing>> "%LOG%"
goto after_wsjtx

:wsjtx_running
echo  WSJT-X already running with --rig-name=!WSJTX_RIG_NAME!
echo WSJTX already running named>> "%LOG%"
goto after_wsjtx

:skip_wsjtx
echo  Skip WSJT-X START_WSJTX=0
echo skip WSJTX>> "%LOG%"

:after_wsjtx
ping -n 3 127.0.0.1 >nul

REM ---- Agent: optional kill, then start ----
if not "!START_AGENT!"=="1" goto skip_agent
if not exist "%HERE%Start-WimsAgent-Continuous.cmd" goto agent_missing

if not "!START_AGENT_RESTART!"=="1" goto agent_maybe_running

echo  Restarting WIMS agent...
for /f "skip=1 tokens=1" %%P in ('wmic process where "CommandLine like '%%wims.agent%%'" get ProcessId 2^>nul') do (
  if not "%%P"=="" if not "%%P"=="ProcessId" (
    echo    kill wims.agent PID %%P
    taskkill /PID %%P /F >nul 2>&1
    echo killed agent %%P>> "%LOG%"
  )
)
REM Free port 8790 if a dead listener remains
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /R /C:":8790 .*LISTENING"') do (
  if not "%%P"=="0" (
    taskkill /PID %%P /F >nul 2>&1
    echo killed port8790 %%P>> "%LOG%"
  )
)
ping -n 2 127.0.0.1 >nul
goto agent_start

:agent_maybe_running
wmic process where "CommandLine like '%%wims.agent%%'" get ProcessId 2>nul | findstr /R "[0-9]" >nul
if not errorlevel 1 goto agent_already
netstat -ano 2>nul | findstr /R /C:":8790 .*LISTENING" >nul
if not errorlevel 1 goto agent_port_busy

:agent_start
echo  Starting WIMS agent continuous - UI http://127.0.0.1:8790/
start "WIMS Agent" /MIN cmd /c call "%HERE%Start-WimsAgent-Continuous.cmd"
echo started agent>> "%LOG%"
goto after_agent

:agent_already
echo  WIMS agent already running - OK
echo  Local UI: http://127.0.0.1:8790/
echo agent already running>> "%LOG%"
goto after_agent

:agent_port_busy
echo  WARN: port 8790 in use but no wims.agent found
echo  Set START_AGENT_RESTART=1 in seat-local.cmd to free it.
echo agent port busy>> "%LOG%"
goto after_agent

:agent_missing
echo  WARN: missing Start-WimsAgent-Continuous.cmd
echo agent launcher missing>> "%LOG%"
goto after_agent

:skip_agent
echo  Skip agent START_AGENT=0
echo skip agent>> "%LOG%"

:after_agent
echo.
echo  Seat startup finished.
echo  Agent UI: http://127.0.0.1:8790/
echo  Full log: %LOG%
echo [%DATE% %TIME%] Start-WimsSeat done>> "%LOG%"

if /I "%~1"=="/silent" exit /b 0
ping -n 6 127.0.0.1 >nul
exit /b 0
