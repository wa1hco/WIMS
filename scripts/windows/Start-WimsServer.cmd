@echo off
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
echo  WIMS: %ROOT%
echo  Python: %PYTHON_EXE%
echo  iface=%IFACE%  http://localhost:8787/
echo.

"%PYTHON_EXE%" -m wims.server.app --iface %IFACE% --n1mm-group 224.0.0.73 --http-port 8787 %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
