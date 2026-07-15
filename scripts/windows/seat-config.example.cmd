@echo off
REM Copy to seat-local.cmd and edit for this PC (seat-local.cmd is gitignored).
REM Loaded by Start-WimsSeat.cmd before launching apps.

REM Site WIMS server (agent reports here)
set "WIMS_SERVER=http://192.168.1.119:8787"

REM Seat label on the wrangler dashboard (optional)
set "WIMS_SEAT_ID=TEMPLATE-01"
REM set "WIMS_AGENT_ID=win10-template-01"

REM What to start at logon (1=yes, 0=skip)
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"

REM 1 = kill N1MM / WSJT-X / wims.agent first, then start clean (recommended while developing)
REM 0 = only start apps that are not already running
set "START_KILL_EXISTING=1"

REM Paths — leave blank to use common defaults on this template image
set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"

REM Optional WSJT-X multi-instance: unique --rig-name (sets UDP id). Blank = default config.
set "WSJTX_RIG_NAME="

REM Delay between apps (seconds) so N1MM is up before WSJT-X
set "START_DELAY_SEC=5"

REM Agent continuous: seconds between config reports
set "AGENT_INTERVAL=30"
