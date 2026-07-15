#Requires -Version 5.1
<#
.SYNOPSIS
  Install WIMS prerequisites on Windows 10/11 (template / lab server).

.DESCRIPTION
  - Ensures Python 3.10+ (stdlib-only runtime; no pip packages required)
  - Obtains the WIMS tree (git clone, or -RepoPath / -SkipClone)
  - Writes scripts\windows\Start-WimsServer.ps1
  - Optionally opens Windows Firewall for TCP 8787
  - Optionally creates a Desktop shortcut

  Does NOT install N1MM, WSJT-X, or GridTracker (radio seat apps).
  Operator seats only need a browser to the server console.

.PARAMETER RepoPath
  Where WIMS should live. Default: $env:USERPROFILE\src\WIMS

.PARAMETER RepoUrl
  Git clone URL if RepoPath is missing.

.PARAMETER SkipFirewall
  Do not add a firewall rule for port 8787.

.PARAMETER SkipShortcut
  Do not create a Desktop shortcut.

.PARAMETER SkipClone
  Require an existing tree at -RepoPath (no git clone).

.EXAMPLE
  Set-ExecutionPolicy -Scope Process Bypass -Force
  .\Install-Wims.ps1

.EXAMPLE
  .\Install-Wims.ps1 -RepoPath D:\WIMS -SkipClone
#>
[CmdletBinding()]
param(
    [string] $RepoPath = (Join-Path $env:USERPROFILE "src\WIMS"),
    [string] $RepoUrl = "https://github.com/wa1hco/WIMS.git",
    [switch] $SkipFirewall,
    [switch] $SkipShortcut,
    [switch] $SkipClone
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Find-Python {
    foreach ($name in @("py", "python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($name -eq "py") {
                $ver = & py -3 -c "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    return @{ Exe = "py"; UsePyLauncher = $true; Version = $ver.Trim() }
                }
            } else {
                $ver = & $cmd.Source -c "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    return @{ Exe = $cmd.Source; UsePyLauncher = $false; Version = $ver.Trim() }
                }
            }
        } catch { }
    }
    return $null
}

function Install-Python {
    Write-Step "Installing Python (winget)…"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget not found. Install Python 3.12+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run."
    }
    $ids = @("Python.Python.3.12", "Python.Python.3.13", "Python.Python.3.11", "Python.Python.3.10")
    $ok = $false
    foreach ($id in $ids) {
        Write-Host "    trying $id …"
        & winget install -e --id $id --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    }
    if (-not $ok) {
        throw "winget could not install Python. Install manually from python.org and re-run."
    }
    Update-SessionPath
    Write-Ok "Python package installed; PATH refreshed for this session."
}

function Ensure-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "git present"
        return
    }
    Write-Step "Installing Git (winget)…"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "git not found and winget unavailable. Install Git for Windows, then re-run."
    }
    & winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git installed but not on PATH yet — open a new PowerShell and re-run."
    }
    Write-Ok "git installed."
}

function Invoke-Python {
    param([Parameter(Mandatory)] $PyInfo, [Parameter(Mandatory)][string[]] $PyArgs)
    if ($PyInfo.UsePyLauncher) {
        & py -3 @PyArgs
    } else {
        & $PyInfo.Exe @PyArgs
    }
}

# --- main ---
Write-Host "WIMS Windows install" -ForegroundColor White
Write-Host "RepoPath = $RepoPath"

if (-not (Test-IsAdmin)) {
    Write-Warn "Not running as Administrator. winget/firewall may prompt or fail; elevate if needed."
}

Write-Step "Checking Python >= 3.10…"
$py = Find-Python
if (-not $py) {
    Install-Python
    $py = Find-Python
}
if (-not $py) { throw "Python still not found after install." }
$parts = $py.Version.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Need Python 3.10+, found $($py.Version)"
}
Write-Ok "Python $($py.Version)"

Write-Step "WIMS source tree…"
$marker = Join-Path $RepoPath "src\wims\server\app.py"
if (Test-Path $marker) {
    Write-Ok "Found existing tree at $RepoPath"
    if (-not $SkipClone) {
        if ((Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $RepoPath ".git"))) {
            Push-Location $RepoPath
            try {
                git pull --ff-only 2>$null
                if ($LASTEXITCODE -eq 0) { Write-Ok "git pull ok" } else { Write-Warn "git pull skipped/failed (ok if offline)" }
            } finally { Pop-Location }
        }
    }
} elseif ($SkipClone) {
    throw "RepoPath missing app.py and -SkipClone was set: $RepoPath"
} else {
    Ensure-Git
    $parent = Split-Path -Parent $RepoPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    if (Test-Path $RepoPath) { throw "Path exists but is not a WIMS tree: $RepoPath" }
    Write-Host "    git clone $RepoUrl -> $RepoPath"
    git clone $RepoUrl $RepoPath
    if (-not (Test-Path $marker)) { throw "Clone succeeded but $marker missing." }
    Write-Ok "Cloned."
}

Write-Step "Writing Start-WimsServer.ps1…"
$launcherDir = Join-Path $RepoPath "scripts\windows"
if (-not (Test-Path $launcherDir)) { New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null }
$launcher = Join-Path $launcherDir "Start-WimsServer.ps1"

if ($py.UsePyLauncher) {
    $runPy = "py -3"
} else {
    $runPy = "& '" + ($py.Exe -replace "'", "''") + "'"
}

$launcherBody = @"
# Start WIMS server (stdlib only). Generated/updated by Install-Wims.ps1.
`$ErrorActionPreference = "Stop"
`$Root = (Resolve-Path (Join-Path `$PSScriptRoot "..\..")).Path
Set-Location `$Root
`$env:PYTHONPATH = Join-Path `$Root "src"

`$Iface = "0.0.0.0"
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { `$_.IPAddress -notlike "127.*" -and `$_.IPAddress -notlike "169.254.*" } |
  Select-Object -First 1 |
  ForEach-Object { `$Iface = `$_.IPAddress }

`$N1mmGroup = "224.0.0.73"
`$HttpPort = 8787

Write-Host "WIMS root: `$Root"
Write-Host "  iface=`$Iface  n1mm-group=`$N1mmGroup  http=:`$HttpPort"
Write-Host "  Operate  http://localhost:`$HttpPort/"
Write-Host "  Status   http://localhost:`$HttpPort/status"
Write-Host "  Setup    http://localhost:`$HttpPort/setup"
Write-Host "  Remote   http://<this-host-ip>:`$HttpPort/"
Write-Host ""

$runPy -m wims.server.app --iface `$Iface --n1mm-group `$N1mmGroup --http-port `$HttpPort @args
"@
Set-Content -Path $launcher -Value $launcherBody -Encoding UTF8
Write-Ok $launcher

if (-not $SkipFirewall) {
    Write-Step "Windows Firewall (TCP 8787)…"
    if (-not (Test-IsAdmin)) {
        Write-Warn "Skip firewall (need Administrator). Allow TCP 8787 for remote browsers."
    } else {
        $ruleName = "WIMS console HTTP 8787"
        if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
            Write-Ok "Rule already present: $ruleName"
        } else {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
                -LocalPort 8787 -Action Allow -Profile Any | Out-Null
            Write-Ok "Added inbound allow TCP 8787"
        }
    }
}

if (-not $SkipShortcut) {
    Write-Step "Desktop shortcut…"
    $desk = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desk "WIMS Server.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($lnkPath)
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`""
    $lnk.WorkingDirectory = $RepoPath
    $lnk.Description = "Start WIMS server"
    $lnk.Save()
    Write-Ok $lnkPath
}

Write-Step "Smoke test (import wims)…"
$env:PYTHONPATH = Join-Path $RepoPath "src"
Invoke-Python -PyInfo $py -PyArgs @("-c", "import wims.server.app; print('import ok')")
if ($LASTEXITCODE -ne 0) { throw "import failed" }
Write-Ok "import ok"

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Start:  powershell -ExecutionPolicy Bypass -File `"$launcher`""
Write-Host "  Or double-click Desktop 'WIMS Server'."
Write-Host "  Contest log: copy N1MM .s3db into Documents\N1MM Logger+\Databases then open Setup."
Write-Host "  Other seats: browser only -> http://<server-ip>:8787/ (no install required)."
Write-Host ""
