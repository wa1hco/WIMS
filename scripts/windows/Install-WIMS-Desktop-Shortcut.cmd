@echo off
setlocal EnableExtensions
REM Desktop "WIMS" shortcut with sticky custom icon (wscript + VBS + wims.ico).
REM Prefer Install-WimsDesktopShortcut.ps1 — .cmd targets lose custom icons on Windows.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-WimsDesktopShortcut.ps1" -NoPause
set "RC=%ERRORLEVEL%"
if /I not "%~1"=="/nopause" if not "%RC%"=="0" pause
exit /b %RC%
