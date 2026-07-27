@echo off
setlocal EnableExtensions
REM Double-click: list all WSJT-X launchers and seat-local.cmd rig-name.
REM To apply on this PC, run from cmd (examples below).

cd /d "%~dp0"
echo.
echo  List launchers ^(no changes^):
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Find-And-Set-WsjtxRigName.ps1" %*
echo.
echo  ------------------------------------------------------------
echo  To SET rig-name on this PC, open cmd here and run ONE of:
echo.
echo    Find-And-Set-WsjtxRigName.cmd -RigName W10VM-144 -Apply
echo    Find-And-Set-WsjtxRigName.cmd -RigName W10VM-50 -Apply
echo.
echo  Then EXIT all wsjtx.exe and reboot ^(or Start-WimsSeat.cmd^).
echo  ------------------------------------------------------------
echo.
pause
exit /b 0
