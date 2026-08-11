# WIMS on Windows

## Roles

| Machine | Needs |
|---------|--------|
| **WIMS server** (one per site/lab) | This install + Python; opens TCP **8787** |
| **Radio seat** (N1MM + WSJT-X) | N1MM / WSJT-X / optional GridTracker; **browser** to the server. WIMS install optional |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` |

## Solo tester (everything on one PC) — start here if you're trying WIMS out

**What you install (roles):** [docs/tester_roles.md](../../docs/tester_roles.md)  
**Full tracks (no apps → WSJT only → N1MM+WSJT → multi-PC):**  
[docs/tester_quickstart.md](../../docs/tester_quickstart.md)

For **one operator on one PC** running N1MM + WSJT-X + WIMS together, on a single FT8
frequency (any band). No fleet, no separate server.

1. **`Install-Wims.cmd`** — installs prerequisites (once; may prompt for UAC).
2. In WSJT-X: **Settings → Reporting → UDP Server `224.0.0.73`, port `2237`** (or your
   band port — 144→2238, 432→**2241**, never 2240), tick **"Accept UDP requests"**.
3. **`Check-WimsSetup.cmd`** — double-click to see a plain-language **[OK] / [! ] / [XX]**
   check of your WSJT-X + N1MM setup (starts nothing).
4. **`Start-Wims-Solo.cmd`** — runs the same check, then starts WIMS and opens
   `http://localhost:8787/`. **Click a roster line** to Work (no Arm/Enable TX);
   **Halt TX** always available.

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
| **`Start-Seat-Flex50.cmd`** | **Flex 50 MHz pack:** SmartSDR → CAT → DAX → N1MM → WSJT-X (`WSJTX-50`) → agent. |
| **`Start-Seat-IC9700-144.cmd`** | **IC-9700 144 MHz pack:** wfview → N1MM → WSJT-X (`WSJTX-144`) → agent. |
| **`Start-WimsSeat.cmd`** | Dispatcher: `flex50` / `ic9700-144`, or menu / `SEAT_DEFAULT_RADIO`. |
| **`_Start-Seat-Core.cmd`** | Shared engine (N1MM + WSJT + agent); not double-clicked. |
| **`Find-And-Set-WsjtxRigName.cmd`** | List/fix all WSJT-X shortcuts + radio config `--rig-name`. |
| **`Install-WimsSeatStartup.cmd`** / **`Remove-WimsSeatStartup.cmd`** | Logon auto-start: `Install-WimsSeatStartup.cmd flex50` or `ic9700-144`. |
| **`seat-common.example.cmd`** / **`seat-common.cmd`** | Shared: server URL, N1MM path, agent flags. |
| **`radio-flex50.example.cmd`** / **`radio-flex50.cmd`** | Flex paths + 50 MHz `WSJTX_RIG_NAME`. |
| **`radio-ic9700-144.example.cmd`** / **`radio-ic9700-144.cmd`** | wfview path + 144 MHz `WSJTX_RIG_NAME`. |
| **`Start-WSJTX.cmd`** | Generic launcher with required `--rig-name=` (arg or config). |
| **`Start-WSJTX-50.cmd`** / **`Start-WSJTX-144.cmd`** | Band-specific WSJT-X only (tired-op safe). |
| **`Install-WSJTX-RigNameShortcuts.cmd`** | Repoints Desktop / Start Menu `wsjtx` icons at `Start-WSJTX.cmd` (no bare launch). |
| **`Check-WimsSetup.cmd`** / **`Start-Wims-Solo.cmd`** | Solo tester path (see section above). |
| **`Set-SeatAfterClone.cmd`** | After cloning a Win10 seat: write common + radio config, hostname, Startup. |

### Lab: Proxmox seat clones (optional)

| File | What it does |
|------|----------------|
| **`proxmox-clone-wims-seats.sh`** | On the **Proxmox host**: template the golden Win10 guest, clone IC-9700 + Flex seats. |
| **`_pve_api.py`** / **`_pve_spawn_seats.py`** | Optional API helpers (password via CLI arg only — never commit secrets). Lab defaults (host/VMIDs) are in-file; edit for your cluster. |

After clones boot, run **`Set-SeatAfterClone.cmd SEAT-ID [WSJT-RIG-NAME]`** inside each guest (elevated if renaming).

### Two radio packs (same PC or separate seats)

| Pack | Script | Middleware | WSJT-X `--rig-name` (default) | Band |
|------|--------|------------|-------------------------------|------|
| **Flex 50** | `Start-Seat-Flex50.cmd` | SmartSDR → CAT → DAX | `WSJTX-50` | 50 MHz |
| **IC-9700 144** | `Start-Seat-IC9700-144.cmd` | wfview (RigCtld) | `WSJTX-144` | 144 MHz |

**N1MM is common** — both packs start it only if missing (one logger process).  
**WSJT-X is per-band** — each pack uses its own named config under  
`%LOCALAPPDATA%\WSJT-X - <rig-name>\` (radio, audio, UDP port differ by band).

Config files (gitignored when local):

| File | Scope |
|------|--------|
| `seat-common.cmd` | Server URL, N1MM path, agent flags, `SEAT_DEFAULT_RADIO` |
| `radio-flex50.cmd` | SmartSDR dir, 50 MHz seat id + rig-name |
| `radio-ic9700-144.cmd` | wfview path, 144 MHz seat id + rig-name |

### Fleet seat auto-start (Win10 template, auto-logon)

This image logs in as the operator with no password. After the desktop appears, Windows runs the user **Startup** folder.

1. Copy examples → local configs and edit:
   - `seat-common.example.cmd` → `seat-common.cmd`
   - `radio-flex50.example.cmd` → `radio-flex50.cmd` **or**
   - `radio-ic9700-144.example.cmd` → `radio-ic9700-144.cmd`
2. Double-click **`Install-WimsSeatStartup.cmd flex50`** or **`… ic9700-144`** once  
   (or menu option 9 — picks a pack).
3. Optional test: **`Start-Seat-Flex50.cmd`** / **`Start-Seat-IC9700-144.cmd`**.
4. Reboot or sign out/in — that radio’s middleware, N1MM, WSJT-X, and agent come up.

Logs: `seat-startup-flex50-log.txt` / `seat-startup-ic9700-144-log.txt`, `agent-daemon-log.txt`.

**Start order (critical for CAT/audio):**
- **Flex 50:** SmartSDR → wait (`SMARTSDR_DELAY_SEC`) → CAT → DAX → wait → N1MM → WSJT-X-50
- **IC-9700 144:** wfview → wait (`WFVIEW_DELAY_SEC`) → N1MM → WSJT-X-144  

N1MM / WSJT-X will not open radio COM or DAX correctly if middleware is not up first.
Middleware, N1MM, and WSJT-X are **only started if missing** (never force-killed).  
The **agent** defaults to `START_AGENT_RESTART=1` while in development.

Disable auto-start: **`Remove-WimsSeatStartup.cmd`** or delete  
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WIMS Seat.lnk`.

Steps (seat / fleet VM):

1. Get the repo onto the VM (`git clone …` **or** USB tree), e.g. `C:\Users\W2SZ\WIMS`.
2. Open `WIMS\scripts\windows\` once → double-click **`Install-Wims.cmd`** (Python) if needed.
3. Double-click **`Install-WIMS-Desktop-Shortcut.cmd`** → Desktop gets **WIMS** (blue menu)
   and **WIMS Agent** (green continuous agent).
4. Day-to-day: run the pack for the radio in use (`Start-Seat-Flex50` or `…-IC9700-144`),
   or use the **WIMS** menu. Edit `seat-common.cmd` + the matching `radio-*.cmd`.
5. **Unique WSJT-X UDP id per band:** set `WSJTX_RIG_NAME` in the radio config **and** fix
   Desktop shortcuts: `Find-And-Set-WsjtxRigName.cmd -RigName WSJTX-144 -Apply` (2m) or
   `WSJTX-50` (6m). Prefer `Start-WSJTX-50.cmd` / `Start-WSJTX-144.cmd` over bare `wsjtx.exe`.

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
