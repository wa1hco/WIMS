#Requires -Version 5.1
<#
.SYNOPSIS
  Install ALL WIMS server prerequisites on Windows 10/11 and wire launchers.

.DESCRIPTION
  Installs (if missing):
    - Python 3.10+ (winget, then official silent installer fallback)
    - Git (winget; only if cloning)
  Then:
    - Ensures WIMS source tree (clone or -RepoPath)
    - Writes Start-WimsServer.cmd with the FULL path to python.exe
      (so start works even when PATH was not refreshed)
    - Firewall TCP 8787, Desktop shortcut

  Double-click Install-Wims.cmd (preferred). Pass -RepoPath when the tree
  is not under %USERPROFILE%\src\WIMS.
#>
[CmdletBinding()]
param(
    [string] $RepoPath = "",
    [string] $RepoUrl = "https://github.com/wa1hco/WIMS.git",
    [switch] $SkipFirewall,
    [switch] $SkipShortcut,
    [switch] $SkipClone
)

$ErrorActionPreference = "Stop"

# If launched from scripts\windows without -RepoPath, use repo root (two levels up).
if (-not $RepoPath) {
    if ($PSScriptRoot) {
        $candidate = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
        if (Test-Path (Join-Path $candidate "src\wims\server\app.py")) {
            $RepoPath = $candidate
        }
    }
    if (-not $RepoPath) {
        $RepoPath = Join-Path $env:USERPROFILE "src\WIMS"
    }
}

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

function Test-PythonExe([string] $Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $null }
    try {
        $ver = & $Exe -c "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { return $null }
        $parts = $ver.Trim().Split(".")
        $maj = [int]$parts[0]; $min = [int]$parts[1]
        if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 10)) { return $null }
        return @{ Exe = (Resolve-Path -LiteralPath $Exe).Path; Version = $ver.Trim() }
    } catch { return $null }
}

function Find-Python {
    Update-SessionPath

    # 1) py launcher
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                $info = Test-PythonExe $exe.Trim()
                if ($info) { return $info }
            }
        } catch { }
    }

    # 2) python on PATH
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notmatch "WindowsApps\\python") {
            $info = Test-PythonExe $cmd.Source
            if ($info) { return $info }
        }
    }

    # 3) Well-known install locations (PATH often stale after winget/silent install)
    $roots = @(
        "${env:LocalAppData}\Programs\Python",
        "${env:ProgramFiles}\Python*",
        "${env:ProgramFiles(x86)}\Python*",
        "${env:ProgramFiles}\Python312",
        "${env:ProgramFiles}\Python313",
        "${env:ProgramFiles}\Python311",
        "${env:ProgramFiles}\Python310",
        "${env:LocalAppData}\Programs\Python\Python312",
        "${env:LocalAppData}\Programs\Python\Python313",
        "${env:LocalAppData}\Programs\Python\Python311",
        "${env:LocalAppData}\Programs\Python\Python310"
    )
    $candidates = @()
    foreach ($r in $roots) {
        $candidates += Get-ChildItem -Path $r -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch "\\Lib\\|\\Scripts\\pythonw" } |
            Select-Object -ExpandProperty FullName
    }
    # Also: py.ini / registry
    foreach ($hive in @("HKLM:\SOFTWARE\Python\PythonCore", "HKCU:\SOFTWARE\Python\PythonCore")) {
        if (Test-Path $hive) {
            Get-ChildItem $hive -ErrorAction SilentlyContinue | ForEach-Object {
                $ip = Join-Path $_.PSPath "InstallPath"
                try {
                    $dir = (Get-ItemProperty $ip -ErrorAction SilentlyContinue)."(default)"
                    if ($dir) { $candidates += (Join-Path $dir "python.exe") }
                } catch { }
            }
        }
    }

    foreach ($c in ($candidates | Select-Object -Unique)) {
        $info = Test-PythonExe $c
        if ($info) { return $info }
    }
    return $null
}

function Install-PythonViaWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }

    Write-Step "Installing Python via winget…"
    $ids = @("Python.Python.3.12", "Python.Python.3.13", "Python.Python.3.11", "Python.Python.3.10")
    $scopeArgs = @()
    if (Test-IsAdmin) { $scopeArgs = @("--scope", "machine") }

    foreach ($id in $ids) {
        Write-Host "    winget install $id $($scopeArgs -join ' ') …"
        & winget install -e --id $id --accept-package-agreements --accept-source-agreements @scopeArgs
        # 0 = success, -1978335189 often "already installed"
        if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) {
            Update-SessionPath
            Start-Sleep -Seconds 2
            if (Find-Python) { Write-Ok "winget: $id available"; return $true }
        }
    }
    Write-Warn "winget finished but python.exe not found yet."
    return $false
}

function Install-PythonViaOfficialInstaller {
    Write-Step "Installing Python via official silent installer…"
    # Pin a known-good 3.12.x amd64 build (project requires >=3.10).
    $ver = "3.12.8"
    $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
    $tmp = Join-Path $env:TEMP "wims-python-$ver-amd64.exe"
    Write-Host "    downloading $url"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    } catch {
        throw "Download failed: $_. Install Python from https://www.python.org/downloads/ (tick Add to PATH) and re-run."
    }

    # InstallAllUsers when admin so all accounts / PATH are machine-wide.
    $targetArgs = if (Test-IsAdmin) {
        "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0 SimpleInstall=1"
    } else {
        "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 SimpleInstall=1"
    }
    Write-Host "    running silent installer…"
    $p = Start-Process -FilePath $tmp -ArgumentList $targetArgs -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        throw "Python installer exit code $($p.ExitCode). Try manual install from python.org."
    }
    Update-SessionPath
    Start-Sleep -Seconds 2
    if (-not (Find-Python)) {
        throw "Python installer finished but python.exe still not found. Sign out/in or reboot, then re-run Install-Wims.cmd."
    }
    Write-Ok "Python installed via python.org ($ver)"
    return $true
}

function Ensure-Python {
    Write-Step "Ensuring Python >= 3.10…"
    $py = Find-Python
    if ($py) {
        Write-Ok "Found Python $($py.Version) at $($py.Exe)"
        return $py
    }
    Write-Warn "Python not found — installing prerequisites…"
    $ok = Install-PythonViaWinget
    $py = Find-Python
    if ($py) {
        Write-Ok "Found Python $($py.Version) at $($py.Exe)"
        return $py
    }
    Install-PythonViaOfficialInstaller | Out-Null
    $py = Find-Python
    if (-not $py) { throw "Python install failed — still not found." }
    Write-Ok "Found Python $($py.Version) at $($py.Exe)"
    return $py
}

function Ensure-Git {
    Update-SessionPath
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "git present"
        return
    }
    Write-Step "Installing Git (winget)…"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "git not found and winget unavailable. Install Git for Windows, then re-run."
    }
    $scopeArgs = @()
    if (Test-IsAdmin) { $scopeArgs = @("--scope", "machine") }
    & winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements @scopeArgs
    Update-SessionPath
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        # Common path after machine install
        $guess = @(
            "${env:ProgramFiles}\Git\cmd\git.exe",
            "${env:LocalAppData}\Programs\Git\cmd\git.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($guess) {
            $env:Path = "$(Split-Path $guess);$env:Path"
        }
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git installed but not on PATH — open a new window or reboot, then re-run."
    }
    Write-Ok "git installed."
}

function Write-StartCmd([string] $PythonExe, [string] $OutCmd) {
    # Embed absolute python.exe so PATH refresh is never required to start WIMS.
    $pyEsc = $PythonExe -replace '%', '%%'
    $body = @"
@echo off
setlocal
REM Generated by Install-Wims.ps1 — uses full path to Python (no PATH dependency).
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul
if errorlevel 1 (
  echo Cannot find WIMS repo root.
  pause
  exit /b 1
)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

set "PYTHON_EXE=$pyEsc"
if not exist "%PYTHON_EXE%" (
  echo Python missing: %PYTHON_EXE%
  echo Re-run Install-Wims.cmd
  pause
  exit /b 1
)

set "IFACE=0.0.0.0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "IFACE=%%I"

set "N1MM_GROUP=224.0.0.73"
set "HTTP_PORT=8787"

echo.
echo  WIMS root: %ROOT%
echo  Python:    %PYTHON_EXE%
echo    iface=%IFACE%  n1mm-group=%N1MM_GROUP%  http=:%HTTP_PORT%
echo    Operate  http://localhost:%HTTP_PORT%/
echo    Status   http://localhost:%HTTP_PORT%/status
echo    Setup    http://localhost:%HTTP_PORT%/setup
echo.

"%PYTHON_EXE%" -m wims.server.app --iface %IFACE% --n1mm-group %N1MM_GROUP% --http-port %HTTP_PORT% %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo WIMS exited with code %ERR%.
  pause
)
exit /b %ERR%
"@
    Set-Content -Path $OutCmd -Value $body -Encoding ASCII
}

# --- main ---
Write-Host "WIMS Windows install" -ForegroundColor White
Write-Host "RepoPath = $RepoPath"
Write-Host "Admin    = $(Test-IsAdmin)"

if (-not (Test-IsAdmin)) {
    Write-Warn "Not Administrator: Python may install per-user only; firewall rule may be skipped."
    Write-Warn "Prefer double-click Install-Wims.cmd (requests UAC)."
}

$py = Ensure-Python

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

$launcherDir = Join-Path $RepoPath "scripts\windows"
if (-not (Test-Path $launcherDir)) { New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null }

Write-Step "Writing Start-WimsServer.cmd (pinned Python path)…"
$startCmd = Join-Path $launcherDir "Start-WimsServer.cmd"
Write-StartCmd -PythonExe $py.Exe -OutCmd $startCmd
Write-Ok "Python = $($py.Exe)"
Write-Ok $startCmd

# Remember path for debugging
Set-Content -Path (Join-Path $launcherDir "python-path.txt") -Value $py.Exe -Encoding ASCII

if (-not $SkipFirewall) {
    Write-Step "Windows Firewall (TCP 8787)…"
    if (-not (Test-IsAdmin)) {
        Write-Warn "Skip firewall (need Administrator)."
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
    $lnk.TargetPath = $startCmd
    $lnk.Arguments = ""
    $lnk.WorkingDirectory = $RepoPath
    $lnk.Description = "Start WIMS server"
    $lnk.Save()
    Write-Ok $lnkPath
}

Write-Step "Smoke test (import wims)…"
$env:PYTHONPATH = Join-Path $RepoPath "src"
& $py.Exe -c "import wims.server.app; print('import ok')"
if ($LASTEXITCODE -ne 0) { throw "import failed — PYTHONPATH=$($env:PYTHONPATH)" }
Write-Ok "import ok"

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Python:  $($py.Exe)  ($($py.Version))"
Write-Host "  Start:   double-click Start-WimsServer.cmd"
Write-Host "           $startCmd"
Write-Host "  Or Desktop 'WIMS Server'."
Write-Host "  Contest log: copy N1MM .s3db into Documents\N1MM Logger+\Databases then open Setup."
Write-Host ""
