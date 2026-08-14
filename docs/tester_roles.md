# WIMS — What you install (roles for testers)

This is the **operator-facing product surface**: what lands on a PC, what each piece is
for, and what is **not** in the home-tester cut. Use it when evaluating a checkout or a
future GitHub Release.

**How to try it:** [tester_quickstart.md](tester_quickstart.md) (tracks A–D) ·  
**Solo deep dive:** [tester_runbook.md](tester_runbook.md) ·  
**Fleet networking:** [plan/wims_networking.md](plan/wims_networking.md) ·  
**Build status:** [plan/wims_status.md](plan/wims_status.md)

---

## One tree, several entry points

WIMS is **one codebase** (stdlib Python, no `pip` deps for runtime). There is no separate
installer per role. You clone or unpack the tree, run **Install** on Windows if needed,
then pick a **launcher**.

| How you get the tree | Notes |
|----------------------|--------|
| `git clone https://github.com/wa1hco/WIMS.git` | Preferred for updates |
| [GitHub ZIP of `main`](https://github.com/wa1hco/WIMS/archive/refs/heads/main.zip) | Offline-friendly; no pinned version until a Release exists |
| Future: GitHub **Release** asset | Same tree + release notes; not required for lab use |

**Windows prereqs once:** double-click `scripts\windows\Install-Wims.cmd`  
→ Python ≥ 3.10, optional Git, firewall **TCP 8787**, desktop shortcuts.  
**Does not** install N1MM, WSJT-X, GridTracker, or radio drivers.

**Linux:** `git` + `python3` (≥ 3.10); run with `PYTHONPATH=src`.

---

## Roles (what people mean vs what exists)

Design calls for three stackable roles: **server**, **console**, **agent**. In practice a
tester meets these **named** pieces:

| Role / name | What it is | How you start it | Home tester (R0)? |
|-------------|------------|------------------|-------------------|
| **Solo** | Site server + setup check + browser, single-PC defaults (one WSJT port, no fleet presence) | Windows: **`Start-Wims-Solo.cmd`** · Linux: `python -m wims.solo` / `scripts/start-wims-solo.sh` | **Yes — primary path** |
| **Site server** | Multicast ingest, roster, N1MM seed/live, Work/Halt, HTTP+SSE; fleet joins all band ports | **`Start-WimsServer.cmd`** / `python -m wims.server.app` | Optional (Track D / multi-PC) |
| **Operator console** | Browser only — Operate / Status / Setup | `http://<host>:8787/` | **Yes** (opened by Solo) |
| **Seat agent** (= **station agent**) | Local config audit, optional continuous report to server, local UI `:8790` | **`Check-WimsSetup.cmd`**, **`Start-WimsAgent.cmd`**, continuous **WIMS Agent** | Optional on one PC; useful on seats |
| **KEY agent** (SSB/CW → TX inhibit) | Reads KEY/CTS, sends `tx_inhibit` UDP to the WSJT-X gate | **No product launcher in this tree** | **No — not in R0 install surface** |
| **Seat pack** (Flex 50 / IC-9700 144) | Starts radio middleware + N1MM + WSJT-X + agent | `Start-Seat-*.cmd`, **`WIMS.cmd`** menu | Lab / fleet only |

**Naming:** “station agent” and “seat agent” are the **same** process (`wims.agent`). There
is not a second FT8-seat binary. **KEY agent** is a future/lab interlock role, not a
separate installer today.

---

## What each piece does (tester eyes)

### Solo / site server + console

| Page | URL | You use it for |
|------|-----|----------------|
| **Operate** | `/` | Ranked call roster; **click a row = Work** (WSJT-X Reply); **Halt TX** always available |
| **Status** | `/status` | Instances, N1MM, seat agents, activity, health |
| **Setup** | `/setup` | Contest log pick/resync, networking checklist, agent config detail |

**TX model:** no global Arm / Enable TX. Human initiation = **roster line click** (GridTracker2-style). **Call CQ / run** stays in the WSJT-X UI.

### Seat / station agent

| Mode | Entry | What you see |
|------|--------|----------------|
| Setup check | `Check-WimsSetup.cmd` or `python -m wims.agent --solo` | Plain-language `[OK]` / `[! ]` / `[XX]` for WSJT-X + N1MM |
| One-shot | `Start-WimsAgent.cmd` | Report; optional export to server |
| Continuous | Desktop **WIMS Agent** / `Start-WimsAgent-Continuous.cmd` | Local UI **http://127.0.0.1:8790/** + rows under Status/Setup **agents** |

**Built today:** WSJT-X `.ini` audit, N1MM DB/folder probe, process hints, export, site-server discovery.  
**Not built in the agent product:** KEY/PTT read, inhibit send, co-seat mute, process lifecycle/watchdog, production K3NG serial path.

### KEY agent / TX inhibit (out of R0 install)

| Layer | Location | Tester-facing? |
|-------|----------|----------------|
| Pure logic | `src/wims/interlock/inhibit.py` | No |
| Lab spike | `python testbed/inhibit_spike.py {gate,agent,selftest}` | Lab only |
| Gate inside WSJT-X | Separate repo [wa1hco/wsjtx-wims](https://github.com/wa1hco/wsjtx-wims) | Own CI/Releases; not the WIMS ZIP |

Home evaluation (tracks A–C) does **not** require KEY agent or a patched WSJT-X.

---

## Recommended surface (ignore the rest at first)

If `scripts/windows/` looks crowded, only these matter for home:

| Step | Windows | Linux |
|------|---------|--------|
| 1. Install prereqs | `Install-Wims.cmd` | `apt install git python3` |
| 2. Check setup | `Check-WimsSetup.cmd` | `PYTHONPATH=src python3 -m wims.agent --solo` |
| 3. Run | `Start-Wims-Solo.cmd` | `PYTHONPATH=src python3 -m wims.solo` |
| 4. Console | Browser → http://localhost:8787/ | same |

Everything else (seat packs, Startup, Proxmox clones, multi-band fleet server) is **advanced / site lab**.

---

## Band ports (WSJT-X / N1MM / WIMS must match)

UDP group **`224.0.0.73`**. Port is the **band stream** (not “any free port”):

| Band | Port |
|------|------|
| 50 MHz | **2237** |
| 144 | **2238** |
| 222 | **2239** |
| *(unused)* | **2240** — do not use (N1MM conflict hole) |
| 432 | **2241** |
| 902 | **2242** |
| 1296 | **2243** |

- **Solo** defaults to **2237**. Other band → start with matching port, e.g. `python -m wims.solo --port 2238`.  
- **Fleet server** joins `2237,2238,2239,2241,2242,2243` by default.  
- Full map: [plan/wims_networking.md](plan/wims_networking.md) §4.

WSJT-X **Settings → Reporting:** Accept UDP requests **ON**. On multi-host, set **Outgoing interface** to the contest LAN NIC (blank/`@Invalid` → silent empty roster).

---

## Track checklist (what “done” looks like)

| Track | You have | Pass criteria |
|-------|----------|----------------|
| **A** | No radio apps | Install; Operate/Status/Setup load; optional agent report |
| **B** | Local WSJT-X | Instance + roster populate from decodes |
| **C** | WSJT-X + N1MM | Needed↔dupe follows log; roster **click → Work** into dummy load; **Halt** stops |
| **D** | Multi-PC (optional) | Unique `--rig-name` per radio; browser to site server |

TX steps in the runbook are **provisional** until the first real-WSJT-X dummy-load bring-up is signed off (status: R0 remaining).

---

## Still open (honest remaining work)

| Area | Status |
|------|--------|
| CI on GitHub (`validate.sh`) | Done |
| Versioned GitHub Release / tags | Not yet (rolling `main`) |
| Dummy-load Reply echo-exactness | Open (R0 ship gate) |
| Seat agent: interlock / KEY / mute | Not productized |
| KEY agent launcher in WIMS install | Not present |
| Rotator: live K3NG on seats | Partial (sim + API; not full product) |
| “One package, choose role” installer | Design only; launchers only today |
| Multi-op claims, remote console polish | Later milestones |
| Fleet inventory UI + KEY target lists as nodes churn | Design §2.13; not coded |

**Fleet operating model (design):** operator identity + band subscribe + soft claim takeover,
equipment inventory, multi-KEY agents, and N1MM binding rules live in
[plan/wims_design.md](plan/wims_design.md) **§2.7 / §2.11 / §2.13**. R0 solo does not need
multi-op or KEY; site multi-multi does.

---

## Quick “see what a tester sees” (no RF)

```bash
cd WIMS
PYTHONPATH=src python3 -m wims.solo          # browser → :8787
# optional:
PYTHONPATH=src python3 -m wims.agent --solo
PYTHONPATH=src python3 testbed/simulators/emulator.py --iface 127.0.0.1 \
  --instances SIM-6M:50313000,SIM-2M:144174000
```

### UI lab fleet (multi WSJT + N1MM, including 3×6m → one N1MM)

Simulates the Status / N1MM network view without Springhill:

```bash
# one shot (server + traffic):
scripts/run_ui_fleet.sh
# or 6 m only:
scripts/run_ui_fleet.sh --six-only

# manual:
PYTHONPATH=src python3 -m wims.server.app --iface 127.0.0.1 --no-presence --no-seed
PYTHONPATH=src python3 testbed/simulators/fleet_ui.py   # or --six-only
# → http://localhost:8787/status
```

Story (default `fleet_ui.py`):

| Band | WSJT-X | N1MM |
|------|--------|------|
| **6 m** | TRAILER-50-A/B, TV-50-C | N1MM-50 on SSB-50-PC (3 feeds) |
| **2 m** | TRAILER-144-FT8 + TRAILER-144-MSK | N1MM-144 (both); N1MM-144-SSB (no WSJT) |
| **222 / 432** | ROY-222 / ROY-432 | Seat N1MM; **mode switch** FT8 ↔ SSB (WSJT silent in SSB half) |

Do **not** expect KEY/inhibit from that path.

When reporting issues: note **track**, OS, and whether N1MM / WSJT-X / unique rig-name were in use.
