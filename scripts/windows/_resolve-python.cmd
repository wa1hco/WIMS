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

REM Sets PYTHON_EXE for callers (call this script). Prefer install pin, then common paths.
set "PYTHON_EXE="
if exist "%~dp0python-path.txt" (
  set /p PYTHON_EXE=<"%~dp0python-path.txt"
)
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%ProgramFiles%\Python313\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%ProgramFiles%\Python312\python.exe"
if exist "%PYTHON_EXE%" goto :eof
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  goto :eof
)
REM Last resort — may be Store stub; prefer failing clearly
set "PYTHON_EXE=python"
