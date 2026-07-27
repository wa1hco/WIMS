#Requires -Version 5.1
<#
.SYNOPSIS
  Find every Windows shortcut that starts WSJT-X, show --rig-name, optionally set it.

.DESCRIPTION
  Scans Desktop, Startup, Start Menu, common ProgramData, and this scripts folder.
  Use this when two VMs both show as UDP id "WSJT-X" in WIMS.

  List only (default):
    powershell -ExecutionPolicy Bypass -File Find-And-Set-WsjtxRigName.ps1

  Apply on this PC (e.g. 2m seat):
    powershell -ExecutionPolicy Bypass -File Find-And-Set-WsjtxRigName.ps1 -RigName W10VM-144 -Apply

  Also prints where WIMS seat boot gets the name (seat-local.cmd WSJTX_RIG_NAME).

.NOTES
  Does not change Task Scheduler or registry Run keys unless present as .lnk in
  the scanned folders — those are listed separately if found via schtasks / reg.
#>
[CmdletBinding()]
param(
    [string] $RigName = "",
    [switch] $Apply,
    [switch] $IncludeTaskScheduler
)

$ErrorActionPreference = "Continue"

function Write-Info($m) { Write-Host $m -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  OK  $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  !!  $m" -ForegroundColor Yellow }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scanRoots = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
    [Environment]::GetFolderPath("Startup"),
    [Environment]::GetFolderPath("StartMenu"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"),
    $scriptDir,
    (Join-Path $env:USERPROFILE "Desktop")
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

Write-Info "=== WSJT-X launcher scan ==="
Write-Host "PC: $env:COMPUTERNAME  User: $env:USERNAME"
Write-Host ""

# --- seat-local.cmd (WIMS boot path) ---
$seatLocal = Join-Path $scriptDir "seat-local.cmd"
$seatEx = Join-Path $scriptDir "seat-config.example.cmd"
Write-Info "WIMS seat boot (Start-WimsSeat / Startup 'WIMS Seat'):"
if (Test-Path $seatLocal) {
    $txt = Get-Content -LiteralPath $seatLocal -Raw -ErrorAction SilentlyContinue
    if ($txt -match 'WSJTX_RIG_NAME=(.+)') {
        $cur = $Matches[1].Trim().Trim('"')
        if ($cur) { Write-Ok "seat-local.cmd WSJTX_RIG_NAME=$cur" }
        else { Write-Warn "seat-local.cmd WSJTX_RIG_NAME is blank → default id WSJT-X" }
    } else {
        Write-Warn "seat-local.cmd has no WSJTX_RIG_NAME line"
    }
    if ($Apply -and $RigName) {
        $new = @()
        $found = $false
        Get-Content -LiteralPath $seatLocal | ForEach-Object {
            if ($_ -match '^\s*set\s+"WSJTX_RIG_NAME=') {
                $new += "set `"WSJTX_RIG_NAME=$RigName`""
                $found = $true
            } elseif ($_ -match '^\s*set\s+WSJTX_RIG_NAME=') {
                $new += "set `"WSJTX_RIG_NAME=$RigName`""
                $found = $true
            } else {
                $new += $_
            }
        }
        if (-not $found) {
            $new += ""
            $new += "REM UDP id for WIMS (unique per radio/VM)"
            $new += "set `"WSJTX_RIG_NAME=$RigName`""
        }
        Set-Content -LiteralPath $seatLocal -Value $new -Encoding ASCII
        Write-Ok "Updated seat-local.cmd → WSJTX_RIG_NAME=$RigName"
    }
} else {
    Write-Warn "No seat-local.cmd yet (copy from seat-config.example.cmd)"
    if ($Apply -and $RigName -and (Test-Path $seatEx)) {
        Copy-Item -LiteralPath $seatEx -Destination $seatLocal -Force
        (Get-Content $seatLocal) -replace 'WSJTX_RIG_NAME=.*', "WSJTX_RIG_NAME=$RigName" |
            Set-Content $seatLocal -Encoding ASCII
        # also set seat id if still template
        (Get-Content $seatLocal) -replace 'WIMS_SEAT_ID=TEMPLATE-01', "WIMS_SEAT_ID=$RigName" |
            Set-Content $seatLocal -Encoding ASCII
        Write-Ok "Created seat-local.cmd with WSJTX_RIG_NAME=$RigName"
    }
}
Write-Host ""

# --- .lnk shortcuts ---
$shell = New-Object -ComObject WScript.Shell
$found = @()

foreach ($root in $scanRoots) {
    Get-ChildItem -LiteralPath $root -Filter *.lnk -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $sc = $shell.CreateShortcut($_.FullName)
                $tp = [string]$sc.TargetPath
                $arg = [string]$sc.Arguments
                if ($tp -match 'wsjtx\.exe' -or $arg -match 'wsjtx') {
                    $found += [pscustomobject]@{
                        Path      = $_.FullName
                        Target    = $tp
                        Arguments = $arg
                        WorkingDir = $sc.WorkingDirectory
                    }
                }
            } catch { }
        }
}

Write-Info "Shortcuts that start WSJT-X ($($found.Count) found):"
if ($found.Count -eq 0) {
    Write-Warn "None found in Desktop / Startup / Start Menu / scripts"
} else {
    $i = 0
    foreach ($f in $found) {
        $i++
        $hasRig = $f.Arguments -match '--rig-name[=\s]+(\S+)'
        $rig = if ($hasRig) { $Matches[1] } else { "(none → id WSJT-X)" }
        Write-Host ""
        Write-Host "  [$i] $($f.Path)"
        Write-Host "      Target: $($f.Target)"
        Write-Host "      Args:   $($f.Arguments)"
        if ($hasRig) { Write-Ok "rig-name=$rig" } else { Write-Warn "no --rig-name  $rig" }

        if ($Apply -and $RigName) {
            $exe = $f.Target
            if (-not ($exe -match 'wsjtx\.exe$')) {
                # Target might be cmd; leave Args rewrite only
            }
            $newArgs = $f.Arguments
            if ($newArgs -match '--rig-name[=\s]+\S+') {
                $newArgs = $newArgs -replace '--rig-name[=\s]+\S+', "--rig-name=$RigName"
            } elseif ($newArgs.Trim()) {
                $newArgs = $newArgs.Trim() + " --rig-name=$RigName"
            } else {
                $newArgs = "--rig-name=$RigName"
            }
            try {
                $sc = $shell.CreateShortcut($f.Path)
                $sc.Arguments = $newArgs
                $sc.Save()
                Write-Ok "Updated args → $newArgs"
            } catch {
                Write-Warn "Could not update: $_"
            }
        }
    }
}

Write-Host ""
Write-Info "Startup folder shortcuts (all .lnk names):"
$startup = [Environment]::GetFolderPath("Startup")
if (Test-Path $startup) {
    Get-ChildItem $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  $($_.Name)  →  $($_.FullName)"
    }
} else {
    Write-Host "  (no user Startup folder)"
}

if ($IncludeTaskScheduler) {
    Write-Host ""
    Write-Info "Task Scheduler tasks mentioning wsjtx (names only):"
    try {
        schtasks /Query /FO LIST /V 2>$null | Select-String -Pattern 'wsjtx|WSJT' -Context 2,0 | ForEach-Object { $_.Line }
    } catch { Write-Warn "schtasks query failed" }
}

Write-Host ""
Write-Info "=== Recommended per-seat values ==="
Write-Host "  2m / IC-9700 (.116):  -RigName W10VM-144"
Write-Host "  6m / Flex     (.120):  -RigName W10VM-50"
Write-Host ""
Write-Host "After Apply:"
Write-Host "  1. Exit all wsjtx.exe (Task Manager if needed)"
Write-Host "  2. Reboot OR run Start-WimsSeat.cmd"
Write-Host "  3. On WIMS Status: two different instance ids, one host each"
Write-Host ""
if (-not $Apply) {
    Write-Host "List-only mode. To write changes, re-run with -RigName NAME -Apply" -ForegroundColor Yellow
}
if ($Apply -and -not $RigName) {
    Write-Warn "-Apply requires -RigName"
}
