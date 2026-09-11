# WIMS - User Startup shortcut: start WSJT-X + WIMS from saved seat intent.
param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $here "Start-WimsAtLogon.vbs"
$ico = Join-Path $here "assets\wims.ico"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

if (-not (Test-Path -LiteralPath $vbs)) {
    Write-Host "ERROR: Start-WimsAtLogon.vbs missing." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}

$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
if (-not (Test-Path -LiteralPath $startup)) {
    New-Item -ItemType Directory -Path $startup -Force | Out-Null
}
$lnk = Join-Path $startup "WIMS at logon.lnk"
$vbsAbs = (Resolve-Path -LiteralPath $vbs).Path
$icoAbs = $null
if (Test-Path -LiteralPath $ico) {
    $icoAbs = (Resolve-Path -LiteralPath $ico).Path
}

$pack = Join-Path $startup "WIMS Seat.lnk"
if (Test-Path -LiteralPath $pack) {
    Write-Host " NOTE: WIMS Seat.lnk is also in Startup (radio pack)."
    Write-Host " Remove it with Remove-WimsSeatStartup.cmd if you only want this script."
}

$wsh = New-Object -ComObject WScript.Shell
$s = $wsh.CreateShortcut($lnk)
$s.TargetPath = $wscript
$s.Arguments = "//nologo `"$vbsAbs`""
$s.WorkingDirectory = $here
$s.WindowStyle = 7
$s.Description = "WIMS: start WSJT-X and launcher from seat intent"
if ($icoAbs) { $s.IconLocation = "$icoAbs,0" }
$s.Save()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null

Write-Host " Startup: $lnk"
Write-Host " Next logon starts from %APPDATA%\wims\seat_intent.json"
Write-Host " Test: Start-WimsAtLogon.cmd --dry-run"
Write-Host " Remove: Remove-WimsLogonStartup.cmd"
if (-not $NoPause) { pause }
exit 0
