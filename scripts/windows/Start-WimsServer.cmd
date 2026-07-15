@echo off
setlocal
REM Double-click to start the WIMS server. No Set-ExecutionPolicy required.

cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul
if errorlevel 1 (
  echo Cannot find WIMS repo root from %~dp0
  pause
  exit /b 1
)
set "ROOT=%CD%"
popd

set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

REM Prefer first non-loopback IPv4 for multicast join (multi-host lab).
set "IFACE=0.0.0.0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "IFACE=%%I"

set "N1MM_GROUP=224.0.0.73"
set "HTTP_PORT=8787"

echo.
echo  WIMS root: %ROOT%
echo    iface=%IFACE%  n1mm-group=%N1MM_GROUP%  http=:%HTTP_PORT%
echo    Operate  http://localhost:%HTTP_PORT%/
echo    Status   http://localhost:%HTTP_PORT%/status
echo    Setup    http://localhost:%HTTP_PORT%/setup
echo    Remote   http://^<this-host-ip^>:%HTTP_PORT%/
echo.

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
  py -3 -m wims.server.app --iface %IFACE% --n1mm-group %N1MM_GROUP% --http-port %HTTP_PORT% %*
  goto :after
)
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
  python -m wims.server.app --iface %IFACE% --n1mm-group %N1MM_GROUP% --http-port %HTTP_PORT% %*
  goto :after
)

echo Python not found. Double-click Install-Wims.cmd first.
pause
exit /b 1

:after
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo WIMS exited with code %ERR%.
  pause
)
exit /b %ERR%
