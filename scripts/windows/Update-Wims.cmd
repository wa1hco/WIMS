@echo off
setlocal EnableExtensions
REM One-click WIMS update: git pull --ff-only origin/main, then optional relaunch.
REM Usage:
REM   Update-Wims.cmd
REM   Update-Wims.cmd /relaunch
REM   Update-Wims.cmd /nopause

cd /d "%~dp0"
set "HERE=%~dp0"
set "RELAUNCH="
set "NOPAUSE="
if /I "%~1"=="/relaunch" set "RELAUNCH=-Relaunch"
if /I "%~2"=="/relaunch" set "RELAUNCH=-Relaunch"
if /I "%~1"=="/nopause" set "NOPAUSE=-NoPause"
if /I "%~2"=="/nopause" set "NOPAUSE=-NoPause"

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%Update-Wims.ps1" %RELAUNCH% %NOPAUSE%
set "EC=%ERRORLEVEL%"
exit /b %EC%
