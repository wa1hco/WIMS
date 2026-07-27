# WIMS on Windows

## Roles

| Machine | Needs |
|---------|--------|
| **WIMS server** (one per site/lab) | This install + Python; opens TCP **8787** |
| **Radio seat** (N1MM + WSJT-X) | N1MM / WSJT-X / optional GridTracker; **browser** to the server. WIMS install optional |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` |

## Solo tester (everything on one PC) — start here if you're trying WIMS out

**Full tracks (no apps → WSJT only → N1MM+WSJT → multi-PC):**  
[docs/tester_quickstart.md](../../docs/tester_quickstart.md)

For **one operator on one PC** running N1MM + WSJT-X + WIMS together, on a single FT8
frequency (any band). No fleet, no separate server.

1. **`Install-Wims.cmd`** — installs prerequisites (once; may prompt for UAC).
2. In WSJT-X: **Settings → Reporting → UDP Server `224.0.0.73`, port `2237`**, tick
   **"Accept UDP requests"**.
3. **`Check-WimsSetup.cmd`** — double-click to see a plain-language **[OK] / [! ] / [XX]**
   check of your WSJT-X + N1MM setup (starts nothing).
4. **`Start-Wims-Solo.cmd`** — runs the same check, then starts WIMS and opens
   `http://localhost:8787/`. Arm TX, click **Work** on a roster row, **Halt TX** to stop.

| File | What it does |
|------|----------------|
| **`Check-WimsSetup.cmd`** | Plain-language single-PC setup check (`wims.agent --solo`). Reports what's wrong and the exact WSJT-X/N1MM fix. Starts nothing. |
| **`Start-Wims-Solo.cmd`** | Solo console: setup check, then the WIMS server on this PC (`python -m wims.solo`, localhost, no fleet presence). |

To verify the **needed-vs-dupe** roster: log a callsign in N1MM → its roster row turns to
*dupe*; delete it → back to *needed*.

## Quick install (Win10 template) — for operators

**No PowerShell knowledge required.**

### One place to click (recommended) — fleet radio seats

| File | What it does |
|------|----------------|
| **`WIMS.cmd`** | **Seat menu** — check agent, continuous agent, seat pack, open pages, desktop/Startup helpers. Finds the install automatically. |
| **`Install-WIMS-Desktop-Shortcut.cmd`** | Desktop **WIMS** (seat menu, blue icon) **+** **WIMS Agent** (green). Run once per seat VM. |
| **`Install-WimsAgent-Desktop-Shortcut.cmd`** | Desktop **WIMS Agent** only (green icon → continuous agent). |
| **`assets\wims.ico` / `wims-agent.ico`** | Icons for those shortcuts. |

After that, operators only need the Desktop **WIMS** icon.

### Other scripts (menu calls these; rarely opened by hand)

| File | What it does |
|------|----------------|
| **`Install-Wims.cmd`** | Installs Python/Git (winget), gets/updates the repo, firewall TCP 8787. May prompt for UAC. |
| **`Start-WimsServer.cmd`** | **Site** WIMS server only (not for radio seats). |
| **`Start-WimsAgent.cmd`** | One-shot agent check (also menu option 1). |
| **`Start-WimsAgent-Continuous.cmd`** | Continuous agent (menu option 2). |
<<<<<<< HEAD
| **`Start-WimsSeat.cmd`** | N1MM/WSJT if needed + agent (menu option 3). |
| **`Find-And-Set-WsjtxRigName.cmd`** | List/fix all WSJT-X shortcuts + `seat-local.cmd` `--rig-name`. |
| **`Start-WimsSeat.cmd`** | wfview → N1MM/WSJT if needed + agent (menu option 3). |
| **`Find-And-Set-WsjtxRigName.cmd`** | List/fix all WSJT-X shortcuts + `seat-local.cmd` `--rig-name`. |
| **`Install-WimsSeatStartup.cmd`** / **`Remove-WimsSeatStartup.cmd`** | Logon auto-start for seat pack. |
| **`seat-config.example.cmd`** / **`seat-local.cmd`** | Seat id, server URL, paths (edit `seat-local` per clone). **`WSJTX_RIG_NAME` is required** (never blank). |
| **`Start-WSJTX.cmd`** | Only safe way to start WSJT-X — always adds `--rig-name=` from `seat-local`. |
| **`Install-WSJTX-RigNameShortcuts.cmd`** | Repoints Desktop / Start Menu `wsjtx` icons at `Start-WSJTX.cmd` (no bare launch). |
| **`Check-WimsSetup.cmd`** / **`Start-Wims-Solo.cmd`** | Solo tester path (see section above). |
| **`Start-WSJTX-50.cmd`** | Start (or no-op if already up) the 6 m WSJT-X instance `--rig-name=WSJTX-50`. |
| **`Set-SeatAfterClone.cmd`** | After cloning a Win10 seat: write `seat-local.cmd`, hostname, Startup link. |

### Lab: Proxmox seat clones (optional)

| File | What it does |
|------|----------------|
| **`proxmox-clone-wims-seats.sh`** | On the **Proxmox host**: template the golden Win10 guest, clone IC-9700 + Flex seats. |
| **`_pve_api.py`** / **`_pve_spawn_seats.py`** | Optional API helpers (password via CLI arg only — never commit secrets). Lab defaults (host/VMIDs) are in-file; edit for your cluster. |

After clones boot, run **`Set-SeatAfterClone.cmd SEAT-ID [WSJT-RIG-NAME]`** inside each guest (elevated if renaming).

### Fleet seat auto-start (Win10 template, auto-logon)

This image logs in as the operator with no password. After the desktop appears, Windows runs the user **Startup** folder.

1. Edit `scripts\windows\seat-local.cmd` (created from the example on first install):  
   `WIMS_SERVER`, `WIMS_SEAT_ID`, exe paths, `START_WFVIEW` / `START_N1MM` / `START_WSJTX` / `START_AGENT`.
2. Double-click **`Install-WimsSeatStartup.cmd`** once (or menu option 7).
3. Optional test: **`Start-WimsSeat.cmd`** / menu option 3 (does not wait for reboot).
4. Reboot or sign out/in — wfview, N1MM, WSJT-X, and the continuous agent should come up.

Logs: `seat-startup-log.txt`, `agent-daemon-log.txt` next to the scripts.

**App policy:** **wfview** starts first (Icom CAT / RigCtld), then N1MM, then WSJT-X.
wfview, N1MM, and WSJT-X are **only started if missing** (never force-killed — avoids blank
WSJT dialogs and mid-log disruption). The **agent** defaults to
`START_AGENT_RESTART=1` (kill old `wims.agent`, start fresh) while the agent is in development.

Disable auto-start: **`Remove-WimsSeatStartup.cmd`** or delete  
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS Seat.lnk`.

Steps (seat / fleet VM):

1. Get the repo onto the VM (`git clone …` **or** USB tree), e.g. `C:\Users\W2SZ\WIMS`.
2. Open `WIMS\scripts\windows\` once → double-click **`Install-Wims.cmd`** (Python) if needed.
3. Double-click **`Install-WIMS-Desktop-Shortcut.cmd`** → Desktop gets **WIMS** (blue menu)
   and **WIMS Agent** (green continuous agent).
4. Day-to-day on a radio seat: double-click **WIMS Agent**. Full menu: **WIMS**.
   Edit `seat-local.cmd` once per clone for seat id / server URL.
5. **Unique WSJT-X UDP id:** set `WSJTX_RIG_NAME=` in `seat-local.cmd` **and** fix every
   Desktop/Startup shortcut that starts `wsjtx.exe`:
   `Find-And-Set-WsjtxRigName.cmd` (list) then  
   `Find-And-Set-WsjtxRigName.cmd -RigName W10VM-144 -Apply` (2m) or `W10VM-50` (6m).  
   Exit all `wsjtx.exe` and reboot. If another Startup entry starts WSJT without
   `--rig-name` first, WIMS seat pack will not re-launch it with the right name.

Site server PC (not seats): **`Start-WimsServer.cmd`** / **WIMS Server** → `http://localhost:8787/`.
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
