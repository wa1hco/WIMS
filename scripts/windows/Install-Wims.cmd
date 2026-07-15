@echo off
setlocal EnableExtensions
REM Double-click install with reliable UAC elevation (no quoting hell).

cd /d "%~dp0"
set "HERE=%~dp0"
set "PS1=%~dp0Install-Wims.ps1"
for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
set "LOG=%~dp0install-log.txt"
set "ELEV=%TEMP%\wims-elevate-install.ps1"

echo.
echo  WIMS Windows install
echo  ====================
echo  Repo:   %REPO%
echo  Script: %PS1%
echo  Log:    %LOG%
echo.

if not exist "%REPO%\src\wims\server\app.py" (
  echo  ERROR: Not a full WIMS checkout:
  echo    %REPO%
  echo  git clone https://github.com/wa1hco/WIMS.git
  echo.
  pause
  exit /b 1
)

if not exist "%PS1%" (
  echo  ERROR: Missing Install-Wims.ps1
  pause
  exit /b 1
)

REM Seed log so we always have something to show
echo [%DATE% %TIME%] Install-Wims.cmd started > "%LOG%"
echo Repo=%REPO%>> "%LOG%"
echo User=%USERNAME%>> "%LOG%"

net session >nul 2>&1
if not errorlevel 1 (
  echo  Already Administrator — running install...
  echo Already admin >> "%LOG%"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -RepoPath "%REPO%" -LogPath "%LOG%"
  goto :show
)

echo  Administrator required for machine-wide Python and firewall.
echo  A UAC prompt should appear — click Yes.
echo.
echo Waiting for UAC / elevated install... >> "%LOG%"

REM Write a tiny elev helper with HARD-CODED absolute paths (avoids nested-quote bugs).
(
  echo $ErrorActionPreference = 'Stop'
  echo $ps1  = '%PS1%'
  echo $repo = '%REPO%'
  echo $log  = '%LOG%'
  echo "Elevated helper starting" ^| Out-File -FilePath $log -Append -Encoding utf8
  echo "  ps1=$ps1" ^| Out-File -FilePath $log -Append -Encoding utf8
  echo "  repo=$repo" ^| Out-File -FilePath $log -Append -Encoding utf8
  echo if (-not ^(Test-Path -LiteralPath $ps1^)^) { "MISSING ps1" ^| Out-File $log -Append; exit 2 }
  echo ^& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps1 -RepoPath $repo -LogPath $log
  echo $code = $LASTEXITCODE
  echo "Elevated helper exit=$code" ^| Out-File -FilePath $log -Append -Encoding utf8
  echo exit $code
) > "%ELEV%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%ELEV%'); 'Start-Process exit=' + $p.ExitCode | Out-File -FilePath '%LOG%' -Append -Encoding utf8; exit $p.ExitCode } catch { $_ | Out-File -FilePath '%LOG%' -Append -Encoding utf8; 'UAC_DENIED_OR_ERROR' | Out-File -FilePath '%LOG%' -Append -Encoding utf8; exit 1 }"

set ELEV_ERR=%ERRORLEVEL%
echo Elevation/start exit code: %ELEV_ERR% >> "%LOG%"

:show
echo.
echo  ---------- install-log.txt ----------
if exist "%LOG%" (
  type "%LOG%"
) else (
  echo  ^(log missing — unexpected^)
)
echo  -------------------------------------
echo.

findstr /C:"SUCCESS" "%LOG%" >nul 2>&1
if not errorlevel 1 (
  echo  RESULT: SUCCESS
  if exist "%~dp0python-path.txt" (
    echo  Python:
    type "%~dp0python-path.txt"
  )
  echo  Next: double-click Start-WimsServer.cmd
  goto :done
)

findstr /C:"UAC_DENIED_OR_ERROR" "%LOG%" >nul 2>&1
if not errorlevel 1 (
  echo  RESULT: UAC was denied or elevation failed.
  echo  Right-click Install-Wims.cmd -^> Run as administrator
  goto :done
)

findstr /C:"Elevated helper starting" "%LOG%" >nul 2>&1
if errorlevel 1 (
  if %ELEV_ERR% neq 0 (
    echo  RESULT: Elevated process did not start ^(UAC cancelled?^).
    echo  Right-click Install-Wims.cmd -^> Run as administrator
    goto :done
  )
)

echo  RESULT: Install did not finish with SUCCESS.
echo  Scroll up for FAIL lines in the log.
echo  Or right-click Install-Wims.cmd -^> Run as administrator

:done
echo.
echo  Full log: %LOG%
echo.
pause
exit /b 0
