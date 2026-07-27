@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Import WSJT-X config dropped by W10VM-50 onto this seat as --rig-name=W10VM-144
set "SHARE=\\truenas\share\wsjtx-from-50"
set "DST=%LOCALAPPDATA%\WSJT-X - W10VM-144"
set "SRC="
if exist "%SHARE%\named\WSJT-X.ini" set "SRC=%SHARE%\named"
if not defined SRC if exist "%SHARE%\default\WSJT-X.ini" set "SRC=%SHARE%\default"
if not defined SRC (
  echo No config on share yet. On W10VM-50 run:
  echo   %SHARE%\EXPORT-FROM-W10VM-50.cmd
  pause
  exit /b 1
)
echo Stopping WSJT-X...
taskkill /IM jt9.exe /F >nul 2>&1
taskkill /IM wsjtx.exe /F >nul 2>&1
ping -n 2 127.0.0.1 >nul
echo Copying %SRC% -^> %DST%
if exist "%DST%" ren "%DST%" "WSJT-X - W10VM-144.bak-%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
mkdir "%DST%" 2>nul
xcopy "%SRC%\*" "%DST%\" /E /I /Y /H
echo Relaunching with --rig-name=W10VM-144
call "%~dp0Start-WSJTX.cmd"
echo Done.
pause
