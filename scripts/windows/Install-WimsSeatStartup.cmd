@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Register a radio seat pack to start at logon (user Startup folder — no admin).
REM
REM Usage:
REM   Install-WimsSeatStartup.cmd              → uses SEAT_DEFAULT_RADIO or prompts
REM   Install-WimsSeatStartup.cmd flex50
REM   Install-WimsSeatStartup.cmd ic9700-144

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\WIMS Seat.lnk"

set "PACK=%~1"
if /I "%PACK%"=="flex" set "PACK=flex50"
if /I "%PACK%"=="50" set "PACK=flex50"
if /I "%PACK%"=="6m" set "PACK=flex50"
if /I "%PACK%"=="ic9700" set "PACK=ic9700-144"
if /I "%PACK%"=="icom" set "PACK=ic9700-144"
if /I "%PACK%"=="144" set "PACK=ic9700-144"
if /I "%PACK%"=="2m" set "PACK=ic9700-144"

if "%PACK%"=="" (
  if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
  if defined SEAT_DEFAULT_RADIO set "PACK=!SEAT_DEFAULT_RADIO!"
)

if "%PACK%"=="" (
  echo.
  echo  Install logon auto-start for which radio?
  echo    1. Flex 50 MHz     ^(SmartSDR + CAT + DAX^)
  echo    2. IC-9700 144 MHz ^(wfview^)
  echo.
  choice /C 12 /N /M "  Choose 1-2: "
  if errorlevel 2 (
    set "PACK=ic9700-144"
  ) else (
    set "PACK=flex50"
  )
)

if /I "%PACK%"=="flex50" (
  set "SEAT=%HERE%Start-Seat-Flex50.cmd"
  set "DESC=WIMS Flex-50: SmartSDR CAT DAX N1MM WSJT agent"
) else if /I "%PACK%"=="ic9700-144" (
  set "SEAT=%HERE%Start-Seat-IC9700-144.cmd"
  set "DESC=WIMS IC9700-144: wfview N1MM WSJT agent"
) else (
  echo ERROR: pack must be flex50 or ic9700-144 ^(got %PACK%^)
  pause
  exit /b 1
)

if not exist "!SEAT!" (
  echo ERROR: missing !SEAT!
  pause
  exit /b 1
)

if not exist "%STARTUP%" mkdir "%STARTUP%" 2>nul

echo.
echo  Install WIMS seat auto-start
echo  ============================
echo  Pack:     %PACK%
echo  Launcher: !SEAT!
echo  Startup:  %LNK%
echo.

if not exist "%HERE%seat-common.cmd" (
  if exist "%HERE%seat-common.example.cmd" (
    copy /Y "%HERE%seat-common.example.cmd" "%HERE%seat-common.cmd" >nul
    echo  Created seat-common.cmd from example.
  )
)
if /I "%PACK%"=="flex50" if not exist "%HERE%radio-flex50.cmd" (
  if exist "%HERE%radio-flex50.example.cmd" (
    copy /Y "%HERE%radio-flex50.example.cmd" "%HERE%radio-flex50.cmd" >nul
    echo  Created radio-flex50.cmd from example.
  )
)
if /I "%PACK%"=="ic9700-144" if not exist "%HERE%radio-ic9700-144.cmd" (
  if exist "%HERE%radio-ic9700-144.example.cmd" (
    copy /Y "%HERE%radio-ic9700-144.example.cmd" "%HERE%radio-ic9700-144.cmd" >nul
    echo  Created radio-ic9700-144.cmd from example.
  )
)

REM Remember default for Start-WimsSeat.cmd dispatcher
if exist "%HERE%seat-common.cmd" (
  findstr /I /C:"SEAT_DEFAULT_RADIO" "%HERE%seat-common.cmd" >nul 2>&1
  if errorlevel 1 (
    echo.>> "%HERE%seat-common.cmd"
    echo set "SEAT_DEFAULT_RADIO=%PACK%">> "%HERE%seat-common.cmd"
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = '!SEAT!'; $s.Arguments = '/silent'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 7; $s.Description = '!DESC!'; $s.Save(); Write-Host 'Shortcut written.'"

if not exist "%LNK%" (
  echo ERROR: could not create Startup shortcut
  pause
  exit /b 1
)

echo.
echo  RESULT: OK — at next logon this user will run the %PACK% pack
echo  Common: %HERE%seat-common.cmd
if /I "%PACK%"=="flex50" echo  Radio:  %HERE%radio-flex50.cmd
if /I "%PACK%"=="ic9700-144" echo  Radio:  %HERE%radio-ic9700-144.cmd
echo  Remove: double-click Remove-WimsSeatStartup.cmd
echo  Test:   double-click Start-Seat-Flex50.cmd or Start-Seat-IC9700-144.cmd
echo.
pause
exit /b 0
