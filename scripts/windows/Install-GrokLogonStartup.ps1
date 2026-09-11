# User Startup shortcut: Grok CLI in the WIMS tree, --always-approve (no tool prompts).
param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $here "Start-GrokAtLogon.vbs"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$grok = Join-Path $env:USERPROFILE ".grok\bin\grok.exe"

if (-not (Test-Path -LiteralPath $vbs)) {
    Write-Host "ERROR: Start-GrokAtLogon.vbs missing." -ForegroundColor Red
    if (-not $NoPause) { pause }
    exit 1
}
if (-not (Test-Path -LiteralPath $grok)) {
    Write-Host "ERROR: grok.exe not found: $grok" -ForegroundColor Red
    Write-Host "Install Grok CLI and run grok login once."
    if (-not $NoPause) { pause }
    exit 1
}

$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
if (-not (Test-Path -LiteralPath $startup)) {
    New-Item -ItemType Directory -Path $startup -Force | Out-Null
}
$lnk = Join-Path $startup "Grok CLI.lnk"
$vbsAbs = (Resolve-Path -LiteralPath $vbs).Path

$wsh = New-Object -ComObject WScript.Shell
$s = $wsh.CreateShortcut($lnk)
$s.TargetPath = $wscript
$s.Arguments = "//nologo `"$vbsAbs`""
$s.WorkingDirectory = $here
$s.WindowStyle = 7
$s.Description = "Grok CLI at logon (always-approve, cwd WIMS tree)"
$s.Save()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null

Write-Host " Startup: $lnk"
Write-Host " Logon starts: grok --always-approve --cwd <WIMS repo>"
Write-Host " Tools run without permission prompts. Deny rules still apply."
Write-Host " Remove: del `"$lnk`""
if (-not $NoPause) { pause }
exit 0
