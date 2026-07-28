@echo off

REM FlexRadio 50 MHz — radio-specific settings.
REM Copy to radio-flex50.cmd and edit (gitignored).
REM Used only by Start-Seat-Flex50.cmd.
REM
REM Start order: SmartSDR → CAT → DAX → N1MM → WSJT-X → agent

set "SEAT_LABEL=Flex-50"
set "WIMS_SEAT_ID=FLEX-50"

REM Unique WSJT-X UDP id for 6 m (separate config from 144)
REM Config dir: %LOCALAPPDATA%\WSJT-X - <name>\
set "WSJTX_RIG_NAME=WSJTX-50"

REM Versioned SmartSDR install folder (change when upgrading)
set "SMARTSDR_DIR=C:\Program Files\SmartSDR v4.2.20"
REM Optional explicit paths:
REM set "SMARTSDR_EXE=C:\Program Files\SmartSDR v4.2.20\SmartSDR.exe"
REM set "SMARTSDR_CAT_EXE=C:\Program Files\SmartSDR v4.2.20\CAT.exe"
REM set "SMARTSDR_DAX_EXE=C:\Program Files\SmartSDR v4.2.20\DAX.exe"

set "START_SMARTSDR_CAT=1"
set "START_SMARTSDR_DAX=1"
REM Extra wait after SmartSDR before CAT/DAX (radio connect / slices)
set "SMARTSDR_DELAY_SEC=15"
