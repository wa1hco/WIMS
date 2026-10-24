# WIMS — WSJT-X Instance Management System

**Step 1.** Put **WIMS** on the Desktop and in the Start menu (Linux: the app menu).

| | |
|--|--|
| Windows | Double-click [`scripts\Add WIMS to Desktop.bat`](scripts/Add%20WIMS%20to%20Desktop.bat) |
| Linux | Double-click [`scripts/Add WIMS to Desktop.desktop`](scripts/Add%20WIMS%20to%20Desktop.desktop) |

**Step 2.** Double-click **WIMS**.

The WIMS window opens. Start Operate or the site server there, and the console opens in the browser at <http://localhost:8787/>. If that window is already open, double-clicking the icon brings it to the front.

Every file you can double-click is listed in [scripts/README.md](scripts/README.md).

Supervised, **human-in-the-loop** console for multi-instance VHF contesting: one operator sees a
ranked **call roster** across the fleet and **clicks to work** stations (S&P / tailend via WSJT-X
UDP Reply). Works with N1MM+, optional GridTracker, and rotators. **Not an autobot** — a human
starts every exchange; **run/CQ** stays in the seat WSJT-X UI (design §2.12).

On Setup, **Goal** is what you want from the stations you hear (a contest, an award, just operating, or your own list). The line under it is the rule in plain language. Changing it applies immediately. Just operating uses a **Checklist**: tick what is worth working, each line overall, on each band, or on each mode. **Advanced** holds a custom rule, and station state and county. The log WIMS checks is on **Log**: which file, and whether to count the whole log, contacts from now, or this year. To compare log files, double-click **Check logs**, or open Log → **Check logs**. The first line says how many logs were read and what is missing. WIMS only reads logs.

| Where the choice is saved | |
|--|--|
| Linux | `~/.config/wims/` |
| Windows | `%APPDATA%\wims\` |

The checklist is checked against the log you chose. A contest goal suggests the newest matching contest log only when you have not chosen one. Your choice stays until you change it.

> Design: [docs/plan/wims_design.md](docs/plan/wims_design.md) ·
> Status: [docs/plan/wims_status.md](docs/plan/wims_status.md)

## Install & quick start

**Short install guide:** **[INSTALL.md](INSTALL.md)** — Release package or ZIP, then the double-click installer for your system.  
**Testers / home evaluation:**  
**[docs/tester_quickstart.md](docs/tester_quickstart.md)** — tracks from *no radio apps* → WSJT-X only → WSJT-X+N1MM → optional multi-PC.  
**What you install (roles):** [docs/tester_roles.md](docs/tester_roles.md) — solo vs server vs N1MM agent / WSJT monitor.  
**Seat setup (WSJT-X · N1MM · Keyline):** [docs/operator_setup.md](docs/operator_setup.md).

Full instructions for a **new machine with nothing installed** (except Windows or Linux itself).
WIMS is **stdlib-only** (no `pip install`); the Windows installer brings in Python/Git/firewall.

Versioned packages (when cut): [GitHub Releases](https://github.com/wa1hco/WIMS/releases)
(`wims-<ver>-windows-x86_64.zip`, `wims-<ver>-linux-x86_64.tar.gz`).  
Design: [docs/plan/wims_release_packages.md](docs/plan/wims_release_packages.md).

### A. Windows — full setup (site server or lab PC)

**Installer (pick one):**

| Entry | Notes |
|-------|--------|
| [`scripts/windows/Install-Wims.cmd`](scripts/windows/Install-Wims.cmd) | Double-click; allow **UAC** (recommended) |
| [`install.ps1`](install.ps1) | Repo-root wrapper (map144-style); same logic |

Prefer the **`.cmd`** path. It starts PowerShell with `-ExecutionPolicy Bypass` for that run only. You do **not** need to change machine policy, and scripts are **not** Authenticode-signed yet.

#### Windows blocks unsigned scripts / downloads

GitHub Release ZIPs and browser downloads often carry a Mark of the Web. Windows may block `.ps1` / warn on first run.

1. **Prefer** double-click **`Install-Wims.cmd`** (not `install.ps1` alone).
2. If **SmartScreen** says “Windows protected your PC”: click **More info** → **Run anyway** (only if you trust [wa1hco/WIMS](https://github.com/wa1hco/WIMS)).
3. If Explorer / PowerShell says the file is **blocked** or “not digitally signed”:
   - In Explorer: right-click the **zip** (before extract) or `Install-Wims.cmd` / `install.ps1` → **Properties** → check **Unblock** → **OK**.
   - Or in PowerShell from `C:\WIMS`:
     ```powershell
     Unblock-File -Path .\scripts\windows\*.cmd, .\scripts\windows\*.ps1, .\install.ps1
     ```
4. To run the root wrapper when policy still blocks `.ps1`:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
   ```

Do **not** set a permanent `Set-ExecutionPolicy Unrestricted` unless you already manage that on the PC.

| If missing, install adds | How |
|--------------------------|-----|
| **Python ≥ 3.10** | `winget`, else silent download of python.org **3.12.x** |
| **Git** | `winget` — clone **and** launcher “Update available” (`git fetch origin/main`). Skipped for Release ZIP trees (no `.git`) |
| **Firewall rule TCP 8787** | so browsers on the LAN can open the console |
| **Start launchers + desktop shortcut** | pins the real `python.exe` path in `python-path.txt` (PATH not required; LibreOffice / Store stub ignored) |

**Not** installed by WIMS: N1MM Logger+, WSJT-X, GridTracker, radio drivers — install those
separately if this PC is a radio seat.

#### 1. Get the WIMS tree onto the PC (pick one)

| Method | Steps |
|--------|--------|
| **USB / network share** (offline-friendly) | Copy a full `WIMS` folder to e.g. `C:\WIMS` |
| **GitHub Release ZIP** | [Releases](https://github.com/wa1hco/WIMS/releases) → `wims-*-windows-x86_64.zip` → extract to `C:\WIMS` |
| **GitHub ZIP of `main`** | [main.zip](https://github.com/wa1hco/WIMS/archive/refs/heads/main.zip), extract to e.g. `C:\WIMS` |
| **Git already installed** | `git clone https://github.com/wa1hco/WIMS.git C:\WIMS` |

You only need the folder that contains `src\wims\` and `scripts\windows\`.

#### 2. Run the installer (installs missing prereqs)

1. If the tree came from a browser download, **Unblock** first (section above).
2. Open Explorer → `C:\WIMS\scripts\windows\` (or your path).
3. Double-click **`Install-Wims.cmd`**.
4. Click **Yes** on the UAC prompt (needed for machine-wide Python and firewall).
5. Wait until it reports success. Log: `scripts\windows\install-log.txt`.  
   On failure: re-run Install, or see [scripts/windows/README.md](scripts/windows/README.md)
   (“If you still see Python not found”).

#### 3. Start the site server

- Desktop **WIMS** → **Site server** (N1MM or dedicated host PC — not a WSJT-X-only seat), or **`Start-WimsServer.cmd`**.
- Browser on this PC: [http://localhost:8787/](http://localhost:8787/)  
  · Overview `/overview` · WSJT-X `/wsjt` · Log `/log` · N1MM `/n1mm` (several stations) · Setup `/setup`

Use the **contest LAN IP** for `--iface` when other hosts must reach the server (the Start script
defaults are lab-oriented; details in [scripts/windows/README.md](scripts/windows/README.md)).

#### 4. Point radios / operators at it

| Role | What to install / do |
|------|----------------------|
| **This PC = site server only** | WIMS install above is enough. Optional: copy an N1MM contest file onto the server, then choose it on the Log page. |
| **Radio seat** (N1MM + WSJT-X) | Install N1MM/WSJT-X yourself. Multicast + **Outgoing interface = LAN**. Browser → `http://<server-ip>:8787/`. Seat agent pack: same `scripts\windows\` folder — see **Full Windows guide** below. |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` (no WIMS install). |

**Full Windows guide** (seat auto-start, agent, offline flags, troubleshooting):  
**[scripts/windows/README.md](scripts/windows/README.md)**

**Fleet networking** (ports, N1MM, WSJT-X settings, readiness):  
**[docs/plan/wims_networking.md](docs/plan/wims_networking.md)**

### B. Linux — first time on this PC

1. Open the WIMS folder.
2. Open **scripts**.
3. Double-click **Add WIMS to Desktop**.

WIMS is then on the desktop and in the app menu. Double-click **WIMS**.

The file manager may ask once before that first file runs:

- **Ubuntu and other GNOME desktops:** If a message says the file is not trusted, right-click **Add WIMS to Desktop** and click **Allow Launching**. Then double-click it again.
- **KDE:** If a window asks whether to open or run the file, click **Execute**.
- **XFCE:** If a window asks whether to run the file, click **Execute**.
- **Cinnamon:** If a window asks, click **Run**. If it says the file is not trusted, right-click it and click **Allow Launching**, then double-click it again.

If the file opens as a page of text, the download dropped the permission to run it. Right-click **Add WIMS to Desktop**, open **Properties**, allow it to run as a program, and double-click it again.

If Python or the window library is missing, a message names what to install. Install that, then do what the message says.

### C. Already installed — just run

Double-click **WIMS**. On Windows the same window is **Start-WimsLauncher** in `scripts\windows\`. On one PC with WSJT-X, **Start-Wims-Solo** opens Operate and the browser.

---

## What it does

- **Call roster** — every decode ranked by expected score; click for **S&P or tailend** (Reply on
  a retained decode, including **73**). **Run/CQ** is not started from WIMS (design §2.12).
- **Contest scoring** — explainable factors; **N1MM** is dupe/mult authority; WIMS keeps a log copy.
- **Cross-vehicle console** — one roster + health instead of chat-only coordination.
- **Multi-operator** — soft control claims; cooperative team (design §2.7).
- **Zero TX overlap** per resource group; **SSB/CW priority** with preventive gate + 10 ms mute
  (design §3.4.1).
- **Setup assist** — connectivity checks, fleet discovery, plain-language readiness.
- **Dial is RF by default.** 28.074 MHz stays 10m (Flex / SmartSDR already
  report RF). Mark a seat on **Setup** only when its radio reports IF
  (Roy 222 at 21 MHz, Roy 432 at 28 MHz). No environment variable.

## Architecture at a glance

```
   WSJT-X #1 (6m FT8) ┐
   WSJT-X #2 (6m MSK) ┤          ┌──────────────────────────┐
   WSJT-X #3 (2m FT8) ┼─UDP──▶  │          WIMS            │ ◀── human override (SSB/CW op)
   WSJT-X #N ...       ┘         │  - UDP parse/control     │
        ▲                        │  - multi-instance mgr    │
        │  Reply / HaltTx /      │  - INTERLOCK (TX arbiter)│──▶ Dashboard
        │  FreeText / Replay     │  - decision engine       │
        └────────────────────────│  - safety / watchdog     │
                                 └───────┬─────────┬────────┘
                                         │         │
                           N1MM+ (log, ◀┘          └▶ Rotator(s) Yaesu/K3NG
                           dupe/needed)
```

**Site server** = multicast consumer + console control (Reply / Halt / Free Text — not Call CQ).
Consoles are browsers. Soft claim who may command TX from the console; local seat **run/CQ**
(Enable Tx in WSJT-X) is attended by the seat op. 10 ms SSB/CW mute runs on the **radio host
agent**, not through the server. Design §2.12 / §4 / §4.5.

## Status

**Phase-1 read-only console is live** (roster, interlock, N1MM sync, agents, three-page UI).
Command path (click-to-work) and later milestones: [wims_status.md](docs/plan/wims_status.md).

**Planned, not built:** additional sources for the needed-stations list — PSK Reporter, contest history, and VHF chat — as hints beside live decodes. A hint does not transmit. Design [§2.15](docs/plan/wims_design.md#215-additional-sources-for-the-needed-stations-list).

How the Score column is computed today, and a proposed score for comment, is in [docs/plan/scoring.md](docs/plan/scoring.md). The proposal is not built. A score does not transmit.

## Repository layout

```
WIMS/
├── docs/plan/            design · status · networking
├── scripts/              double-click launchers (see scripts/README.md)
├── tools/dev/            tests, packaging, lab helpers
├── src/wims/             server, udp, engine, interlock, n1mm, agent, …
├── testbed/              WSJT-X emulator, interlock bench
└── tests/unit/           no-pytest unit suites
```

## Developer

Typed commands, path variables, and flags are for people changing WIMS. Operators use the Desktop icon.

On a Mac, double-click is not available. From the WIMS folder: `scripts/add-wims-to-desktop.sh`.

```bash
# from the repo root; the checkout shim finds src/ with no path variable
python3 -m wims version
python3 -m wims solo --no-open
python3 -m wims.logaudit
tools/dev/validate.sh
```

```bat
set PYTHONPATH=src
python -m wims solo
```

Log compare flags (`--adif`, `--n1mm-db`, `--lotw`, `--json`) are optional. With no arguments the compare tool uses the WSJT-X logs it can find on this PC.

## License

WIMS is free software licensed under the **GNU General Public License v3.0 or later**
(**GPL-3.0-or-later**). See [LICENSE](LICENSE) for the full text.

    Copyright (C) 2026 Jeff Millar, WA1HCO

    This program is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by the Free
    Software Foundation, either version 3 of the License, or (at your option)
    any later version. It is distributed WITHOUT ANY WARRANTY; see the license
    for details.
