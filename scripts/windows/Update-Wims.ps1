#Requires -Version 5.1

# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One-click update: git fetch + pull --ff-only from origin/main.
# Keep ASCII-only for Windows PowerShell 5.1.

[CmdletBinding()]
param(
    [string] $RepoPath = "",
    [string] $Remote = "origin",
    [string] $Branch = "main",
    [switch] $ResetHard,
    [switch] $Relaunch,
    [switch] $NoPause
)

$ErrorActionPreference = "Stop"

function Log([string] $msg, [string] $color = "White") {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    try { Write-Host $line -ForegroundColor $color } catch { Write-Output $line }
    if ($script:LogFile) {
        try { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 } catch { }
    }
}

function Find-RepoPath {
    param([string] $Hint)
    if ($Hint -and (Test-Path (Join-Path $Hint "src\wims\__init__.py"))) {
        return (Resolve-Path $Hint).Path
    }
    # This script lives in <repo>\scripts\windows
    $here = $PSScriptRoot
    $cand = (Resolve-Path (Join-Path $here "..\..")).Path
    if (Test-Path (Join-Path $cand "src\wims\__init__.py")) { return $cand }
    foreach ($p in @(
        (Join-Path $env:USERPROFILE "src\WIMS"),
        (Join-Path $env:USERPROFILE "WIMS"),
        "C:\WIMS"
    )) {
        if (Test-Path (Join-Path $p "src\wims\__init__.py")) { return $p }
    }
    return $null
}

$RepoPath = Find-RepoPath -Hint $RepoPath
if (-not $RepoPath) {
    Write-Host "FAIL: WIMS repo not found. Run Install-Wims.cmd first." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 2
}

$win = Join-Path $RepoPath "scripts\windows"
$script:LogFile = Join-Path $win "update-log.txt"
try {
    "===== WIMS update $(Get-Date -Format o) =====" | Set-Content -LiteralPath $script:LogFile -Encoding UTF8
} catch { }

Log "Repo = $RepoPath" "Cyan"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Log "FAIL: git not on PATH. Run Install-Wims.cmd once." "Red"
    if (-not $NoPause) { pause }
    exit 2
}

$gitDir = Join-Path $RepoPath ".git"
if (-not (Test-Path $gitDir)) {
    Log "FAIL: not a git checkout (no .git). Clone with Install-Wims.cmd or git clone." "Red"
    if (-not $NoPause) { pause }
    exit 2
}

Push-Location $RepoPath
try {
    $before = (git rev-parse --short HEAD 2>$null)
    if (-not $before) { $before = "?" }
    Log "Before: $before"

    Log "git fetch $Remote $Branch ..."
    git fetch --quiet $Remote $Branch 2>&1 | ForEach-Object { Log "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Log "FAIL: git fetch failed (network?). See update-log.txt" "Red"
        if (-not $NoPause) { pause }
        exit 1
    }

    $remoteSha = (git rev-parse --short "$Remote/$Branch" 2>$null)
    Log "Remote $Remote/$Branch = $remoteSha"

    if ($ResetHard) {
        Log "git reset --hard $Remote/$Branch (explicit)" "Yellow"
        git reset --hard "$Remote/$Branch" 2>&1 | ForEach-Object { Log "  $_" }
        if ($LASTEXITCODE -ne 0) {
            Log "FAIL: reset --hard failed" "Red"
            if (-not $NoPause) { pause }
            exit 1
        }
    } else {
        Log "git pull --ff-only $Remote $Branch ..."
        git pull --ff-only $Remote $Branch 2>&1 | ForEach-Object { Log "  $_" }
        if ($LASTEXITCODE -ne 0) {
            Log "FAIL: pull --ff-only failed (local changes?). Fix or re-run with -ResetHard in lab." "Red"
            if (-not $NoPause) { pause }
            exit 1
        }
    }

    $after = (git rev-parse --short HEAD 2>$null)
    if (-not $after) { $after = "?" }
    Log "After:  $after" "Green"
    if ($before -eq $after) {
        Log "Already up to date." "Green"
    } else {
        Log "Updated $before -> $after" "Green"
    }
} finally {
    Pop-Location
}

# Refresh Desktop WIMS launcher shortcut when helper exists.
$deskShortcut = Join-Path $win "Install-WIMS-Desktop-Shortcut.cmd"
if (Test-Path -LiteralPath $deskShortcut) {
    Log "Refreshing Desktop WIMS shortcut..."
    try {
        & cmd /c "`"$deskShortcut`" /nopause" | ForEach-Object { Log "  $_" }
    } catch {
        Log "WARN: shortcut refresh: $_" "Yellow"
    }
}

# Also ensure Update-Wims itself is on Desktop for next time.
try {
    $desk = [Environment]::GetFolderPath("Desktop")
    if (-not $desk) { $desk = Join-Path $env:USERPROFILE "Desktop" }
    $ico = Join-Path $win "assets\wims.ico"
    $updCmd = Join-Path $win "Update-Wims.cmd"
    if ((Test-Path $updCmd) -and (Test-Path $desk)) {
        $wsh = New-Object -ComObject WScript.Shell
        $lnkPath = Join-Path $desk "Update WIMS.lnk"
        $lnk = $wsh.CreateShortcut($lnkPath)
        $lnk.TargetPath = $updCmd
        $lnk.WorkingDirectory = $win
        $lnk.Description = "Pull latest WIMS from GitHub main"
        if (Test-Path $ico) { $lnk.IconLocation = "$ico,0" }
        $lnk.Save()
        Log "Desktop shortcut: $lnkPath"
    }
} catch {
    Log "WARN: Update shortcut: $_" "Yellow"
}

if ($Relaunch) {
    $launch = Join-Path $win "Start-WimsLauncher.cmd"
    if (Test-Path $launch) {
        Log "Relaunching WIMS launcher..."
        Start-Process -FilePath $launch -WorkingDirectory $win
    }
}

Log "Done." "Green"
if (-not $NoPause) { pause }
exit 0
