# WIMS - Desktop + logon Startup shortcuts for the site console in kiosk mode.
param(
    [switch]$NoPause,
    [switch]$NoStartup
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmd = Join-Path $here "Start-WimsConsole-Kiosk.cmd"
$ico = Join-Path $here "assets\wims.ico"

if (-not (Test-Path -LiteralPath $cmd)) {
    Write-Host "ERROR: Start-WimsConsole-Kiosk.cmd missing next to this script." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}

function Get-DesktopDir {
    $desk = [Environment]::GetFolderPath("Desktop")
    if ($desk -and (Test-Path -LiteralPath $desk)) { return $desk }
    $fallback = Join-Path $env:USERPROFILE "Desktop"
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    $one = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    if (Test-Path -LiteralPath $one) { return $one }
    return $fallback
}

$cmdAbs = (Resolve-Path -LiteralPath $cmd).Path
$icoAbs = $null
if (Test-Path -LiteralPath $ico) {
    $icoAbs = (Resolve-Path -LiteralPath $ico).Path
}

$firefox = Join-Path $env:ProgramFiles "Mozilla Firefox\firefox.exe"
if (-not (Test-Path -LiteralPath $firefox)) {
    $pf86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($pf86) {
        $firefox = Join-Path $pf86 "Mozilla Firefox\firefox.exe"
    }
}
if (Test-Path -LiteralPath $firefox) {
    [Environment]::SetEnvironmentVariable("WIMS_BROWSER", $firefox, "User")
    $env:WIMS_BROWSER = $firefox
    Write-Host " WIMS_BROWSER (user) = $firefox"
} else {
    Write-Host " Firefox not found - kiosk script will use Chrome if present." -ForegroundColor Yellow
}

$wsh = New-Object -ComObject WScript.Shell

$desk = Get-DesktopDir
if (-not (Test-Path -LiteralPath $desk)) {
    New-Item -ItemType Directory -Path $desk -Force | Out-Null
}
$deskLnk = Join-Path $desk "WIMS Console Kiosk.lnk"
$sd = $wsh.CreateShortcut($deskLnk)
$sd.TargetPath = $cmdAbs
$sd.WorkingDirectory = $here
$sd.WindowStyle = 1
$sd.Description = "WIMS Operate console (compact, resizable)"
if ($icoAbs) { $sd.IconLocation = "$icoAbs,0" }
$sd.Save()
Write-Host " Desktop: $deskLnk"

if (-not $NoStartup) {
    $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    if (-not (Test-Path -LiteralPath $startup)) {
        New-Item -ItemType Directory -Path $startup -Force | Out-Null
    }
    $startLnk = Join-Path $startup "WIMS Console Kiosk.lnk"
    $ss = $wsh.CreateShortcut($startLnk)
    $ss.TargetPath = $cmdAbs
    $ss.Arguments = "/silent"
    $ss.WorkingDirectory = $here
    $ss.WindowStyle = 7
    $ss.Description = "Logon: WIMS site console kiosk"
    if ($icoAbs) { $ss.IconLocation = "$icoAbs,0" }
    $ss.Save()
    Write-Host " Startup: $startLnk"
}

[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null

Write-Host ""
Write-Host " Double-click Desktop WIMS Console Kiosk (or wait until next logon)."
Write-Host " Opens Operate in a compact resizable window (same idea as Chrome --app=)."
Write-Host ""
if (-not $NoPause) { pause }
exit 0
