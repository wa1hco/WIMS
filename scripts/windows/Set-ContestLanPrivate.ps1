#Requires -Version 5.1

# WIMS - WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

<#
.SYNOPSIS
  Set connected Windows network profiles to Private.

  N1MM Logger+ (and the gold-image firewall prompt) allow inbound on Private
  and block on Public. After a VM clone, Ethernet often comes up Public, so
  stations appear via UDP discovery but TCP 12070 send/receive stays red.

.NOTES
  ASCII-only. Run elevated. DomainAuthenticated profiles are left alone.
#>
[CmdletBinding()]
param(
    [switch] $NoElevate
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Status([string] $kind, [string] $msg) {
    $color = @{ OK = "Green"; WARN = "Yellow"; FAIL = "Red"; INFO = "Cyan" }[$kind]
    if (-not $color) { $color = "White" }
    $line = "[{0}] {1}" -f $kind, $msg
    try { Write-Host $line -ForegroundColor $color } catch { Write-Output $line }
}

if (-not (Test-IsAdmin)) {
    if ($NoElevate) {
        Write-Status FAIL "Administrator required to set network category to Private."
        exit 1
    }
    Write-Status INFO "Elevating (UAC) to set contest LAN Private..."
    $self = $MyInvocation.MyCommand.Path
    $p = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $self, "-NoElevate"
    )
    exit $p.ExitCode
}

if (-not (Get-Command Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
    Write-Status FAIL "Get-NetConnectionProfile is not available on this Windows."
    exit 1
}

try {
    $profiles = @(Get-NetConnectionProfile -ErrorAction Stop)
} catch {
    Write-Status FAIL "Get-NetConnectionProfile failed: $_"
    exit 1
}

if ($profiles.Count -eq 0) {
    Write-Status WARN "No connection profiles found."
    exit 1
}

$failed = 0
$changed = 0
foreach ($p in $profiles) {
    $alias = [string]$p.InterfaceAlias
    $name = [string]$p.Name
    $cat = [string]$p.NetworkCategory
    $label = "{0} ({1})" -f $alias, $name
    if ($cat -eq "Private") {
        Write-Status OK "$label already Private - N1MM Private allow-rules apply."
        continue
    }
    if ($cat -eq "DomainAuthenticated") {
        Write-Status OK "$label is DomainAuthenticated - leaving as-is."
        continue
    }
    try {
        Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private -ErrorAction Stop
        Write-Status OK "$label $cat -> Private"
        $changed += 1
    } catch {
        Write-Status FAIL "Could not set $label $cat -> Private: $_"
        $failed += 1
    }
}

if ($failed -gt 0) { exit 1 }
if ($changed -gt 0) {
    Write-Status INFO "Restart N1MM (or Close and Open connection in Network Status) so TCP 12070 retries."
}
exit 0
