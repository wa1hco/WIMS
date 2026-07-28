@echo off

REM Icom IC-9700 144 MHz — radio-specific settings.
REM Copy to radio-ic9700-144.cmd and edit (gitignored).
REM Used only by Start-Seat-IC9700-144.cmd.
REM
REM Start order: wfview → N1MM → WSJT-X → agent
REM (wfview owns radio COM; RigCtld must be enabled for WSJT-X Hamlib NET)

set "SEAT_LABEL=IC9700-144"
set "WIMS_SEAT_ID=IC9700-144"

REM Unique WSJT-X UDP id for 2 m (separate config from 50)
REM Config dir: %LOCALAPPDATA%\WSJT-X - <name>\
REM Fleet example: W10VM-144
set "WSJTX_RIG_NAME=WSJTX-144"

set "WFVIEW_EXE=C:\Program Files\wfview\wfview.exe"
REM Wait for RigCtld / TCP after launching wfview
set "WFVIEW_DELAY_SEC=5"
