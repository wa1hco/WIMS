@echo off
setlocal EnableExtensions EnableDelayedExpansion
title WIMS Seat
color 0A

REM Single entry point for seat PCs — no need to know paths or which .cmd to run.
REM Double-click this file, or use the Desktop "WIMS" shortcut from Install-WIMS-Desktop-Shortcut.cmd

cd /d "%~dp0"
set "HERE=%~dp0"

call :find_root
if not defined ROOT (
  echo.
  echo  ERROR: Could not find the WIMS install.
  echo  Expected a folder that contains src\wims\agent\app.py
  echo  Tried: scripts\windows\..\.. and %USERPROFILE%\WIMS
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not defined WIMS_SERVER set "WIMS_SERVER=http://192.168.1.119:8787"

:menu
cls
echo.
echo  ============================================================
echo   WIMS Seat menu
echo  ============================================================
echo   Install:  %ROOT%
echo   Server:   %WIMS_SERVER%
if defined WIMS_SEAT_ID (echo   Seat:     %WIMS_SEAT_ID%) else (echo   Seat:     ^(not set — edit seat-local.cmd^))
echo  ------------------------------------------------------------
echo.
echo    1.  Check this PC now          ^(agent one-shot report^)
echo    2.  Start continuous agent     ^(reports to server, stays running^)
echo    3.  Start seat pack            ^(N1MM / WSJT-X if needed + agent^)
echo    4.  Open local agent page      ^(http://127.0.0.1:8790/^)
echo    5.  Open server Status page    ^(%WIMS_SERVER%/status^)
echo    6.  Put WIMS on Desktop        ^(shortcut to this menu^)
echo    7.  Auto-start at logon        ^(install Startup for seat pack^)
echo    8.  Remove auto-start
echo.
echo    0.  Exit
echo.
echo  ============================================================
echo.
choice /C 123456780 /N /M "  Choose 0-8: "
set "SEL=%ERRORLEVEL%"

REM choice returns 1 for first char, so 1->1 ... 8->8, 0 is 9th option -> 9
if "%SEL%"=="9" goto end
if "%SEL%"=="1" goto do_check
if "%SEL%"=="2" goto do_agent
if "%SEL%"=="3" goto do_seat
if "%SEL%"=="4" goto do_local_ui
if "%SEL%"=="5" goto do_server_ui
if "%SEL%"=="6" goto do_desktop
if "%SEL%"=="7" goto do_startup_on
if "%SEL%"=="8" goto do_startup_off
goto menu

:do_check
echo.
call "%HERE%_resolve-python.cmd"
if not exist "!PYTHON_EXE!" if /I not "!PYTHON_EXE!"=="py" (
  echo  Python not found. Run Install-Wims.cmd once on this PC.
  pause
  goto menu
)
echo  Running seat check...
echo.
set "SEAT_ARGS="
if defined WIMS_SEAT_ID set "SEAT_ARGS=--seat-id %WIMS_SEAT_ID%"
if defined WIMS_AGENT_ID set "SEAT_ARGS=!SEAT_ARGS! --agent-id %WIMS_AGENT_ID%"
"!PYTHON_EXE!" -m wims.agent --server "%WIMS_SERVER%" %SEAT_ARGS%
echo.
pause
goto menu

:do_agent
echo.
echo  Starting continuous agent in a new window...
echo  Local page: http://127.0.0.1:8790/
echo  Stop with Ctrl+C in that window.
start "WIMS Agent" cmd /k call "%HERE%Start-WimsAgent-Continuous.cmd"
ping -n 2 127.0.0.1 >nul
goto menu

:do_seat
echo.
echo  Running seat pack...
call "%HERE%Start-WimsSeat.cmd"
goto menu

:do_local_ui
start "" "http://127.0.0.1:8790/"
goto menu

:do_server_ui
start "" "%WIMS_SERVER%/status"
goto menu

:do_desktop
call "%HERE%Install-WIMS-Desktop-Shortcut.cmd" /nopause
echo.
pause
goto menu

:do_startup_on
call "%HERE%Install-WimsSeatStartup.cmd"
goto menu

:do_startup_off
call "%HERE%Remove-WimsSeatStartup.cmd"
goto menu

:end
exit /b 0

REM ---------- locate WIMS repo root ----------
:find_root
set "ROOT="
REM 1) This script lives in ...\WIMS\scripts\windows
if exist "%HERE%..\..\src\wims\agent\app.py" (
  pushd "%HERE%..\.."
  set "ROOT=!CD!"
  popd
  goto :eof
)
REM 2) Common clone path
if exist "%USERPROFILE%\WIMS\src\wims\agent\app.py" (
  set "ROOT=%USERPROFILE%\WIMS"
  goto :eof
)
REM 3) Same drive root copy
if exist "C:\WIMS\src\wims\agent\app.py" (
  set "ROOT=C:\WIMS"
  goto :eof
)
goto :eof
