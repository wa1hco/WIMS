# WIMS — create/refresh Desktop "WIMS" shortcut with a sticky custom icon.
# Targets wscript.exe + Start-WimsLauncher.vbs so Explorer does not replace
# our icon with the default .cmd glyph after clone / Update / VM restore.
param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $here "Start-WimsLauncher.vbs"
$cmd = Join-Path $here "Start-WimsLauncher.cmd"
$ico = Join-Path $here "assets\wims.ico"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

if (-not (Test-Path -LiteralPath $cmd)) {
    Write-Host "ERROR: Start-WimsLauncher.cmd missing next to this script." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}
if (-not (Test-Path -LiteralPath $vbs)) {
    Write-Host "ERROR: Start-WimsLauncher.vbs missing — pull latest WIMS." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}
if (-not (Test-Path -LiteralPath $ico)) {
    Write-Host "ERROR: assets\wims.ico missing — pull latest WIMS." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}

$desk = [Environment]::GetFolderPath("Desktop")
if (-not $desk -or -not (Test-Path -LiteralPath $desk)) {
    $desk = Join-Path $env:USERPROFILE "Desktop"
}
if (-not (Test-Path -LiteralPath $desk)) {
    $desk = Join-Path $env:USERPROFILE "OneDrive\Desktop"
}
$lnkPath = Join-Path $desk "WIMS.lnk"
$icoAbs = (Resolve-Path -LiteralPath $ico).Path
$vbsAbs = (Resolve-Path -LiteralPath $vbs).Path

$wsh = New-Object -ComObject WScript.Shell
$s = $wsh.CreateShortcut($lnkPath)
$s.TargetPath = $wscript
$s.Arguments = "//nologo `"$vbsAbs`""
$s.WorkingDirectory = $here
$s.WindowStyle = 1
$s.Description = "WIMS launcher - agents + site console"
$s.IconLocation = "$icoAbs,0"
$s.Save()

# Drop COM ref so the .lnk is fully flushed before we report.
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null

Write-Host ""
Write-Host " Desktop shortcut ready: WIMS"
Write-Host "  $lnkPath"
Write-Host "  Icon: $icoAbs"
Write-Host " Double-click WIMS on the Desktop for the GUI launcher."
Write-Host ""

# Install / refresh never creates WIMS Server or WIMS Agent icons.
foreach ($staleName in @("WIMS Server.lnk", "WIMS Agent.lnk")) {
    $stale = Join-Path $desk $staleName
    if (Test-Path -LiteralPath $stale) {
        Remove-Item -LiteralPath $stale -Force
        Write-Host " Removed leftover $staleName (launcher only)."
    }
}

if (-not $NoPause) { pause }
exit 0
