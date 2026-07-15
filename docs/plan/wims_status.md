# WIMS — Build Status & Milestones

Companion tracker to **[wims_design.md](wims_design.md)** (the requirements / design source of
truth). This file holds **implementation progress only** — what's built, tested, and running —
and references design sections by their `§` numbers. When a *design* changes, edit
wims_design.md; when *code* lands, edit here.

Status: `[ ]` todo · `[~]` in progress · `[x]` done

---

## How to run (current)

```
python src/wims/server/app.py --iface 127.0.0.1
#   Operate:  http://localhost:8787/          (roster / work stations)
#   Status:   http://localhost:8787/status    (live health, RF, decodes)
#   Setup:    http://localhost:8787/setup     (contest log, networking, config)
```
- **Log seed:** scans N1MM contest `.s3db` file(s) for **multiple contest instances**
  (`ContestInstance` / `ContestNR`), **auto-picks** the latest log with QSOs, and loads only that
  contest (not whole multi-year DXLOG). Status page **Contest log** picker to change / rescan;
  `POST /api/contests/select`. Optional `--seed-db` / `--seed-db-dir` / `--no-seed` — operators
  should not need ContestNR. Copy the VM’s contest DB into the seed dir when N1MM is remote.
- **Ingest (current code):** WSJT-X multicast `224.0.0.73:2237` on `--iface` + N1MM XML on
  `:12060` (unicast/broadcast by default; `--n1mm-group 224.0.0.73` for multi-host multicast —
  same group as WSJT-X is fine, port differs). Multicast join uses `--iface` (use the LAN IP,
  not `127.0.0.1`, for a bridged VM / other host).
- **Fleet networking (design):** multi-band layout is **one N1MM + N× WSJT-X per band**,
  streams segregated by port (2237–2240) so each logger is sole owner — full map in
  **[wims_networking.md](wims_networking.md)**. Server multi-port join for 2238–2240 is not
  wired yet (lab still uses a single WSJT-X port).
- **No-RF test bed:** `python testbed/simulators/emulator.py --iface 127.0.0.1 --instances ROY-6M:50313000,CHIP-2M:144174000,TRL-432:432174000`
- **Interlock bench:** `python testbed/interlock_bench.py`

## Tests — **11 suites green** (no pytest dep; run `python tests/unit/test_*.py`)
`test_messages` · `test_encode` · `test_emulator` · `test_arbiter` · `test_controller` ·
`test_scoring` · `test_roster` · `test_activity` · `test_fleet` · `test_n1mm_log` ·
`test_server_state`

**One-command smoke validation:** `scripts/validate.sh` — runs the unit suites, an
import check, the interlock bench, and a **live** no-RF run (boots server + emulator,
captures one SSE frame, asserts the state contract + emulated instances flow through).
Exit 0 = all green; per-check logs land in `scratch/validate/` (gitignored). Overridable
via `WIMS_IFACE` / `WIMS_HTTP_PORT` / `WIMS_INSTANCES` / `PYTHON`.

---

## Milestones (design intent: §4 / §4.5)

- [~] **M1 — parser + read-only dashboard.** Parser (§3.1); console monitor + fleet view; browser
  dashboard live (server ingests multicast → SSE → static HTML). **Phase-1 read-only panel sweep
  complete:** fleet/instances, interlock/overlap (§2.1), call roster (§2.2 / §3.5), decode-activity
  heatmaps (§2.5), decode log, N1MM-sync, loggers — all live & verified vs the emulator. Console
  split into two pages (Operate / Status). Next: command path + Phase-2 polish.
- [~] **M2 — arbiter + control on bench (no RF).** Core done: emulator (§5.1), `TxController`
  (§3.2), `TxArbiter` + `OverlapDetector` (§3.4) — interlock bench proves zero overlap live.
  Remaining: per-resource-group config from profiles, SSB/CW fast-inhibit path, lease gating.
- [~] **M3 — decision engine + N1MM dupe/mult.** Live server scores a ranked roster
  (`engine/roster.py` + `scoring.py`) against a log copy seeded from the N1MM `.s3db` at startup
  and kept current from live `<contactinfo>`; dupe/new-mult per band×grid, verified live (951
  QSOs). Remaining: operator resync trigger, give-up / run-vs-S&P signals, geometry-aware
  reachability (§3.14).
- [ ] **M4 — multi-instance + rotator + safety.**
- [ ] **M5 — WIMS op works one band on-air** via roster + click-to-work (one empty seat).
- [ ] **M6 — WIMS op covers multiple empty-seat bands**, smooth local⇄WIMS handoff (§4.2).
- [ ] **M7 — remote + multi-operator** over the internet; non-cooperative lease handoff (§4.5).

---

## Module implementation status (design: §3 table)

| § | Module | Status | Built / remaining |
|---|--------|--------|-------------------|
| 3.1 | UDP listener/parser | `[~]` | Heartbeat/Status/Decode parsed + unit-tested vs live captures (`udp/messages.py`, `udp/sink.py`); grid extracted. QSO-Logged/ADIF parsers written, not yet captured live. |
| 3.2 | UDP controller/sender | `[~]` | `udp/controller.py` + `udp/encode.py`: `reply()` / `halt()`, drives the emulator live. Remaining: Free Text/Replay, lease gating. |
| 3.3 | Multi-instance manager | `[~]` | **Seat agent (config/monitor slice):** `wims.agent` local UI :8790 + POST `/api/agents/report`; Status/Setup board. Config tool: `wsjtx_config.py`. Remaining: host fast mute, thumbnails, setup wizard apply, process service install. |
| 3.4 | Interlock / TX arbiter | `[~]` | `interlock/arbiter.py`: `TxArbiter` (≤1/group) + `OverlapDetector`; 5000-step stress + live bench, 0 overlap. Remaining: fast-mute path, lease gating, per-group config from profiles. |
| 3.5 | Decision / recommendation engine | `[~]` | Scoring built (`engine/scoring.py`): pluggable, explainable factors, condition weights. Roster builder (`engine/roster.py`). Remaining: run/S&P, give-up, geometry, persistent grid memory, grid→WSJT-X for logging. |
| 3.6 | Logger interface (N1MM) | `[~]` | seed (`integrations/n1mm/logdb.py`) + live `<contactinfo>` + `reconcile()` resync (`state/logstore.py`); dupe/mult self-computed. Remaining: `LogSource` backend abstraction, operator resync trigger. |
| 3.7 | GridTracker interface | `[ ]` | — |
| 3.8 | Rotator controller | `[ ]` | — |
| 3.9 | Safety / watchdog | `[ ]` | — |
| 3.10 | State store / logger | `[~]` | log copy + dupe/mult/resync (`state/logstore.py`, SQLite). Remaining: append-only JSONL event/decision stream. |
| 3.11 | Config | `[ ]` | scoring weights exist as defaults (`engine/scoring.py`); no Instance-Profile / config files yet. |
| 3.12 | Server API / integration hub | `[~]` | stdlib HTTP + SSE state contract (`server/state.py`), two pages. Remaining: command endpoints (click-to-work / click-to-point), lease endpoints, published enriched feed. |
| 3.13 | Override interface | `[ ]` | — |
| 3.15 | Network discovery & diagnostics | `[~]` | passive fleet discovery + health + expected-vs-actual + N1MM presence from **any** broadcast (`<RadioInfo>`/`<AppInfo>`, no QSO needed) — `discovery/fleet.py`. Remaining: active probes, GridTracker/rotator nodes, topology map. |

**Dashboard panels live (Phase-1):** interlock/overlap · call roster · instances · decode-activity ·
decode log · N1MM-sync · loggers · system summary.
**State-contract keys (`server/state.py`):** `instances, loggers, rx, interlock, roster, activity,
decodes, n1mm_sync`.

**Test bed (§5):** WSJT-X emulator built (`testbed/simulators/emulator.py`, reacts Reply→TX /
Halt→RX); interlock bench (`testbed/interlock_bench.py`). Remaining: captured-traffic replay, N1MM
stub, rotator stub, fast-mute harness.

**§2.6 roster feature backlog status:** A4/A5/A6, C1/C2 done; B3, C3, C4, D1, D3, the §3.15 pieces
partial; everything else missing — see the backlog table in wims_design.md §2.6 for priorities.

---

## Build log

- **2026-06-17** — §3.1 parser + read-only console monitor. N1MM log layer (DXLOG seed +
  `contactinfo` → `LoggedQso` → SQLite log copy with dupe/rover/mult + resync). Decode-activity
  map, fleet discovery, WSJT-X config validator, datagram encoder, WSJT-X emulator. M2 core:
  `TxController` + `TxArbiter` + `OverlapDetector` (5000-step stress + live bench, 0 overlap).
  §3.5 scoring engine. Browser dashboard: stdlib HTTP+SSE, state contract, first fleet panel live.
- **2026-06-19** — Interlock/overlap safety panel (live `OverlapDetector`, `--group-by`, overlap
  alarm verified live). Call-roster panel + M3 start (`RosterBuilder` + N1MM-fed dupe/mult, per
  band×grid, verified live). Decode-activity heatmap tiles. Decode-log + N1MM-sync panels →
  Phase-1 read-only sweep complete.
- **2026-06-20** — Startup `.s3db` seed (951 QSOs from `N2OY.s3db`). N1MM presence from any
  broadcast (RadioInfo/AppInfo — no QSO needed, for setup verification). Console split into two
  pages (Operate / Status), shared `wims.css`/`wims.js`. Fixed brittle `test_n1mm_log` (was pinned
  to volatile live-DB content). §2.6 roster feature backlog drafted into the design doc.
- **2026-07-09** — Compact UI density pass (row padding 6→2px, tighter header/`main`/`h2`, 13px
  base). **Call roster reworked GridTracker-style:** one row per station heard (all decodes, not
  CQ-only), score kept as a sortable column; new columns Calling / Mode / Freq (dial+df) / Az /
  UTC / Op-stub; needed-only + band filters, all headers sortable with sort/filter persisted across
  SSE ticks. New `to_call` decode field, `de_grid` captured on nodes, pure `engine/geo.py`
  (Maidenhead→bearing). Contract (`roster_to_dict`) now ships every row with `is_needed`/`az`/
  `freq_hz`/`operator_call`; roster/state tests updated to new semantics; `test_geo` added.
  Full suite + live validator green. **Still stubbed:** `operator_call` (band manager) pending the
  §3.14 fleet profile — shared with the planned per-operator table.
- **2026-07-13** — Design: fleet networking map
  ([wims_networking.md](wims_networking.md)) — Trailer 50×3 + 144×2, 222×1, 432×1; four N1MMs;
  WSJT-X port-per-band segregation; N1MM external multicast; console unicast. Deployment context
  in wims_design.md updated to match. Server still single-port WSJT-X join in code.
- **2026-07-13** — Design: **resilience & guided setup** (wims_networking.md §12) — contest
  profile, seat bring-up, continuous 🟢/🔴 readiness with plain-language fixes, fail-soft TX,
  MVP build order; §2.5 / S1 cross-links in wims_design.md. Not implemented in code yet.
- **2026-07-14** — **WSJT-X Outgoing interface** elevated to first-class setup/verify/monitor
  requirement (silent failure: decodes OK, WIMS blind). Design §1.1 / §3.14 / I1 + networking §4/§12;
  `wsjtx_config.py` errors on blank/`@Invalid`/loopback iface and loopback UDP Server (fleet mode);
  `--all` discovers Linux `WSJT-X - <rig>.ini`; `test_wsjtx_config` added.
- **2026-07-14** — networking.md **§4.1 Contest LAN interface** expanded: required/forbidden
  values, silent-failure lab case, operator steps, multi-homed rules, `wsjtx_config` gate, live
  monitoring, WIMS/N1MM iface parallels.
- **2026-07-14** — Fleet UX: **prune** WSJT-X nodes silent >120s (killed desktop no longer sticks
  as DEAD forever); activity “waterfall” tile created on Heartbeat/Status (empty band OK);
  id_collision uses recent-host window so desktop→VM move clears ⚠ id.
- **2026-07-14** — Multi-contest log selection: `logdb.list_contests` / `pick_contest` / filtered
  `read_dxlog(contest_nr=)`; auto-seed at startup; Status **Contest log** UI +
  `/api/contests/*` (no cryptic ContestNR CLI).
- **2026-07-15** — **Three-page console:** Operate / **Status** (live health & RF) / **Setup**
  (contest log picker, networking checklist, config diagnostics scaffold). Contest log moved off
  Status onto Setup; Status keeps one-line active-log pointer.
- **2026-07-15** — **Seat agent framework (local-first):** `python -m wims.agent` reads WSJT-X.ini +
  N1MM folder probe, shows operator report on `http://127.0.0.1:8790/`, optional export to site
  server `POST /api/agents/report`; state key `agents` on Status/Setup. Windows
  `Start-WimsAgent.cmd` (template seats). TX/interlock still later.
