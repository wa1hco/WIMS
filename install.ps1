#Requires -Version 5.1

# install.ps1 - WIMS install / update for Windows (repo-root entry).
#
# Run from inside the cloned or unpacked tree:
#
#     git clone https://github.com/wa1hco/WIMS.git C:\WIMS
#     cd C:\WIMS
#     .\install.ps1
#
# Or after unpacking a GitHub Release ZIP, from that folder:
#
#     .\install.ps1
#
# Thin wrapper around scripts\windows\Install-Wims.ps1 so the map144-style
# root entry works. Prefer Install-Wims.cmd (UAC elevation) when double-clicking;
# this script is for PowerShell / scripted installs.
#
# Keep ASCII-only + CRLF (Windows PowerShell 5.1).

[CmdletBinding()]
param(
    [string] $RepoPath = "",
    [string] $RepoUrl = "https://github.com/wa1hco/WIMS.git",
    [string] $LogPath = "",
    [switch] $SkipFirewall,
    [switch] $SkipShortcut,
    [switch] $SkipClone
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $PSScriptRoot).Path
$Inner = Join-Path $RepoRoot "scripts\windows\Install-Wims.ps1"
if (-not (Test-Path -LiteralPath $Inner)) {
    throw "Missing $Inner — not a full WIMS tree?"
}

if (-not $RepoPath) {
    $RepoPath = $RepoRoot
}

# Release ZIP trees have no .git; do not attempt clone into a filled folder.
$marker = Join-Path $RepoPath "src\wims\server\app.py"
if ((Test-Path -LiteralPath $marker) -and -not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) {
    $SkipClone = $true
}

$forward = @{
    RepoPath     = $RepoPath
    RepoUrl      = $RepoUrl
    SkipFirewall = $SkipFirewall
    SkipShortcut = $SkipShortcut
    SkipClone    = $SkipClone
}
if ($LogPath) { $forward["LogPath"] = $LogPath }

& $Inner @forward
exit $LASTEXITCODE
