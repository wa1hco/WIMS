@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-GrokLogonStartup.ps1" -NoPause
if /I not "%~1"=="/nopause" if errorlevel 1 pause
exit /b %ERRORLEVEL%
