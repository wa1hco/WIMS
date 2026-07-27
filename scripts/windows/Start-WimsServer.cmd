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
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

set "PYTHON_EXE=C:\Users\W2SZ\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python missing: %PYTHON_EXE%
  echo Run Install-Wims.cmd again.
  pause
  exit /b 1
)

set "IFACE=0.0.0.0"
for /f "usebackq delims=" %%I in (powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress } catch { '0.0.0.0' }") do set "IFACE=%%I"

echo.
echo  WIMS site server
echo  Root:  %ROOT%
echo  Python: %PYTHON_EXE%
echo  LAN:   %IFACE%
echo  Console: http://localhost:8787/   (also http://%IFACE%:8787/)
echo  Bands: 50/144/222/432 ports 2237-2240  ^(no flags to remember^)
echo.

REM Defaults join all band ports + N1MM mcast. Override only for lab: %*
"%PYTHON_EXE%" -m wims.server.app --iface %IFACE% --n1mm-group 224.0.0.73 --http-port 8787 %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
