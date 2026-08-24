#Requires -Version 5.1

# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

<#
.SYNOPSIS
  Add Windows Firewall allow-rules for N1MM, WSJT-X, GridTracker, and WIMS
  on the Private profile (contest LAN).

  Do NOT turn the firewall off. Keep Ethernet Private, then run this.

  WSJT-X control uses an ephemeral UDP port — a rule limited to 2237 is wrong.
  Allow inbound UDP to wsjtx.exe (any local port). Same idea for GridTracker.

.NOTES
  ASCII-only. Run elevated. Missing apps are skipped (not an error).
#>
[CmdletBinding()]
param(
    [switch] $NoElevate
)

$ErrorActionPreference = "Stop"
$script:Failed = 0
$script:Changed = 0

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Status([string] $kind, [string] $msg) {
    $color = @{ OK = "Green"; WARN = "Yellow"; FAIL = "Red"; INFO = "Cyan"; SKIP = "DarkGray" }[$kind]
    if (-not $color) { $color = "White" }
    $line = "[{0}] {1}" -f $kind, $msg
    try { Write-Host $line -ForegroundColor $color } catch { Write-Output $line }
}

if (-not (Test-IsAdmin)) {
    if ($NoElevate) {
        Write-Status FAIL "Administrator required to change Windows Firewall."
        exit 1
    }
    Write-Status INFO "Elevating (UAC) to set contest app firewall rules..."
    $self = $MyInvocation.MyCommand.Path
    $p = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $self, "-NoElevate"
    )
    exit $p.ExitCode
}

function Ensure-Rule {
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [ValidateSet("Inbound", "Outbound")] [string] $Direction,
        [Parameter(Mandatory)] [ValidateSet("TCP", "UDP")] [string] $Protocol,
        [string] $Program = "",
        [string] $LocalPort = "",
        [string] $Profile = "Private"
    )
    $existing = @(Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        try {
            Set-NetFirewallRule -DisplayName $DisplayName -Action Allow -Enabled True -Profile $Profile -ErrorAction Stop
            Write-Status OK "updated $DisplayName ($Protocol $Direction $Profile)"
            $script:Changed += 1
        } catch {
            Write-Status FAIL "could not update $DisplayName : $_"
            $script:Failed += 1
        }
        return
    }
    $params = @{
        DisplayName = $DisplayName
        Direction   = $Direction
        Protocol    = $Protocol
        Action      = "Allow"
        Enabled     = $true
        Profile     = $Profile
        ErrorAction = "Stop"
    }
    if ($Program) { $params.Program = $Program }
    if ($LocalPort) { $params.LocalPort = $LocalPort }
    try {
        New-NetFirewallRule @params | Out-Null
        Write-Status OK "added $DisplayName ($Protocol $Direction $Profile)"
        $script:Changed += 1
    } catch {
        Write-Status FAIL "could not add $DisplayName : $_"
        $script:Failed += 1
    }
}

function Ensure-ProgramPair {
    param(
        [Parameter(Mandatory)] [string] $Label,
        [Parameter(Mandatory)] [string] $Exe,
        [string[]] $Protocols = @("UDP")
    )
    if (-not (Test-Path -LiteralPath $Exe)) {
        Write-Status SKIP "$Label not installed ($Exe)"
        return
    }
    foreach ($proto in $Protocols) {
        Ensure-Rule -DisplayName "WIMS contest - $Label $proto" `
            -Direction Inbound -Protocol $proto -Program $Exe -Profile Private
    }
}

Write-Status INFO "Contest app firewall — Private profile only (leave Public blocked)"
Write-Host ""

# --- N1MM Logger+ (peer log TCP 12070 + UDP discovery / broadcasts) ---
$n1mm = "C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe"
$rotor = "C:\Program Files (x86)\N1MM Logger+\N1MMRotor.net.exe"
Ensure-ProgramPair -Label "N1MM Logger+" -Exe $n1mm -Protocols @("TCP", "UDP")
Ensure-ProgramPair -Label "N1MM Rotor+" -Exe $rotor -Protocols @("TCP", "UDP")
# Belt-and-suspenders: peer port even if the exe path changes after an update
Ensure-Rule -DisplayName "WIMS contest - N1MM TCP 12070" -Direction Inbound -Protocol TCP -LocalPort "12070"
Ensure-Rule -DisplayName "WIMS contest - N1MM UDP 12070" -Direction Inbound -Protocol UDP -LocalPort "12070"
Ensure-Rule -DisplayName "WIMS contest - N1MM UDP 12080" -Direction Inbound -Protocol UDP -LocalPort "12080"
Ensure-Rule -DisplayName "WIMS contest - N1MM UDP 12060" -Direction Inbound -Protocol UDP -LocalPort "12060"

# --- WSJT-X: program UDP (any local port — control is ephemeral, not 2237) ---
$wsjtCandidates = @(
    "C:\WSJT\wsjtx\bin\wsjtx.exe",
    "C:\wsjt\wsjtx\bin\wsjtx.exe",
    "C:\Program Files\wsjtx\bin\wsjtx.exe",
    "C:\Program Files (x86)\wsjtx\bin\wsjtx.exe"
)
if (Test-Path "C:\WSJT") {
    Get-ChildItem "C:\WSJT" -Filter "wsjtx.exe" -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object { $wsjtCandidates += $_.FullName }
}
if (Test-Path "C:\wsjt") {
    Get-ChildItem "C:\wsjt" -Filter "wsjtx.exe" -Recurse -Depth 4 -ErrorAction SilentlyContinue |
        ForEach-Object { $wsjtCandidates += $_.FullName }
}
$wsjtSeen = @{}
foreach ($exe in $wsjtCandidates) {
    $key = $exe.ToLower()
    if ($wsjtSeen.ContainsKey($key)) { continue }
    $wsjtSeen[$key] = $true
    if (-not (Test-Path -LiteralPath $exe)) { continue }
    $leaf = Split-Path (Split-Path (Split-Path $exe -Parent) -Parent) -Leaf
    if (-not $leaf) { $leaf = "wsjtx" }
    Ensure-ProgramPair -Label "WSJT-X ($leaf)" -Exe $exe -Protocols @("UDP")
}
if ($wsjtSeen.Count -eq 0) {
    Write-Status SKIP "WSJT-X not found under C:\WSJT or Program Files"
}

# --- GridTracker / GridTracker2 (optional viewer) ---
$gtCandidates = @(
    "$env:LOCALAPPDATA\GridTracker2\GridTracker2.exe",
    "$env:LOCALAPPDATA\Programs\GridTracker2\GridTracker2.exe",
    "$env:LOCALAPPDATA\GridTracker\GridTracker.exe",
    "$env:LOCALAPPDATA\Programs\GridTracker\GridTracker.exe",
    "C:\Program Files\GridTracker2\GridTracker2.exe",
    "C:\Program Files\GridTracker\GridTracker.exe",
    "C:\Program Files (x86)\GridTracker\GridTracker.exe"
)
$gtFound = $false
foreach ($exe in $gtCandidates) {
    if (Test-Path -LiteralPath $exe) {
        $gtFound = $true
        $name = [IO.Path]::GetFileNameWithoutExtension($exe)
        Ensure-ProgramPair -Label $name -Exe $exe -Protocols @("UDP")
        # WIMS optional GT bridge forwards plane A to 22370
        Ensure-Rule -DisplayName "WIMS contest - GridTracker UDP 22370" `
            -Direction Inbound -Protocol UDP -LocalPort "22370"
    }
}
if (-not $gtFound) {
    Write-Status SKIP "GridTracker not installed (optional)"
}

# --- WIMS: port rules (python.exe path is not stable) ---
Ensure-Rule -DisplayName "WIMS contest - console TCP 8787" -Direction Inbound -Protocol TCP -LocalPort "8787"
Ensure-Rule -DisplayName "WIMS contest - agent TCP 8790" -Direction Inbound -Protocol TCP -LocalPort "8790"
Ensure-Rule -DisplayName "WIMS contest - presence UDP 8788" -Direction Inbound -Protocol UDP -LocalPort "8788"

Write-Host ""
Write-Status INFO "Outbound is already Allow on Windows — no outbound rules needed."
Write-Status INFO "Public profile left blocked. Ethernet must stay Private."
if ($script:Failed -gt 0) {
    Write-Status FAIL "$script:Failed rule(s) failed, $script:Changed changed"
    exit 1
}
Write-Status OK "$script:Changed rule(s) added or updated"
exit 0
