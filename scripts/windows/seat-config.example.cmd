@echo off

REM WIMS — WSJT-X Instance Management System
REM Copyright (C) 2026 Jeff Millar, WA1HCO
REM
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM This program is free software: you can redistribute it and/or modify
REM it under the terms of the GNU General Public License as published by
REM the Free Software Foundation, either version 3 of the License, or
REM (at your option) any later version.
REM
REM This program is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
REM GNU General Public License for more details.
REM
REM You should have received a copy of the GNU General Public License
REM along with this program.  If not, see <https://www.gnu.org/licenses/>.

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

REM N1MM / WSJT-X are never force-killed (only started if missing).
REM 1 = kill existing wims.agent and start a fresh one (recommended while agent is in dev)
REM 0 = leave a running agent alone
set "START_AGENT_RESTART=1"

REM Paths
set "N1MM_EXE=C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
set "WSJTX_EXE=C:\WSJT\wsjtx\bin\wsjtx.exe"

REM Optional WSJT-X multi-instance: unique --rig-name (sets UDP id). Blank = default config.
set "WSJTX_RIG_NAME="

REM Delay after starting N1MM before starting WSJT-X (seconds)
set "START_DELAY_SEC=5"

REM Agent continuous: seconds between config reports
set "AGENT_INTERVAL=30"
