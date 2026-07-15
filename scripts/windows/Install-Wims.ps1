#Requires -Version 5.1
<#
.SYNOPSIS
  Install WIMS prerequisites on Windows (Python, optional Git, firewall, launchers).

  Always writes a log: scripts\windows\install-log.txt
  Exit 0 only if python.exe is found AND import wims succeeds.
#>
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
$script:LogFile = $null

function Log([string] $msg, [string] $color = "White") {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    try { Write-Host $line -ForegroundColor $color } catch { Write-Output $line }
    if ($script:LogFile) {
        try { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 } catch { }
    }
}
function Step($m) { Log "==> $m" "Cyan" }
function Ok($m)   { Log "    OK: $m" "Green" }
function Warn($m) { Log "    WARN: $m" "Yellow" }
function Fail($m) { Log "    FAIL: $m" "Red" }

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    # Common Git/Python dirs if still missing from Path env
    foreach ($extra in @(
        "${env:ProgramFiles}\Python312",
        "${env:ProgramFiles}\Python313",
        "${env:LocalAppData}\Programs\Python\Python312",
        "${env:LocalAppData}\Programs\Python\Python313",
        "${env:ProgramFiles}\Git\cmd",
        "${env:LocalAppData}\Programs\Git\cmd"
    )) {
        if ((Test-Path $extra) -and ($env:Path -notlike "*$extra*")) {
            $env:Path = "$extra;$env:Path"
        }
    }
}

function Test-PythonExe([string] $Exe) {
    if (-not $Exe) { return $null }
    $Exe = $Exe.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }
    # Reject Windows Store stub
    if ($Exe -match "WindowsApps\\python") { return $null }
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList @("-c", "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1])); print(sys.executable)") `
            -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\wims-py-out.txt" -RedirectStandardError "$env:TEMP\wims-py-err.txt"
        if ($p.ExitCode -ne 0) { return $null }
        $lines = Get-Content "$env:TEMP\wims-py-out.txt" -ErrorAction SilentlyContinue
        if (-not $lines -or $lines.Count -lt 1) { return $null }
        $ver = $lines[0].Trim()
        $parts = $ver.Split(".")
        if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) { return $null }
        $resolved = $Exe
        if ($lines.Count -ge 2 -and (Test-Path $lines[1].Trim())) { $resolved = $lines[1].Trim() }
        return @{ Exe = $resolved; Version = $ver }
    } catch {
        return $null
    }
}

function Find-Python {
    Update-SessionPath
    Log "    Searching for python.exe…"

    # py -3
    try {
        $out = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $info = Test-PythonExe $out.Trim()
            if ($info) { Log "    found via py -3: $($info.Exe)"; return $info }
        }
    } catch { }

    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $info = Test-PythonExe $cmd.Source
            if ($info) { Log "    found on PATH: $($info.Exe)"; return $info }
        }
    }

    $searchRoots = @(
        "$env:LocalAppData\Programs\Python",
        "$env:ProgramFiles\Python312",
        "$env:ProgramFiles\Python313",
        "$env:ProgramFiles\Python311",
        "$env:ProgramFiles\Python310",
        "${env:ProgramFiles(x86)}\Python312",
        "$env:ProgramFiles"
    )
    $found = @()
    foreach ($root in $searchRoots) {
        if (-not (Test-Path $root)) { continue }
        try {
            $found += Get-ChildItem -Path $root -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue -Depth 4 |
                Where-Object { $_.FullName -notmatch "\\Lib\\|WindowsApps|\\Scripts\\" } |
                ForEach-Object { $_.FullName }
        } catch { }
    }

    foreach ($hive in @(
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKCU:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore"
    )) {
        if (-not (Test-Path $hive)) { continue }
        Get-ChildItem $hive -ErrorAction SilentlyContinue | ForEach-Object {
            $ip = Join-Path $_.PSPath "InstallPath"
            try {
                $dir = (Get-ItemProperty -LiteralPath $ip -ErrorAction SilentlyContinue).'(default)'
                if ($dir) { $found += (Join-Path $dir "python.exe") }
            } catch { }
        }
    }

    foreach ($c in ($found | Select-Object -Unique)) {
        $info = Test-PythonExe $c
        if ($info) { Log "    found on disk: $($info.Exe)"; return $info }
    }
    Log "    no suitable python.exe found"
    return $null
}

function Install-PythonWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Warn "winget not available"
        return $false
    }
    Step "Trying winget Python install…"
    $ids = @("Python.Python.3.12", "Python.Python.3.13", "Python.Python.3.11")
    foreach ($id in $ids) {
        Log "    winget install -e --id $id"
        $args = @("install", "-e", "--id", $id, "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity")
        if (Test-IsAdmin) { $args += @("--scope", "machine") }
        & winget @args 2>&1 | ForEach-Object { Log "      $_" }
        $code = $LASTEXITCODE
        Log "    winget exit code: $code"
        # 0 success; -1978335189 already installed
        Update-SessionPath
        Start-Sleep -Seconds 3
        $py = Find-Python
        if ($py) { Ok "winget provided Python $($py.Version)"; return $true }
    }
    return $false
}

function Get-PythonInstaller {
    $ver = "3.12.8"
    $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
    $tmp = Join-Path $env:TEMP "wims-python-$ver-amd64.exe"
    if ((Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 10MB)) {
        Log "    using cached installer: $tmp"
        return $tmp
    }
    Log "    downloading $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    } catch {
        Log "    Invoke-WebRequest failed: $_"
        Log "    trying bitsadmin…"
        & bitsadmin /transfer WimsPython /download /priority foreground $url $tmp
        if (-not (Test-Path $tmp)) { throw "Could not download Python installer: $_" }
    }
    if (-not (Test-Path $tmp) -or ((Get-Item $tmp).Length -lt 1MB)) {
        throw "Python installer download incomplete: $tmp"
    }
    Log "    downloaded $([math]::Round((Get-Item $tmp).Length/1MB,1)) MB"
    return $tmp
}

function Install-PythonOfficial {
    Step "Installing Python 3.12.8 (official silent installer)…"
    $tmp = Get-PythonInstaller

    # Default install dir when InstallAllUsers=1
    $targetDir = Join-Path $env:ProgramFiles "Python312"
    if (-not (Test-IsAdmin)) {
        $targetDir = Join-Path $env:LocalAppData "Programs\Python\Python312"
    }

    # Critical: PrependPath + Include_launcher; ExplicitTargetDir for predictability
    $arg = @(
        "/quiet",
        "InstallAllUsers=$(if (Test-IsAdmin) { '1' } else { '0' })",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_test=0",
        "Include_pip=1",
        "Include_doc=0",
        "SimpleInstall=1",
        "TargetDir=`"$targetDir`""
    ) -join " "

    Log "    installer: $tmp"
    Log "    args: $arg"
    Log "    target: $targetDir"

    $p = Start-Process -FilePath $tmp -ArgumentList $arg -Wait -PassThru
    Log "    installer exit code: $($p.ExitCode)"
    # 0 = ok, 3010 = reboot recommended but often still installed
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        Fail "Official installer failed with code $($p.ExitCode)"
        return $false
    }

    Update-SessionPath
    Start-Sleep -Seconds 3

    # Direct check of TargetDir even if PATH broken
    $direct = Join-Path $targetDir "python.exe"
    $info = Test-PythonExe $direct
    if ($info) { Ok "Python at $direct"; return $true }

    $info = Find-Python
    if ($info) { Ok "Python at $($info.Exe)"; return $true }

    Fail "Installer reported success but python.exe not found under $targetDir"
    return $false
}

function Ensure-Python {
    Step "Python prerequisite"
    $py = Find-Python
    if ($py) {
        Ok "Already installed: $($py.Exe) ($($py.Version))"
        return $py
    }
    Warn "Python not found — installing…"

    if (Install-PythonWinget) {
        $py = Find-Python
        if ($py) { return $py }
    }

    if (Install-PythonOfficial) {
        $py = Find-Python
        if ($py) { return $py }
        # Last chance: known target paths
        foreach ($p in @(
            "$env:ProgramFiles\Python312\python.exe",
            "$env:LocalAppData\Programs\Python\Python312\python.exe"
        )) {
            $info = Test-PythonExe $p
            if ($info) { return $info }
        }
    }

    throw @"
Python could not be installed automatically.

Try manually:
  1. Download https://www.python.org/downloads/windows/
  2. Run installer, check BOTH:
       - Add python.exe to PATH
       - Install for all users (if you can)
  3. Reboot or open a new cmd window
  4. Double-click Install-Wims.cmd again

Log: $script:LogFile
"@
}

function Ensure-Git {
    Update-SessionPath
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Ok "git already present"
        return
    }
    Step "Installing Git…"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $args = @("install", "-e", "--id", "Git.Git", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity")
        if (Test-IsAdmin) { $args += @("--scope", "machine") }
        & winget @args 2>&1 | ForEach-Object { Log "      $_" }
        Update-SessionPath
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        foreach ($g in @(
            "$env:ProgramFiles\Git\cmd\git.exe",
            "$env:LocalAppData\Programs\Git\cmd\git.exe"
        )) {
            if (Test-Path $g) {
                $env:Path = "$(Split-Path $g);$env:Path"
                break
            }
        }
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git not available. Install from https://git-scm.com/download/win and re-run."
    }
    Ok "git ready"
}

function Set-Firewall8787 {
    Step "Firewall TCP 8787 (inbound)"
    if (-not (Test-IsAdmin)) {
        Warn "Not admin — cannot change firewall. Other PCs may not reach the console."
        Warn "Re-run Install-Wims.cmd and accept UAC, or run as Administrator."
        return $false
    }
    $ruleName = "WIMS console HTTP 8787"
    $ok = $false

    # Method 1: PowerShell NetSecurity
    try {
        if (Get-Command Get-NetFirewallRule -ErrorAction SilentlyContinue) {
            $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            if ($existing) {
                Ok "Firewall rule already exists: $ruleName"
                $ok = $true
            } else {
                New-NetFirewallRule -DisplayName $ruleName -Name "WIMS-HTTP-8787" `
                    -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow `
                    -Profile Any -ErrorAction Stop | Out-Null
                Ok "Added rule via New-NetFirewallRule"
                $ok = $true
            }
        }
    } catch {
        Warn "New-NetFirewallRule failed: $_"
    }

    # Method 2: netsh (works when NetFirewall cmdlets fail)
    if (-not $ok) {
        try {
            $out = & netsh advfirewall firewall show rule name="$ruleName" 2>&1 | Out-String
            if ($out -match "WIMS console") {
                Ok "netsh: rule already exists"
                $ok = $true
            } else {
                & netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=8787 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Ok "Added rule via netsh advfirewall"
                    $ok = $true
                } else {
                    Fail "netsh add rule exit $LASTEXITCODE"
                }
            }
        } catch {
            Fail "netsh failed: $_"
        }
    }

    # Verify
    try {
        $check = & netsh advfirewall firewall show rule name="$ruleName" 2>&1 | Out-String
        Log "    netsh show rule:`n$check"
        if ($check -match "8787|Allow") { Ok "Firewall rule verified" } else { Warn "Could not verify firewall rule" }
    } catch { }

    return $ok
}

function Write-StartCmd([string] $PythonExe, [string] $OutCmd) {
    $py = $PythonExe
    $body = @"
@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0..\.."
pushd "%ROOT%" 2>nul || (echo Bad repo root & pause & exit /b 1)
set "ROOT=%CD%"
popd
set "PYTHONPATH=%ROOT%\src"
cd /d "%ROOT%"

set "PYTHON_EXE=$py"
if not exist "%PYTHON_EXE%" (
  echo Python missing: %PYTHON_EXE%
  echo Run Install-Wims.cmd again.
  pause
  exit /b 1
)

set "IFACE=0.0.0.0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { `$_.IPAddress -notlike '127.*' -and `$_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress } catch { '0.0.0.0' }"`) do set "IFACE=%%I"

echo.
echo  WIMS: %ROOT%
echo  Python: %PYTHON_EXE%
echo  iface=%IFACE%  http://localhost:8787/
echo.

"%PYTHON_EXE%" -m wims.server.app --iface %IFACE% --n1mm-group 224.0.0.73 --http-port 8787 %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 ( echo Exit %ERR% & pause )
exit /b %ERR%
"@
    Set-Content -Path $OutCmd -Value $body -Encoding ASCII
}

# ========== main ==========
try {
    # Prefer caller-supplied log path so elevated + non-elevated share one file.
    if ($LogPath) {
        $script:LogFile = $LogPath
    } elseif ($PSScriptRoot) {
        $script:LogFile = Join-Path $PSScriptRoot "install-log.txt"
    } else {
        $script:LogFile = Join-Path $env:TEMP "wims-install-log.txt"
    }
    $logDir = Split-Path -Parent $script:LogFile
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Add-Content -LiteralPath $script:LogFile -Value "" -Encoding UTF8
    Add-Content -LiteralPath $script:LogFile -Value "==== PS1 start $(Get-Date -Format o) ====" -Encoding UTF8

    if (-not $RepoPath) {
        if ($PSScriptRoot) {
            $candidate = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
            if (Test-Path (Join-Path $candidate "src\wims\server\app.py")) {
                $RepoPath = $candidate
            }
        }
        if (-not $RepoPath) { $RepoPath = Join-Path $env:USERPROFILE "src\WIMS" }
    }

    Log "WIMS Windows install starting (elevated child or direct)"
    Log "RepoPath = $RepoPath"
    Log "Admin    = $(Test-IsAdmin)"
    Log "User     = $env:USERNAME"
    Log "Log file = $script:LogFile"
    Log "PSScriptRoot = $PSScriptRoot"

    if (-not (Test-IsAdmin)) {
        Warn "NOT running as Administrator."
        Warn "Python may install only for this user; firewall will be SKIPPED."
        Warn "For a template image: right-click Install-Wims.cmd -> Run as administrator"
    }

    $py = Ensure-Python

    Step "WIMS source tree"
    $marker = Join-Path $RepoPath "src\wims\server\app.py"
    if (Test-Path $marker) {
        Ok "Tree present: $RepoPath"
        if (-not $SkipClone -and (Test-Path (Join-Path $RepoPath ".git"))) {
            if (Get-Command git -ErrorAction SilentlyContinue) {
                Push-Location $RepoPath
                try {
                    git pull --ff-only 2>&1 | ForEach-Object { Log "      $_" }
                } finally { Pop-Location }
            }
        }
    } elseif ($SkipClone) {
        throw "No WIMS tree at $RepoPath and -SkipClone set"
    } else {
        Ensure-Git
        $parent = Split-Path -Parent $RepoPath
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if (Test-Path $RepoPath) { throw "Path exists but is not WIMS: $RepoPath" }
        Log "    git clone $RepoUrl"
        git clone $RepoUrl $RepoPath 2>&1 | ForEach-Object { Log "      $_" }
        if (-not (Test-Path $marker)) { throw "Clone missing $marker" }
        Ok "Cloned"
    }

    $launcherDir = Join-Path $RepoPath "scripts\windows"
    if (-not (Test-Path $launcherDir)) { New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null }

    # Keep log next to launchers in the real repo
    $repoLog = Join-Path $launcherDir "install-log.txt"
    if ($script:LogFile -ne $repoLog) {
        Copy-Item $script:LogFile $repoLog -Force -ErrorAction SilentlyContinue
        $script:LogFile = $repoLog
    }

    Step "Writing Start-WimsServer.cmd with pinned Python"
    $startCmd = Join-Path $launcherDir "Start-WimsServer.cmd"
    Write-StartCmd -PythonExe $py.Exe -OutCmd $startCmd
    Set-Content (Join-Path $launcherDir "python-path.txt") $py.Exe -Encoding ASCII
    Ok "Pinned: $($py.Exe)"
    Ok $startCmd

    $fwOk = $true
    if (-not $SkipFirewall) {
        $fwOk = Set-Firewall8787
    }

    if (-not $SkipShortcut) {
        Step "Desktop shortcut"
        try {
            $desk = [Environment]::GetFolderPath("Desktop")
            $lnkPath = Join-Path $desk "WIMS Server.lnk"
            $wsh = New-Object -ComObject WScript.Shell
            $lnk = $wsh.CreateShortcut($lnkPath)
            $lnk.TargetPath = $startCmd
            $lnk.WorkingDirectory = $RepoPath
            $lnk.Description = "Start WIMS server"
            $lnk.Save()
            Ok $lnkPath
        } catch { Warn "Shortcut failed: $_" }
    }

    Step "Smoke test"
    $env:PYTHONPATH = Join-Path $RepoPath "src"
    $p = Start-Process -FilePath $py.Exe -ArgumentList @("-c", "import wims.server.app; print('import ok')") `
        -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\wims-smoke.txt" -RedirectStandardError "$env:TEMP\wims-smoke-err.txt"
    $smokeOut = Get-Content "$env:TEMP\wims-smoke.txt" -Raw -ErrorAction SilentlyContinue
    $smokeErr = Get-Content "$env:TEMP\wims-smoke-err.txt" -Raw -ErrorAction SilentlyContinue
    Log "    stdout: $smokeOut"
    if ($smokeErr) { Log "    stderr: $smokeErr" }
    if ($p.ExitCode -ne 0) { throw "import wims failed (exit $($p.ExitCode))" }
    Ok "import wims.server.app"

    Log ""
    Log "========== RESULT ==========" "Green"
    Log "SUCCESS" "Green"
    Log "  Python : $($py.Exe) ($($py.Version))" "Green"
    Log "  Start  : $startCmd" "Green"
    Log "  Firewall 8787: $(if ($fwOk) { 'OK or already set' } else { 'NOT SET — re-run as Admin' })" $(if ($fwOk) { "Green" } else { "Yellow" })
    Log "  Log    : $script:LogFile" "Green"
    Log "Next: double-click Start-WimsServer.cmd" "Green"
    exit 0
}
catch {
    Fail "$_"
    if ($script:LogFile) { Log "See log: $script:LogFile" "Red" }
    exit 1
}
