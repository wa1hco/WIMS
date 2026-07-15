@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Start contest seat apps after auto-logon: kill stale -> N1MM -> WSJT-X -> agent.
REM Dev-friendly: by default kills existing instances so each start is a clean refresh.
REM Does NOT start the site WIMS server.
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
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"
REM Default ON for development: always kill then start fresh
set "START_KILL_EXISTING=1"
set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
set "WSJTX_RIG_NAME="
set "START_DELAY_SEC=5"
set "AGENT_INTERVAL=30"

if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not exist "%HERE%seat-local.cmd" if exist "%HERE%seat-config.example.cmd" call "%HERE%seat-config.example.cmd"

set "LOG=%HERE%seat-startup-log.txt"
echo [%DATE% %TIME%] Start-WimsSeat begin > "%LOG%"
echo Repo=%ROOT%>> "%LOG%"
echo Server=%WIMS_SERVER% seat=%WIMS_SEAT_ID% kill=!START_KILL_EXISTING!>> "%LOG%"

echo.
echo  WIMS seat startup
echo  =================
echo  Repo:   %ROOT%
echo  Server: %WIMS_SERVER%
if defined WIMS_SEAT_ID echo  Seat:   %WIMS_SEAT_ID%
echo  Kill:   !START_KILL_EXISTING!  ^(1=stop old instances first^)
echo  Log:    %LOG%
echo.

if not "!START_KILL_EXISTING!"=="1" goto after_kill
echo  Stopping any existing seat processes...
echo kill phase>> "%LOG%"

REM WIMS agent only (not every python.exe)
for /f "skip=1 tokens=1" %%P in ('wmic process where "CommandLine like '%%wims.agent%%'" get ProcessId 2^>nul') do (
  if not "%%P"=="" if not "%%P"=="ProcessId" (
    echo    kill wims.agent PID %%P
    taskkill /PID %%P /F >nul 2>&1
    echo killed agent %%P>> "%LOG%"
  )
)

REM WSJT-X + decoder helper
taskkill /IM wsjtx.exe /F >nul 2>&1
if not errorlevel 1 (
  echo    killed wsjtx.exe
  echo killed wsjtx>> "%LOG%"
)
taskkill /IM jt9.exe /F >nul 2>&1
if not errorlevel 1 (
  echo    killed jt9.exe
  echo killed jt9>> "%LOG%"
)

REM N1MM Logger+
taskkill /IM N1MMLogger.net.exe /F >nul 2>&1
if not errorlevel 1 (
  echo    killed N1MMLogger.net.exe
  echo killed n1mm>> "%LOG%"
)

REM Free agent port if something still holds it
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /R /C:":8790 .*LISTENING"') do (
  if not "%%P"=="0" (
    echo    kill PID %%P on port 8790
    taskkill /PID %%P /F >nul 2>&1
    echo killed port8790 %%P>> "%LOG%"
  )
)

ping -n 3 127.0.0.1 >nul
echo  Kill phase done.
echo.

:after_kill
if not "!START_N1MM!"=="1" goto skip_n1mm
if not exist "!N1MM_EXE!" goto n1mm_missing
echo  Starting N1MM...
start "N1MM" /MIN "!N1MM_EXE!"
echo started N1MM>> "%LOG%"
goto after_n1mm

:n1mm_missing
echo  WARN: N1MM not found: !N1MM_EXE!
echo N1MM missing>> "%LOG%"
goto after_n1mm

:skip_n1mm
echo  Skip N1MM START_N1MM=0
echo skip N1MM>> "%LOG%"

:after_n1mm
if "!START_DELAY_SEC!"=="" set "START_DELAY_SEC=5"
echo  Waiting !START_DELAY_SEC!s...
set /a _PING_N=!START_DELAY_SEC!+1
ping -n !_PING_N! 127.0.0.1 >nul

if not "!START_WSJTX!"=="1" goto skip_wsjtx
if not exist "!WSJTX_EXE!" goto wsjtx_missing
echo  Starting WSJT-X...
if defined WSJTX_RIG_NAME if not "!WSJTX_RIG_NAME!"=="" goto wsjtx_named
start "WSJTX" "!WSJTX_EXE!"
echo started WSJTX default>> "%LOG%"
goto after_wsjtx

:wsjtx_named
start "WSJTX" "!WSJTX_EXE!" --rig-name=!WSJTX_RIG_NAME!
echo started WSJTX rig=!WSJTX_RIG_NAME!>> "%LOG%"
goto after_wsjtx

:wsjtx_missing
echo  WARN: WSJT-X not found: !WSJTX_EXE!
echo WSJTX missing>> "%LOG%"
goto after_wsjtx

:skip_wsjtx
echo  Skip WSJT-X START_WSJTX=0
echo skip WSJTX>> "%LOG%"

:after_wsjtx
ping -n 3 127.0.0.1 >nul

if not "!START_AGENT!"=="1" goto skip_agent
if not exist "%HERE%Start-WimsAgent-Continuous.cmd" goto agent_missing
echo  Starting WIMS agent continuous - UI http://127.0.0.1:8790/
start "WIMS Agent" /MIN cmd /c call "%HERE%Start-WimsAgent-Continuous.cmd"
echo started agent>> "%LOG%"
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
echo  Seat startup finished ^(fresh instances^).
echo  Agent UI: http://127.0.0.1:8790/
echo  Full log: %LOG%
echo [%DATE% %TIME%] Start-WimsSeat done>> "%LOG%"

if /I "%~1"=="/silent" exit /b 0
ping -n 6 127.0.0.1 >nul
exit /b 0
