@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Dedicated Operate console window (Chrome --app= style: compact, resizable).
REM Uses the reachable site server (localhost, WIMS_SERVER, or last-known
REM LAN URL). Does not start a second site server if one is already on the
REM contest LAN. Close with the window X or Alt+F4.
REM Firefox --kiosk is fullscreen-locked; do not use it.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

call "%~dp0_resolve-python.cmd"

set "FF="
set "CHROME="
if exist "%ProgramFiles%\Mozilla Firefox\firefox.exe" set "FF=%ProgramFiles%\Mozilla Firefox\firefox.exe"
if not defined FF if exist "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" set "FF=%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined FF if not defined CHROME (
  echo ERROR: Firefox or Chrome is required for kiosk mode.
  if /I not "%~1"=="/silent" pause
  exit /b 1
)

echo  WIMS console kiosk
echo.

set "URL="
"%PYTHON_EXE%" -c "from wims.launcher.app import probe_site_urls; ok, base = probe_site_urls(); print(('OK' if ok else 'FAIL') + ' ' + base.rstrip('/') + '/')" > "%TEMP%\wims-kiosk-url.txt" 2>nul
for /f "usebackq tokens=1,*" %%A in ("%TEMP%\wims-kiosk-url.txt") do (
  set "PROBE=%%A"
  set "URL=%%B"
)
if not defined URL set "URL=http://127.0.0.1:8787/"
REM Always Operate (/). Probe returns the site base with no path.
if /I not "%URL:~-1%"=="/" set "URL=%URL%/"

if /I "%PROBE%"=="OK" (
  echo  Console: %URL%
) else (
  echo  No site server reachable yet. Opening %URL% anyway.
  echo  If this PC should HOST the server, use Desktop WIMS Server first.
)

set "PROFILE=%LOCALAPPDATA%\WIMS\kiosk-profile"
if not exist "%PROFILE%" mkdir "%PROFILE%" >nul 2>&1
echo  Opening Operate (compact, resizable). Close with the window X or Alt+F4.
if defined FF (
  "%PYTHON_EXE%" -c "from wims.launcher.app import prepare_firefox_kiosk_profile; prepare_firefox_kiosk_profile()" 2>nul
  start "" "%FF%" --new-instance --profile "%PROFILE%" -width 900 -height 640 "%URL%"
) else (
  start "" "%CHROME%" --app="%URL%" --user-data-dir="%PROFILE%" --no-first-run --disable-session-crashed-bubble
)
exit /b 0
