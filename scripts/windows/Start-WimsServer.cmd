@echo off
setlocal EnableExtensions
REM Double-click start. Prefers python path written by Install-Wims; falls back to PATH search.

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

set "PYTHON_EXE="
if exist "%~dp0python-path.txt" (
  set /p PYTHON_EXE=<"%~dp0python-path.txt"
)
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :have_py

REM Fallback: discover after install if path file missing
set "PYTHON_EXE="
where py >nul 2>&1 && (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :have_py

where python >nul 2>&1 && (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%P | findstr /i "WindowsApps" >nul || (
      set "PYTHON_EXE=%%P"
      goto :have_py
    )
  )
)

echo.
echo  Python not found.
echo  Double-click Install-Wims.cmd first ^(installs Python automatically^).
echo  If install already ran: sign out/in or reboot, then run Install-Wims.cmd again.
echo.
pause
exit /b 1

:have_py
set "IFACE=0.0.0.0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "IFACE=%%I"

set "N1MM_GROUP=224.0.0.73"
set "HTTP_PORT=8787"

echo.
echo  WIMS root: %ROOT%
echo  Python:    %PYTHON_EXE%
echo    iface=%IFACE%  n1mm-group=%N1MM_GROUP%  http=:%HTTP_PORT%
echo    Operate  http://localhost:%HTTP_PORT%/
echo    Status   http://localhost:%HTTP_PORT%/status
echo    Setup    http://localhost:%HTTP_PORT%/setup
echo.

"%PYTHON_EXE%" -m wims.server.app --iface %IFACE% --n1mm-group %N1MM_GROUP% --http-port %HTTP_PORT% %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo WIMS exited with code %ERR%.
  pause
)
exit /b %ERR%
