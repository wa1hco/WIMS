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

setlocal EnableExtensions
REM Remove seat auto-start from this user's Startup folder.

set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS Seat.lnk"

echo.
echo  Remove WIMS seat auto-start
echo  ===========================
echo  Target: %LNK%
echo.

if exist "%LNK%" (
  del /F /Q "%LNK%"
  echo  Removed.
) else (
  echo  Not installed ^(no shortcut^).
)

echo.
pause
exit /b 0
