# WIMS — What you install (roles for testers)

This is the **operator-facing product surface**: what lands on a PC, what each piece is
for, and what is **not** in the home-tester cut. Use it when evaluating a checkout or a
future GitHub Release.

**How to try it:** [tester_quickstart.md](tester_quickstart.md) (tracks A–D) ·  
**Solo deep dive:** [tester_runbook.md](tester_runbook.md) ·  
**Fleet networking:** [plan/wims_networking.md](plan/wims_networking.md) ·  
**Build status:** [plan/wims_status.md](plan/wims_status.md)

---

## One tree, one desktop launcher

WIMS is **one codebase** (stdlib Python, no `pip` deps for runtime). You clone or unpack
the tree, run **Install** on Windows if needed, then use the **desktop GUI launcher** —
same idea as double-clicking N1MM or WSJT-X.

| How you get the tree | Notes |
|----------------------|--------|
| `git clone https://github.com/wa1hco/WIMS.git` | Preferred for updates |
| [GitHub ZIP of `main`](https://github.com/wa1hco/WIMS/archive/refs/heads/main.zip) | Offline-friendly; no pinned version until a Release exists |
| Future: GitHub **Release** asset | Same tree + release notes; not required for lab use |

**Windows prereqs once:** double-click `scripts\windows\Install-Wims.cmd`  
→ Python ≥ 3.10, optional Git, firewall **TCP 8787**, then  
`Install-WIMS-Desktop-Shortcut.cmd` → Desktop **WIMS** icon (`assets\wims.ico`).  
**Does not** install N1MM, WSJT-X, GridTracker, or radio drivers.

**Linux:** `git` + `python3` (≥ 3.10) + `python3-tk`;  
`scripts/install-wims-desktop.sh` or `PYTHONPATH=src python3 -m wims --install-shortcut`.

**Everyday start (contest):** double-click Desktop **WIMS** → **Site server** (one PC);
on each **N1MM** PC check **N1MM** (+ **SSB/CW KEY**) → **N1MM agent**; on **WSJT** PCs
optional monitor. Solo is under **lab roles** only.

**Operator setup (WSJT-X / N1MM / Keyline):** [operator_setup.md](operator_setup.md).

Hover any button for a tooltip. Role model:
[docs/decisions/2026-08-29-contest-pc-roles.md](decisions/2026-08-29-contest-pc-roles.md).

---

## Roles (what people mean vs what exists)

Design calls for stackable roles: **server**, **console**, **agent**, **KEY**. Testers
meet them as buttons in the GUI (legacy `.cmd` launchers still work):

| Role / name | What it is | How you start it | Home tester (R0)? |
|-------------|------------|------------------|-------------------|
| **Desktop launcher** | GUI: role picker, band port, tooltips, Desktop shortcut helper | Desktop **WIMS** · `python -m wims` · `Start-WimsLauncher.cmd` | **Yes — primary entry** |
| **Solo** | Site server + browser, single-PC defaults (one WSJT port, no fleet presence) | GUI **Start Solo** · `Start-Wims-Solo.cmd` · `python -m wims solo` | **Yes — primary path** |
| **Site server** | Multicast ingest, roster, N1MM seed/live, Work/Halt, HTTP+SSE; fleet joins **`2237`** | GUI **Start server** · `Start-WimsServer.cmd` · `python -m wims server` | Optional (Track D / multi-PC) |
| **Operator console** | Browser — Operate / Overview / WSJT-X / N1MM / Setup | `http://<host>:8787/` | **Yes** (opened by Solo) |
| **WSJT monitor** | Local WSJT-X.ini audit + report, UI `:8790` | Launcher **WSJT-X** · `Check-WimsSetup.cmd` · `python -m wims.agent` | Optional on digi PCs |
| **N1MM agent** | **Broadcast** + **Log** + optional **KEY** | Launcher **N1MM** + **SSB/CW KEY** · `python -m wims.seat --log --key` | Contest N1MM PC |
| **Inhibit bench** | Lab gate/agent/selftest | `python -m wims key selftest` · `testbed/inhibit_bench.py` | Lab only |
| **Seat pack** (Flex 50 / IC-9700 144) | Radio middleware + N1MM + WSJT-X + agent | `Start-Seat-*.cmd`, **`WIMS.cmd`** text menu | Lab / fleet only |

**Naming:** WSJT **monitor** is `wims.agent` (optional for RF). **N1MM agent** is
`wims.seat` (Broadcast / Log / KEY) — see [operator_setup.md](operator_setup.md).

---

## What each piece does (tester eyes)

### Solo / site server + console

| Page | URL | You use it for |
|------|-----|----------------|
| **Operate** | `/` | Ranked call roster; **click a row = Work**; **Halt TX** |
| **Overview** | `/overview` | System, bands, agents, rotators |
| **WSJT-X** | `/wsjt` | Digi instances + decode activity |
| **N1MM** | `/n1mm` | Contest log pick/resync, logger sync / network |
| **Setup** | `/setup` | Install diagnostics (networking, seat configs) |

**TX model:** no global Arm. Human initiation = **roster click**. **Call CQ** stays in WSJT-X.

### WSJT monitor (`wims.agent`)

| Mode | Entry | What you see |
|------|--------|----------------|
| Setup check | `Check-WimsSetup.cmd` or `python -m wims.agent --solo` | `[OK]` / `[! ]` / `[XX]` for WSJT-X (+ N1MM probe) |
| Continuous | Launcher **WSJT-X** / `Start-WimsAgent-Continuous.cmd` | **http://127.0.0.1:8790/** + Overview **Agents** |

### N1MM agent / KEY / inhibit

| Layer | Location | Tester-facing? |
|-------|----------|----------------|
| N1MM agent | `python -m wims.seat --log --key` | Logger PC — Broadcast / Log / KEY |
| Pure inhibit logic | `src/wims/interlock/inhibit.py` | No |
| Inhibit bench | `testbed/inhibit_bench.py` | Lab |
| Gate inside WSJT-X | [wa1hco/wsjtx-wims](https://github.com/wa1hco/wsjtx-wims) | Separate build |

Home tracks A–C do **not** require KEY or a patched WSJT-X.

---

## Recommended surface (ignore the rest at first)

If `scripts/windows/` looks crowded, only these matter for home:

| Step | Windows | Linux |
|------|---------|--------|
| 1. Install prereqs | `Install-Wims.cmd` | `apt install git python3 python3-tk` |
| 2. Desktop icon | `Install-WIMS-Desktop-Shortcut.cmd` | `scripts/install-wims-desktop.sh` |
| 3. Open WIMS | Double-click Desktop **WIMS** | same, or `PYTHONPATH=src python3 -m wims` |
| 4. In the GUI | **Check this PC**, then **Start Solo** | same |
| 5. Console | GUI **Open Operate** → http://localhost:8787/ | same |

Everything else (seat packs, Startup, Proxmox clones, multi-band fleet server, KEY) is
**advanced / site lab**.

---

## Plane A UDP (WSJT-X / WIMS must match)

```text
224.0.0.73:2237
```

**All bands use port 2237** ([decision 2026-09-05](decisions/2026-09-05-plane-a-single-port-2237.md)).
Distinguish instances with `--rig-name`, not with 2238–2243.

WSJT-X **Settings → Reporting:** Accept UDP requests **ON**. On multi-host, set
**Outgoing interface** to the contest LAN NIC (blank/`@Invalid` → silent empty roster).

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
| KEY agent fleet assignment | Lab selftest in GUI only; no server-pushed targets yet |
| Rotator: live K3NG on seats | Partial (sim + API; not full product) |
| Desktop GUI role launcher | Done (`python -m wims` / Desktop **WIMS** icon) |
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
| **6 m** | **South**, **West**, **East** | N1MM-50 on SSB-50-PC (3 feeds) |
| **2 m** | TRAILER-144-FT8 + TRAILER-144-MSK | N1MM-144 (both); N1MM-144-SSB (no WSJT) |
| **222 / 432** | ROY-222 / ROY-432 | Seat N1MM; **mode switch** FT8 ↔ SSB (WSJT silent in SSB half) |

Do **not** expect KEY/inhibit from that path.

When reporting issues: note **track**, OS, and whether N1MM / WSJT-X / unique rig-name were in use.
