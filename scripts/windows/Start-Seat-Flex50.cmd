@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM FlexRadio 50 MHz seat pack:
REM   SmartSDR → CAT → DAX → N1MM → WSJT-X (--rig-name for 6 m) → WIMS agent
REM
REM Does NOT start the site WIMS server. N1MM is shared with the IC-9700 pack.
REM WSJT-X uses a separate named config from the 144 MHz instance.
REM
REM Config load order:
REM   1) seat-common.cmd   (or seat-local.cmd) — server, N1MM path, agent
REM   2) radio-flex50.cmd  — SmartSDR paths, WIMS_SEAT_ID, WSJTX_RIG_NAME

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "HERE=%~dp0"

REM Defaults for this radio (overridden by config files below)
set "RADIO_STACK=smartsdr"
set "SEAT_LABEL=Flex-50"
set "WIMS_SEAT_ID=FLEX-50"
set "WSJTX_RIG_NAME=WSJTX-50"
set "START_SMARTSDR_CAT=1"
set "START_SMARTSDR_DAX=1"
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"
set "START_AGENT_RESTART=1"
set "SMARTSDR_DIR=C:\Program Files\SmartSDR v4.2.20"
set "START_DELAY_SEC=5"
set "SMARTSDR_DELAY_SEC=15"
set "LOG=%HERE%seat-startup-flex50-log.txt"

REM Shared then radio-specific (later wins for same vars)
if exist "%HERE%seat-common.cmd" call "%HERE%seat-common.cmd"
if not exist "%HERE%seat-common.cmd" if exist "%HERE%seat-local.cmd" call "%HERE%seat-local.cmd"
if not exist "%HERE%seat-common.cmd" if not exist "%HERE%seat-local.cmd" if exist "%HERE%seat-common.example.cmd" call "%HERE%seat-common.example.cmd"
if exist "%HERE%radio-flex50.cmd" call "%HERE%radio-flex50.cmd"
if not exist "%HERE%radio-flex50.cmd" if exist "%HERE%radio-flex50.example.cmd" call "%HERE%radio-flex50.example.cmd"

REM Force this radio stack (config must not switch to wfview)
set "RADIO_STACK=smartsdr"
if "!SEAT_LABEL!"=="" set "SEAT_LABEL=Flex-50"
if "!WSJTX_RIG_NAME!"=="" set "WSJTX_RIG_NAME=WSJTX-50"

call "%HERE%_Start-Seat-Core.cmd" %*
set "ERR=!ERRORLEVEL!"
exit /b !ERR!
