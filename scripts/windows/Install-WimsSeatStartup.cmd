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
REM Register seat apps to start at logon (user Startup folder — no admin required).
REM This PC already auto-logs in as W2SZ; Startup runs after desktop is ready.

cd /d "%~dp0"
set "HERE=%~dp0"
set "SEAT=%~dp0Start-WimsSeat.cmd"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\WIMS Seat.lnk"

if not exist "%SEAT%" (
  echo ERROR: missing Start-WimsSeat.cmd
  pause
  exit /b 1
)

if not exist "%STARTUP%" mkdir "%STARTUP%" 2>nul

echo.
echo  Install WIMS seat auto-start
echo  ============================
echo  Launcher: %SEAT%
echo  Startup:  %LNK%
echo.

if not exist "%HERE%seat-local.cmd" (
  if exist "%HERE%seat-config.example.cmd" (
    copy /Y "%HERE%seat-config.example.cmd" "%HERE%seat-local.cmd" >nul
    echo  Created seat-local.cmd from example — edit paths/seat id if needed.
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = '%SEAT%'; $s.Arguments = '/silent'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 7; $s.Description = 'Start wfview, N1MM, WSJT-X, WIMS agent at logon'; $s.Save(); Write-Host 'Shortcut written.'"

if not exist "%LNK%" (
  echo ERROR: could not create Startup shortcut
  pause
  exit /b 1
)

echo.
echo  RESULT: OK — at next logon this user will run Start-WimsSeat.cmd
echo  Edit:   %HERE%seat-local.cmd
echo  Remove: double-click Remove-WimsSeatStartup.cmd
echo  Test now: double-click Start-WimsSeat.cmd
echo.
pause
exit /b 0
