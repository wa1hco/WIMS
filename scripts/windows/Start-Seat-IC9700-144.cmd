@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Icom IC-9700 144 MHz seat pack:
REM   wfview → N1MM → WSJT-X (--rig-name for 2 m) → WIMS agent
REM
REM Does NOT start the site WIMS server. N1MM is shared with the Flex pack.
REM WSJT-X uses a separate named config from the 50 MHz instance.
REM
REM Config load order:
REM   1) seat-common.cmd   (or seat-local.cmd) — server, N1MM path, agent
REM   2) radio-ic9700-144.cmd — wfview path, WIMS_SEAT_ID, WSJTX_RIG_NAME

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"

REM Defaults for this radio (overridden by config files below)
set "RADIO_STACK=wfview"
set "SEAT_LABEL=IC9700-144"
set "WIMS_SEAT_ID=IC9700-144"
set "WSJTX_RIG_NAME=WSJTX-144"
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"
set "START_AGENT_RESTART=1"
set "WFVIEW_EXE=C:\Program Files\wfview\wfview.exe"
set "START_DELAY_SEC=5"
set "WFVIEW_DELAY_SEC=5"
set "LOG=%HERE%seat-startup-ic9700-144-log.txt"

REM Shared then radio-specific (later wins for same vars)
if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
if not exist "%HERE%seat-common.cmd" if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not exist "%HERE%seat-common.cmd" if not exist "%HERE%seat-local.cmd" if exist "%HERE%seat-common.example.cmd" call "%HERE%seat-common.example.cmd"
if exist "%HERE%radio-ic9700-144.cmd" call "%HERE%radio-ic9700-144.cmd"
if not exist "%HERE%radio-ic9700-144.cmd" if exist "%HERE%radio-ic9700-144.example.cmd" call "%HERE%radio-ic9700-144.example.cmd"

REM Force this radio stack (config must not switch to smartsdr)
set "RADIO_STACK=wfview"
if "!SEAT_LABEL!"=="" set "SEAT_LABEL=IC9700-144"
if "!WSJTX_RIG_NAME!"=="" set "WSJTX_RIG_NAME=WSJTX-144"

call "%HERE%_Start-Seat-Core.cmd" %*
set "ERR=!ERRORLEVEL!"
exit /b !ERR!
