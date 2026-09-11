@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Sets WSJTX_EXE for callers (call this script).
REM Keep an existing override, else default install, else wsjtx-inhibit.

if defined WSJTX_EXE if exist "%WSJTX_EXE%" goto :eof
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
if exist "%WSJTX_EXE%" goto :eof
set "WSJTX_EXE=C:\WSJT\wsjtx-inhibit\bin\wsjtx.exe"
if exist "%WSJTX_EXE%" goto :eof
set "WSJTX_EXE=C:\Program Files\WSJT\wsjtx\bin\wsjtx.exe"
if exist "%WSJTX_EXE%" goto :eof
REM Leave the default path so callers can print a clear "not found".
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"
