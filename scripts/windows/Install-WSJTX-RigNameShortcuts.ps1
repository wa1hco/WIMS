#Requires -Version 5.1
<#
  Install exactly ONE WSJT-X shortcut per desktop (user + public) and keep the
  Start Menu install entry pointed at Start-WSJTX.cmd (--rig-name required).
  Removes redundant wsjt*.lnk clutter first.
#>
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Here "Start-WSJTX.cmd"
$Icon = "C:\WSJT\wsjtx\bin\wsjtx.exe"

if (-not (Test-Path $Launcher)) {
  Write-Error "Missing $Launcher"
  exit 1
}

$rig = "UNSET"
$seatLocal = Join-Path $Here "seat-local.cmd"
if (Test-Path $seatLocal) {
  $m = Select-String -Path $seatLocal -Pattern 'set\s+"WSJTX_RIG_NAME=([^"]*)"' | Select-Object -First 1
  if ($m) { $rig = $m.Matches[0].Groups[1].Value }
}

$ws = New-Object -ComObject WScript.Shell

function Set-ForcedShortcut([string]$Path) {
  $dir = Split-Path -Parent $Path
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  $s = $ws.CreateShortcut($Path)
  $s.TargetPath = $Launcher
  $s.Arguments = ""
  $s.WorkingDirectory = $Here
  if (Test-Path $Icon) { $s.IconLocation = "$Icon,0" }
  $s.Description = "WSJT-X with required --rig-name=$rig (via Start-WSJTX.cmd)"
  $s.Save()
  Write-Host "OK  $Path"
}

function Remove-WsjtShortcutsIn([string]$Dir) {
  if (-not (Test-Path $Dir)) { return }
  Get-ChildItem $Dir -Filter "*.lnk" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      $s = $ws.CreateShortcut($_.FullName)
      $t = [string]$s.TargetPath
      if ($_.Name -match '(?i)wsjt' -or $t -match '(?i)wsjtx|Start-WSJTX') {
        Remove-Item $_.FullName -Force
        Write-Host "REMOVE $($_.FullName)"
      }
    } catch {}
  }
}

$userDesktop = [Environment]::GetFolderPath("Desktop")
$publicDesktop = "C:\Users\Public\Desktop"
$userPrograms = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$installMenu = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\wsjtx 3.0.2"

# Strip clutter on both desktops (Windows merges them into one view).
# Keep exactly ONE icon on the *user* desktop — not Public (that doubles it).
Remove-WsjtShortcutsIn $userDesktop
Remove-WsjtShortcutsIn $publicDesktop
Set-ForcedShortcut (Join-Path $userDesktop "WSJT-X.lnk")


# User Start Menu Programs: remove our old extras (keep install folder entry only)
Remove-WsjtShortcutsIn $userPrograms

# Vendor Start Menu: single entry
if (Test-Path $installMenu) {
  Get-ChildItem $installMenu -Filter "*.lnk" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Name -ieq "Uninstall.lnk") { return }
    if ($_.Name -ieq "wsjtx.lnk") {
      Set-ForcedShortcut $_.FullName
    } else {
      # Drop duplicate names we may have created (WSJT-X.lnk etc.)
      if ($_.Name -match '(?i)^WSJT') {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "REMOVE $($_.FullName)"
      }
    }
  }
  if (-not (Test-Path (Join-Path $installMenu "wsjtx.lnk"))) {
    Set-ForcedShortcut (Join-Path $installMenu "wsjtx.lnk")
  }
}

Write-Host ""
Write-Host "WSJT-X: one Desktop icon (user + public) + Start Menu wsjtx.lnk -> Start-WSJTX.cmd (rig-name=$rig)"
exit 0
