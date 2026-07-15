# WIMS on Windows

## Roles

| Machine | Needs |
|---------|--------|
| **WIMS server** (one per site/lab) | This install + Python; opens TCP **8787** |
| **Radio seat** (N1MM + WSJT-X) | N1MM / WSJT-X / optional GridTracker; **browser** to the server. WIMS install optional |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` |

## Quick install (Win10 template) — for operators

**No PowerShell knowledge required.** Double-click:

| File | What it does |
|------|----------------|
| **`Install-Wims.cmd`** | Installs Python/Git (winget), gets/updates the repo, firewall TCP 8787, desktop shortcut. May prompt for UAC (Administrator). |
| **`Start-WimsServer.cmd`** | Starts the **site** WIMS server (one per contest LAN). Do **not** run this on every radio seat. |
| **`Start-WimsAgent.cmd`** | **One-shot** seat config check (prints report, exits). Optional export if `WIMS_SERVER` is set. |
| **`Start-WimsAgent-Continuous.cmd`** | **Daemon** agent only (UI `:8790` + export). Prefer full seat pack below for fleet VMs. |
| **`Start-WimsSeat.cmd`** | Start **N1MM → WSJT-X → agent** (staggered). Safe if apps already running. |
| **`Install-WimsSeatStartup.cmd`** | Put **WIMS Seat** in this user’s **Startup** folder (auto-logon VMs). No admin. |
| **`Remove-WimsSeatStartup.cmd`** | Remove Startup shortcut. |
| **`seat-config.example.cmd`** | Template for paths / seat id / which apps to start. |
| **`seat-local.cmd`** | Machine-specific copy (gitignored) — edit on each clone. |

### Fleet seat auto-start (Win10 template, auto-logon)

This image logs in as the operator with no password. After the desktop appears, Windows runs the user **Startup** folder.

1. Edit `scripts\windows\seat-local.cmd` (created from the example on first install):  
   `WIMS_SERVER`, `WIMS_SEAT_ID`, exe paths, `START_N1MM` / `START_WSJTX` / `START_AGENT`.
2. Double-click **`Install-WimsSeatStartup.cmd`** once.
3. Optional test: **`Start-WimsSeat.cmd`** (does not wait for reboot).
4. Reboot or sign out/in — N1MM, WSJT-X, and the continuous agent should come up.

Logs: `seat-startup-log.txt`, `agent-daemon-log.txt` next to the scripts.

**Development default:** `START_KILL_EXISTING=1` stops any running N1MM, WSJT-X (`wsjtx`/`jt9`),
and `wims.agent` before starting again so each logon/run is a clean refresh. Set to `0` later
if you prefer “don’t touch already-running apps” in production.

Disable auto-start: **`Remove-WimsSeatStartup.cmd`** or delete  
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS Seat.lnk`.

Steps:

1. Get the repo onto the VM (`git clone https://github.com/wa1hco/WIMS.git` **or** copy a USB tree).
2. In Explorer open `WIMS\scripts\windows\`.
3. Double-click **`Install-Wims.cmd`** → follow prompts / allow UAC.
4. Double-click **`Start-WimsServer.cmd`** (or Desktop **WIMS Server** after install).
5. Browser: `http://localhost:8787/` · `/status` · `/setup`

The `.cmd` files run PowerShell with **`-ExecutionPolicy Bypass` for that run only** — you do **not** run `Set-ExecutionPolicy` yourself.

### Offline / USB tree

```text
Double-click Install-Wims.cmd
```

Or from an elevated cmd (optional flags passed through to the `.ps1`):

```bat
Install-Wims.cmd -RepoPath D:\WIMS -SkipClone
```

### Developers only (PowerShell)

```powershell
.\Install-Wims.ps1
.\Start-WimsServer.ps1   # generated/updated by install; .cmd is preferred for ops
```

## After install

- Operate: `http://localhost:8787/`
- Status:  `http://localhost:8787/status`
- Setup:   `http://localhost:8787/setup` (contest log picker)

Copy the contest **`.s3db`** into `Documents\N1MM Logger+\Databases` on the **server** machine (or use Setup → Rescan after copy).

## Prerequisites the script installs

| Component | How |
|-----------|-----|
| **Python ≥ 3.10** | 1) `winget` (machine scope if admin) 2) if still missing, **silent download** of python.org 3.12.x |
| **Git** | `winget` if the tree must be cloned |
| **Firewall TCP 8787** | `New-NetFirewallRule` (admin) |
| **Start launcher** | Rewrites `Start-WimsServer.cmd` with the **full path** to `python.exe` (PATH refresh not required) |

After install, `scripts\windows\python-path.txt` records the chosen interpreter.

**Not** installed: N1MM, WSJT-X, GridTracker, Icom USB drivers.

### If you still see “Python not found”

1. Double-click **`Install-Wims.cmd`** again (allow UAC).  
2. Read the window for errors; install should not finish green without a Python path.  
3. Sign out/in once, then Install again (rare PATH timing issue).  
4. Manual fallback: https://www.python.org/downloads/ — check **Add python.exe to PATH**, then Install-Wims.cmd again.

## Radio seat checklist (no WIMS install)

1. WSJT-X: multicast + **Outgoing interface = LAN**
2. N1MM: Broadcast Data → WIMS host or `224.0.0.73:12060`
3. Browser → `http://<wims-server-ip>:8787/`

See [docs/plan/wims_networking.md](../../docs/plan/wims_networking.md).
