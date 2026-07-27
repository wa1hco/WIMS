# WIMS — WSJT-X Instance Management System

Supervised, **human-in-the-loop** console for multi-instance VHF contesting: one operator sees a
ranked **call roster** across the fleet and **clicks to work** stations (S&P / tailend via WSJT-X
UDP Reply). Works with N1MM+, optional GridTracker, and rotators. **Not an autobot** — a human
starts every exchange; **run/CQ** stays in the seat WSJT-X UI (design §2.12).

> Design: [docs/plan/wims_design.md](docs/plan/wims_design.md) ·
> Status: [docs/plan/wims_status.md](docs/plan/wims_status.md)

## Install & quick start

**Testers / home evaluation (recommended entry):**  
**[docs/tester_quickstart.md](docs/tester_quickstart.md)** — tracks from *no radio apps* → WSJT-X only → WSJT-X+N1MM → optional multi-PC.

Full instructions for a **new machine with nothing installed** (except Windows or Linux itself).
WIMS is **stdlib-only** (no `pip install`); the Windows installer brings in Python/Git/firewall.

### A. Windows — full setup (site server or lab PC)

**Installer:** [`scripts/windows/Install-Wims.cmd`](scripts/windows/Install-Wims.cmd) →
[`Install-Wims.ps1`](scripts/windows/Install-Wims.ps1). Double-click; allow **UAC**. No
`Set-ExecutionPolicy` needed.

| If missing, install adds | How |
|--------------------------|-----|
| **Python ≥ 3.10** | `winget`, else silent download of python.org **3.12.x** |
| **Git** | `winget` (when cloning) |
| **Firewall rule TCP 8787** | so browsers on the LAN can open the console |
| **Start launchers + desktop shortcut** | pins the real `python.exe` path (PATH not required) |

**Not** installed by WIMS: N1MM Logger+, WSJT-X, GridTracker, radio drivers — install those
separately if this PC is a radio seat.

#### 1. Get the WIMS tree onto the PC (pick one)

| Method | Steps |
|--------|--------|
| **USB / network share** (offline-friendly) | Copy a full `WIMS` folder to e.g. `C:\WIMS` |
| **GitHub ZIP** | Download [repo ZIP](https://github.com/wa1hco/WIMS/archive/refs/heads/main.zip), extract to e.g. `C:\WIMS` |
| **Git already installed** | `git clone https://github.com/wa1hco/WIMS.git C:\WIMS` |

You only need the folder that contains `src\wims\` and `scripts\windows\`.

#### 2. Run the installer (installs missing prereqs)

1. Open Explorer → `C:\WIMS\scripts\windows\` (or your path).
2. Double-click **`Install-Wims.cmd`**.
3. Click **Yes** on the UAC prompt (needed for machine-wide Python and firewall).
4. Wait until it reports success. Log: `scripts\windows\install-log.txt`.  
   On failure: re-run Install, or see [scripts/windows/README.md](scripts/windows/README.md)
   (“If you still see Python not found”).

#### 3. Start the site server

- Double-click **`Start-WimsServer.cmd`**, or Desktop **WIMS Server**.
- Browser on this PC: [http://localhost:8787/](http://localhost:8787/)  
  · Status: `/status` · Setup (contest log): `/setup`

Use the **contest LAN IP** for `--iface` when other hosts must reach the server (the Start script
defaults are lab-oriented; details in [scripts/windows/README.md](scripts/windows/README.md)).

#### 4. Point radios / operators at it

| Role | What to install / do |
|------|----------------------|
| **This PC = site server only** | WIMS install above is enough. Optional: copy N1MM contest `.s3db` onto the server for log seed (Setup page). |
| **Radio seat** (N1MM + WSJT-X) | Install N1MM/WSJT-X yourself. Multicast + **Outgoing interface = LAN**. Browser → `http://<server-ip>:8787/`. Seat agent pack: same `scripts\windows\` folder — see **Full Windows guide** below. |
| **Operator laptop** | Browser only → `http://<server-ip>:8787/` (no WIMS install). |

**Full Windows guide** (seat auto-start, agent, offline flags, troubleshooting):  
**[scripts/windows/README.md](scripts/windows/README.md)**

**Fleet networking** (ports, N1MM, WSJT-X settings, readiness):  
**[docs/plan/wims_networking.md](docs/plan/wims_networking.md)**

### B. Linux — full setup (dev / Linux site server)

There is no Windows-style one-click installer. Install OS packages, then run WIMS.

```bash
# Debian/Ubuntu example — install prereqs if missing
sudo apt update
sudo apt install -y git python3   # ≥ 3.10; 3.12–3.14 fine

git clone https://github.com/wa1hco/WIMS.git
cd WIMS
python3 src/wims/server/app.py --iface 127.0.0.1
# Console: http://localhost:8787/  (use the LAN iface IP for multi-host)
```

No `pip` packages. Optional smoke test / no-RF fleet:

```bash
python3 testbed/simulators/emulator.py --iface 127.0.0.1 \
    --instances ROY-6M:50313000,CHIP-2M:144174000,TRL-432:432174000
scripts/validate.sh   # or: for t in tests/unit/test_*.py; do python3 "$t"; done
```

### C. Already installed — just run

```bash
# Linux / PATH has python3
python3 src/wims/server/app.py --iface 127.0.0.1

# Windows (after Install-Wims.cmd)
scripts\windows\Start-WimsServer.cmd
```

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

## Repository layout

```
WIMS/
├── docs/plan/            design · status · networking
├── scripts/windows/      Install-Wims.cmd (prereqs) · Start-WimsServer · seat pack
├── src/wims/             server, udp, engine, interlock, n1mm, agent, …
├── testbed/              WSJT-X emulator, interlock bench
└── tests/unit/           no-pytest unit suites
```

## License

WIMS is free software licensed under the **GNU General Public License v3.0 or later**
(**GPL-3.0-or-later**). See [LICENSE](LICENSE) for the full text.

    Copyright (C) 2026 Jeff Millar, WA1HCO

    This program is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by the Free
    Software Foundation, either version 3 of the License, or (at your option)
    any later version. It is distributed WITHOUT ANY WARRANTY; see the license
    for details.
