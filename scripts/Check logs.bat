@echo off
REM See whether the logs on this PC agree. Reads logs. Does not change them.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0windows\Check-Logs.cmd" (
  echo This folder does not look like WIMS.
  echo Open the WIMS folder and double-click this file again.
  pause
  exit /b 1
)
call "%~dp0windows\Check-Logs.cmd"
exit /b %ERRORLEVEL%
