@echo off

REM Start Grok CLI in C:\wims with tools auto-approved (no permission prompts).
REM Logon: Start-GrokAtLogon.vbs. Interactive: double-click this file.

setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
cd /d "%ROOT%"

set "GROK=%USERPROFILE%\.grok\bin\grok.exe"
if not exist "%GROK%" (
  echo ERROR: grok.exe not found: %GROK%
  echo Install Grok CLI, then grok login once.
  if /I not "%~1"=="/silent" pause
  exit /b 1
)

REM Brief settle after logon so auth/network is up.
if /I "%~1"=="/silent" ping -n 8 127.0.0.1 >nul

REM Visible TUI; --always-approve skips ordinary tool permission prompts.
where wt >nul 2>&1
if not errorlevel 1 (
  start "Grok" wt.exe -d "%ROOT%" --title Grok "%GROK%" --always-approve --cwd "%ROOT%"
  exit /b 0
)
start "Grok" /D "%ROOT%" "%GROK%" --always-approve --cwd "%ROOT%"
exit /b 0
