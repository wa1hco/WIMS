@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Dispatcher for seat packs (radio-specific scripts do the real work):
REM   Start-Seat-Flex50.cmd         Flex 50 MHz — SmartSDR + CAT + DAX
REM   Start-Seat-IC9700-144.cmd     IC-9700 144 MHz — wfview
REM
REM Usage:
REM   Start-WimsSeat.cmd              → SEAT_DEFAULT_RADIO from seat-common, or menu
REM   Start-WimsSeat.cmd flex50       → Flex 50 pack
REM   Start-WimsSeat.cmd ic9700-144   → IC-9700 144 pack
REM   Start-WimsSeat.cmd /silent ...  → no pause at end (Startup folder)
REM
REM Also accepted: flex, 50, 6m, icom, ic9700, 144, 2m

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"

set "SILENT="
set "CHOICE="
for %%A in (%*) do (
  if /I "%%~A"=="/silent" set "SILENT=/silent"
  if /I "%%~A"=="flex50" set "CHOICE=flex50"
  if /I "%%~A"=="flex" set "CHOICE=flex50"
  if /I "%%~A"=="50" set "CHOICE=flex50"
  if /I "%%~A"=="6m" set "CHOICE=flex50"
  if /I "%%~A"=="ic9700-144" set "CHOICE=ic9700-144"
  if /I "%%~A"=="ic9700" set "CHOICE=ic9700-144"
  if /I "%%~A"=="icom" set "CHOICE=ic9700-144"
  if /I "%%~A"=="144" set "CHOICE=ic9700-144"
  if /I "%%~A"=="2m" set "CHOICE=ic9700-144"
)

if defined CHOICE goto dispatch

REM No CLI choice — load default from shared config
if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
if not exist "%HERE%seat-common.cmd" if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if defined SEAT_DEFAULT_RADIO set "CHOICE=!SEAT_DEFAULT_RADIO!"

if defined CHOICE goto dispatch

REM Interactive menu (not for /silent Startup)
if defined SILENT (
  echo ERROR: no radio pack selected and SEAT_DEFAULT_RADIO not set.
  echo Edit seat-common.cmd: set "SEAT_DEFAULT_RADIO=flex50" or ic9700-144
  echo Or: Install-WimsSeatStartup.cmd flex50
  exit /b 2
)

echo.
echo  WIMS seat pack — pick radio
echo  ===========================
echo.
echo    1.  Flex 50 MHz     ^(SmartSDR + CAT + DAX + N1MM + WSJT-X-50^)
echo    2.  IC-9700 144 MHz ^(wfview + N1MM + WSJT-X-144^)
echo.
echo    0.  Cancel
echo.
choice /C 120 /N /M "  Choose 0-2: "
if errorlevel 3 goto cancel
if errorlevel 2 set "CHOICE=ic9700-144" & goto dispatch
if errorlevel 1 set "CHOICE=flex50" & goto dispatch

:cancel
echo Cancelled.
exit /b 0

:dispatch
if /I "!CHOICE!"=="flex50" (
  echo  Starting Flex 50 MHz seat pack...
  call "%HERE%Start-Seat-Flex50.cmd" !SILENT!
  exit /b !ERRORLEVEL!
)
if /I "!CHOICE!"=="ic9700-144" (
  echo  Starting IC-9700 144 MHz seat pack...
  call "%HERE%Start-Seat-IC9700-144.cmd" !SILENT!
  exit /b !ERRORLEVEL!
)

echo ERROR: unknown radio pack "!CHOICE!" ^(use flex50 or ic9700-144^)
if not defined SILENT pause
exit /b 2
