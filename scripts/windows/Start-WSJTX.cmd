@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Always launch WSJT-X with a required --rig-name (UDP id).
REM Never start a bare wsjtx.exe — tired operators must not get the default id.
REM
REM Config path with --rig-name=FOO:
REM   %LOCALAPPDATA%\WSJT-X - FOO\WSJT-X - FOO.ini
REM (NOT WSJT-X.ini — that is only the no-rig-name default profile.)

cd /d "%~dp0"
set "HERE=%~dp0"

set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
set "WSJTX_RIG_NAME="

if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not defined WSJTX_RIG_NAME if exist "%HERE%seat-config.example.cmd" call "%HERE%seat-config.example.cmd"

REM Optional override: Start-WSJTX.cmd SomeName
if not "%~1"=="" set "WSJTX_RIG_NAME=%~1"

if not defined WSJTX_RIG_NAME goto no_rig
if "!WSJTX_RIG_NAME!"=="" goto no_rig

if not exist "!WSJTX_EXE!" (
  echo ERROR: WSJT-X not found: !WSJTX_EXE!
  pause
  exit /b 1
)

REM Seed named ini from original default profile if missing or still factory-empty
set "ORIG_INI=%LOCALAPPDATA%\WSJT-X\WSJT-X.ini"
set "NAMED_DIR=%LOCALAPPDATA%\WSJT-X - !WSJTX_RIG_NAME!"
set "NAMED_INI=!NAMED_DIR!\WSJT-X - !WSJTX_RIG_NAME!.ini"
if not exist "!NAMED_DIR!" mkdir "!NAMED_DIR!" >nul 2>&1

set "NEED_SEED=0"
if not exist "!NAMED_INI!" set "NEED_SEED=1"
if exist "!NAMED_INI!" (
  findstr /B /C:"MyCall=" "!NAMED_INI!" | findstr /R /C:"MyCall=$" >nul 2>&1
  if not errorlevel 1 set "NEED_SEED=1"
  findstr /B /C:"MyCall=" "!NAMED_INI!" >nul 2>&1
  if errorlevel 1 set "NEED_SEED=1"
  findstr /B /C:"Rig=None" "!NAMED_INI!" >nul 2>&1
  if not errorlevel 1 set "NEED_SEED=1"
)

if "!NEED_SEED!"=="1" (
  if exist "!ORIG_INI!" (
    echo Seeding named config from original: WSJT-X.ini -^> WSJT-X - !WSJTX_RIG_NAME!.ini
    copy /Y "!ORIG_INI!" "!NAMED_INI!" >nul
    copy /Y "!ORIG_INI!" "!NAMED_DIR!\WSJT-X.ini" >nul
  ) else (
    echo WARN: no original %LOCALAPPDATA%\WSJT-X\WSJT-X.ini to seed from
  )
)

echo Starting WSJT-X --rig-name=!WSJTX_RIG_NAME!
echo Config: !NAMED_INI!
start "WSJT-X !WSJTX_RIG_NAME!" "!WSJTX_EXE!" --rig-name=!WSJTX_RIG_NAME!
exit /b 0

:no_rig
echo.
echo  ERROR: WSJT-X rig-name is not set.
echo  Edit seat-local.cmd and set:
echo    set "WSJTX_RIG_NAME=YourSeatName"
echo  Or:  Start-WSJTX.cmd YourSeatName
echo.
echo  Refusing to start without --rig-name ^(prevents default UDP id^).
echo.
pause
exit /b 2
