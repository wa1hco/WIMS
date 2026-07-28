@echo off

REM WIMS — shared seat settings (both radios on this PC / template).
REM Copy to seat-common.cmd and edit (seat-common.cmd is gitignored).
REM Loaded by Start-Seat-Flex50.cmd and Start-Seat-IC9700-144.cmd before radio config.
REM
REM Radio-specific paths and WSJT-X --rig-name live in:
REM   radio-flex50.cmd        / radio-flex50.example.cmd
REM   radio-ic9700-144.cmd    / radio-ic9700-144.example.cmd

REM Site WIMS server (agent reports here)
set "WIMS_SERVER=http://192.168.1.119:8787"

REM Optional: which pack Install-WimsSeatStartup / Start-WimsSeat default to
REM   flex50 | ic9700-144
set "SEAT_DEFAULT_RADIO=flex50"

REM What to start (both packs honor these)
set "START_N1MM=1"
set "START_WSJTX=1"
set "START_AGENT=1"
REM 1 = kill existing wims.agent and start fresh (dev-friendly)
set "START_AGENT_RESTART=1"

REM Common paths
set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"

REM Settle after middleware / after N1MM (seconds)
set "START_DELAY_SEC=5"

REM Agent continuous: seconds between config reports
set "AGENT_INTERVAL=30"
