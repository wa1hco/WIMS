@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later

setlocal EnableExtensions
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS at logon.lnk"

echo.
echo  Remove WIMS logon auto-start
echo  ============================
echo  Target: %LNK%
echo.

if exist "%LNK%" (
  del /F /Q "%LNK%"
  echo  Removed.
) else (
  echo  Not installed ^(no shortcut^).
)

echo.
if /I not "%~1"=="/nopause" pause
exit /b 0
