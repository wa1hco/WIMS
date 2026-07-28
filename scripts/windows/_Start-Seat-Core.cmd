@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Shared seat start engine. Called by radio-specific launchers:
REM   Start-Seat-Flex50.cmd        → RADIO_STACK=smartsdr
REM   Start-Seat-IC9700-144.cmd    → RADIO_STACK=wfview
REM
REM Expects (set by caller after loading config):
REM   RADIO_STACK   smartsdr | wfview
REM   SEAT_LABEL    human label for log/UI (e.g. Flex-50, IC9700-144)
REM   WSJTX_RIG_NAME  required unique --rig-name
REM Optional: START_N1MM, START_WSJTX, START_AGENT, paths, delays, LOG override.
REM
REM Paths may contain parentheses. Requires EnableDelayedExpansion from caller
REM or we re-enable it here.

setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "HERE=%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul
if errorlevel 1 (
  echo Bad repo root
  if /I not "%~1"=="/silent" pause
  exit /b 1
)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

if "!RADIO_STACK!"=="" (
  echo ERROR: RADIO_STACK not set — call Start-Seat-Flex50.cmd or Start-Seat-IC9700-144.cmd
  if /I not "%~1"=="/silent" pause
  exit /b 2
)
if /I not "!RADIO_STACK!"=="smartsdr" if /I not "!RADIO_STACK!"=="wfview" (
  echo ERROR: RADIO_STACK must be smartsdr or wfview ^(got !RADIO_STACK!^)
  if /I not "%~1"=="/silent" pause
  exit /b 2
)

if "!SEAT_LABEL!"=="" set "SEAT_LABEL=!RADIO_STACK!"
if "!START_N1MM!"=="" set "START_N1MM=1"
if "!START_WSJTX!"=="" set "START_WSJTX=1"
if "!START_AGENT!"=="" set "START_AGENT=1"
if "!START_AGENT_RESTART!"=="" set "START_AGENT_RESTART=1"
if "!START_SMARTSDR_CAT!"=="" set "START_SMARTSDR_CAT=1"
if "!START_SMARTSDR_DAX!"=="" set "START_SMARTSDR_DAX=1"
if "!START_DELAY_SEC!"=="" set "START_DELAY_SEC=5"
if "!SMARTSDR_DELAY_SEC!"=="" set "SMARTSDR_DELAY_SEC=15"
if "!WFVIEW_DELAY_SEC!"=="" set "WFVIEW_DELAY_SEC=!START_DELAY_SEC!"
if "!N1MM_EXE!"=="" set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
if "!WSJTX_EXE!"=="" set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
if "!WFVIEW_EXE!"=="" set "WFVIEW_EXE=C:\Program Files\wfview\wfview.exe"
if "!SMARTSDR_DIR!"=="" set "SMARTSDR_DIR=C:\Program Files\SmartSDR v4.2.20"
if "!SMARTSDR_EXE!"=="" if not "!SMARTSDR_DIR!"=="" set "SMARTSDR_EXE=!SMARTSDR_DIR!\SmartSDR.exe"
if "!SMARTSDR_CAT_EXE!"=="" if not "!SMARTSDR_DIR!"=="" set "SMARTSDR_CAT_EXE=!SMARTSDR_DIR!\CAT.exe"
if "!SMARTSDR_DAX_EXE!"=="" if not "!SMARTSDR_DIR!"=="" set "SMARTSDR_DAX_EXE=!SMARTSDR_DIR!\DAX.exe"
if "!WIMS_SERVER!"=="" set "WIMS_SERVER=http://192.168.1.119:8787"

if "!LOG!"=="" set "LOG=%HERE%seat-startup-log.txt"
echo [%DATE% %TIME%] Seat begin stack=!RADIO_STACK! label=!SEAT_LABEL! > "%LOG%"
echo Repo=%ROOT%>> "%LOG%"
echo Server=%WIMS_SERVER% seat_id=!WIMS_SEAT_ID! rig=!WSJTX_RIG_NAME! agent_restart=!START_AGENT_RESTART!>> "%LOG%"

echo.
echo  WIMS seat startup — !SEAT_LABEL!
echo  =================================
echo  Repo:    %ROOT%
echo  Server:  %WIMS_SERVER%
if defined WIMS_SEAT_ID echo  Seat id: !WIMS_SEAT_ID!
echo  Stack:   !RADIO_STACK!
echo  WSJT-X:  --rig-name=!WSJTX_RIG_NAME!
echo  Apps:    N1MM=!START_N1MM! WSJT=!START_WSJTX! agent restart=!START_AGENT_RESTART!
echo  Log:     %LOG%
echo.

REM =====================================================================
REM 1) Radio middleware (must be before N1MM / WSJT-X CAT + audio)
REM =====================================================================
if /I "!RADIO_STACK!"=="smartsdr" goto do_smartsdr
if /I "!RADIO_STACK!"=="wfview" goto do_wfview
goto after_radio

:do_smartsdr
REM Flex 50 MHz: SmartSDR → CAT → DAX
if not exist "!SMARTSDR_EXE!" (
  echo  WARN: SmartSDR not found: !SMARTSDR_EXE!
  echo SmartSDR missing>> "%LOG%"
  goto after_smartsdr_main
)
tasklist /FI "IMAGENAME eq SmartSDR.exe" 2>nul | find /I "SmartSDR.exe" >nul
if not errorlevel 1 (
  echo  SmartSDR already running - leave it
  echo SmartSDR already running>> "%LOG%"
  goto after_smartsdr_main
)
echo  Starting SmartSDR...
start "SmartSDR" "!SMARTSDR_EXE!"
echo started SmartSDR>> "%LOG%"
echo  Waiting !SMARTSDR_DELAY_SEC!s for SmartSDR / radio connect...
set /a _PING_N=!SMARTSDR_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul

:after_smartsdr_main
if not "!START_SMARTSDR_CAT!"=="1" goto after_smartsdr_cat
if not exist "!SMARTSDR_CAT_EXE!" (
  echo  WARN: SmartSDR CAT not found: !SMARTSDR_CAT_EXE!
  echo SmartSDR CAT missing>> "%LOG%"
  goto after_smartsdr_cat
)
tasklist /FI "IMAGENAME eq CAT.exe" 2>nul | find /I "CAT.exe" >nul
if not errorlevel 1 (
  echo  SmartSDR CAT already running - leave it
  echo SmartSDR CAT already running>> "%LOG%"
  goto after_smartsdr_cat
)
echo  Starting SmartSDR CAT...
start "SmartSDR CAT" "!SMARTSDR_CAT_EXE!"
echo started SmartSDR CAT>> "%LOG%"

:after_smartsdr_cat
if not "!START_SMARTSDR_DAX!"=="1" goto after_smartsdr_dax
if not exist "!SMARTSDR_DAX_EXE!" (
  echo  WARN: SmartSDR DAX not found: !SMARTSDR_DAX_EXE!
  echo SmartSDR DAX missing>> "%LOG%"
  goto after_smartsdr_dax
)
tasklist /FI "IMAGENAME eq DAX.exe" 2>nul | find /I "DAX.exe" >nul
if not errorlevel 1 (
  echo  SmartSDR DAX already running - leave it
  echo SmartSDR DAX already running>> "%LOG%"
  goto after_smartsdr_dax
)
echo  Starting SmartSDR DAX...
start "SmartSDR DAX" "!SMARTSDR_DAX_EXE!"
echo started SmartSDR DAX>> "%LOG%"

:after_smartsdr_dax
echo  Waiting !START_DELAY_SEC!s for CAT ports / DAX channels...
set /a _PING_N=!START_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul
goto after_radio

:do_wfview
REM IC-9700 144 MHz: wfview owns COM; RigCtld before N1MM/WSJT CAT
if not exist "!WFVIEW_EXE!" (
  echo  WARN: wfview not found: !WFVIEW_EXE!
  echo wfview missing>> "%LOG%"
  goto after_radio
)
tasklist /FI "IMAGENAME eq wfview.exe" 2>nul | find /I "wfview.exe" >nul
if not errorlevel 1 (
  echo  wfview already running - leave it
  echo wfview already running>> "%LOG%"
  goto after_radio
)
echo  Starting wfview...
start "wfview" "!WFVIEW_EXE!"
echo started wfview>> "%LOG%"
echo  Waiting !WFVIEW_DELAY_SEC!s for wfview / RigCtld...
set /a _PING_N=!WFVIEW_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul
goto after_radio

:after_radio
REM =====================================================================
REM 2) N1MM (common — logger; start once if missing)
REM =====================================================================
if not "!START_N1MM!"=="1" (
  echo  Skip N1MM START_N1MM=0
  echo skip N1MM>> "%LOG%"
  goto after_n1mm
)
if not exist "!N1MM_EXE!" (
  echo  WARN: N1MM not found: !N1MM_EXE!
  echo N1MM missing>> "%LOG%"
  goto after_n1mm
)
tasklist /FI "IMAGENAME eq N1MMLogger.net.exe" 2>nul | find /I "N1MMLogger.net.exe" >nul
if not errorlevel 1 (
  echo  N1MM already running - leave it
  echo N1MM already running>> "%LOG%"
  goto after_n1mm
)
echo  Starting N1MM...
start "N1MM" /MIN "!N1MM_EXE!"
echo started N1MM>> "%LOG%"

:after_n1mm
echo  Waiting !START_DELAY_SEC!s...
set /a _PING_N=!START_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul

REM =====================================================================
REM 3) WSJT-X for this band only (unique --rig-name; leave other named instances)
REM =====================================================================
if not "!START_WSJTX!"=="1" (
  echo  Skip WSJT-X START_WSJTX=0
  echo skip WSJTX>> "%LOG%"
  goto after_wsjtx
)
if not exist "!WSJTX_EXE!" (
  echo  WARN: WSJT-X not found: !WSJTX_EXE!
  echo WSJTX missing>> "%LOG%"
  goto after_wsjtx
)
if not defined WSJTX_RIG_NAME goto wsjtx_no_rig
if "!WSJTX_RIG_NAME!"=="" goto wsjtx_no_rig

REM Only this band's named instance. Leave the other band (other --rig-name) alone.
wmic process where "name='wsjtx.exe'" get CommandLine 2>nul | find /I "--rig-name=!WSJTX_RIG_NAME!" >nul
if not errorlevel 1 (
  echo  WSJT-X already running with --rig-name=!WSJTX_RIG_NAME!
  echo WSJTX already running named>> "%LOG%"
  goto after_wsjtx
)

echo  Starting WSJT-X --rig-name=!WSJTX_RIG_NAME!...
echo  Config: %LOCALAPPDATA%\WSJT-X - !WSJTX_RIG_NAME!\
start "WSJT-X !WSJTX_RIG_NAME!" "!WSJTX_EXE!" --rig-name=!WSJTX_RIG_NAME!
echo started WSJTX rig=!WSJTX_RIG_NAME!>> "%LOG%"
goto after_wsjtx

:wsjtx_no_rig
echo  ERROR: WSJTX_RIG_NAME is empty — refusing to start WSJT-X without --rig-name.
echo  Set it in the radio config ^(radio-flex50.cmd / radio-ic9700-144.cmd^).
echo WSJTX refused: empty WSJTX_RIG_NAME>> "%LOG%"
goto after_wsjtx

:after_wsjtx
ping -n 3 127.0.0.1 >nul

REM =====================================================================
REM 4) WIMS seat agent
REM =====================================================================
if not "!START_AGENT!"=="1" (
  echo  Skip agent START_AGENT=0
  echo skip agent>> "%LOG%"
  goto after_agent
)
if not exist "%HERE%Start-WimsAgent-Continuous.cmd" (
  echo  WARN: missing Start-WimsAgent-Continuous.cmd
  echo agent launcher missing>> "%LOG%"
  goto after_agent
)

if not "!START_AGENT_RESTART!"=="1" goto agent_maybe_running

echo  Restarting WIMS agent...
for /f "skip=1 tokens=1" %%P in ('wmic process where "CommandLine like '%%wims.agent%%'" get ProcessId 2^>nul') do (
  if not "%%P"=="" if not "%%P"=="ProcessId" (
    echo    kill wims.agent PID %%P
    taskkill /PID %%P /F >nul 2>&1
    echo killed agent %%P>> "%LOG%"
  )
)
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
if not errorlevel 1 (
  echo  WIMS agent already running - OK
  echo  Local UI: http://127.0.0.1:8790/
  echo agent already running>> "%LOG%"
  goto after_agent
)
netstat -ano 2>nul | findstr /R /C:":8790 .*LISTENING" >nul
if not errorlevel 1 (
  echo  WARN: port 8790 in use but no wims.agent found
  echo  Set START_AGENT_RESTART=1 in seat-common.cmd to free it.
  echo agent port busy>> "%LOG%"
  goto after_agent
)

:agent_start
echo  Starting WIMS agent continuous - UI http://127.0.0.1:8790/
start "WIMS Agent" /MIN cmd /c call "%HERE%Start-WimsAgent-Continuous.cmd"
echo started agent>> "%LOG%"

:after_agent
echo.
echo  Seat startup finished ^(!SEAT_LABEL!^).
echo  Agent UI: http://127.0.0.1:8790/
echo  Full log: %LOG%
echo [%DATE% %TIME%] Seat done stack=!RADIO_STACK!>> "%LOG%"

if /I "%~1"=="/silent" exit /b 0
ping -n 6 127.0.0.1 >nul
exit /b 0
