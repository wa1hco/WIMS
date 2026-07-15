# WIMS on Windows

## Roles

| Machine | Needs |
|---------|--------|
| **WIMS server** (one per site/lab) | This install + Python; opens TCP **8787** |
| **Radio seat** (N1MM + WSJT-X) | N1MM / WSJT-X / optional GridTracker; **browser** to the server. WIMS install optional |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` |

## Quick install (Win10 template)

1. Open **PowerShell as Administrator** (winget + firewall).
2. Clone or copy the repo, then:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd $env:USERPROFILE\src\WIMS   # or wherever the repo is
.\scripts\windows\Install-Wims.ps1
```

Or clone via the installer (git + Python via winget):

```powershell
# Save Install-Wims.ps1 from the repo, then:
.\Install-Wims.ps1
# Default clone: %USERPROFILE%\src\WIMS
```

### Offline / USB tree

```powershell
.\Install-Wims.ps1 -RepoPath D:\WIMS -SkipClone
```

## After install

```powershell
.\scripts\windows\Start-WimsServer.ps1
```

- Operate: `http://localhost:8787/`
- Status:  `http://localhost:8787/status`
- Setup:   `http://localhost:8787/setup` (contest log picker)

Copy the contest **`.s3db`** into `Documents\N1MM Logger+\Databases` on the **server** machine (or use Setup → Rescan after copy).

## Prerequisites the script installs

| Component | How |
|-----------|-----|
| Python ≥ 3.10 | `winget` (`Python.Python.3.12` preferred) |
| Git | `winget` (`Git.Git`) if cloning |
| Firewall TCP 8787 | `New-NetFirewallRule` (admin) |

**Not** installed: N1MM, WSJT-X, GridTracker, Icom USB drivers.

## Radio seat checklist (no WIMS install)

1. WSJT-X: multicast + **Outgoing interface = LAN**
2. N1MM: Broadcast Data → WIMS host or `224.0.0.73:12060`
3. Browser → `http://<wims-server-ip>:8787/`

See [docs/plan/wims_networking.md](../../docs/plan/wims_networking.md).
