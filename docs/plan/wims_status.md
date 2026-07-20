# WIMS — Build Status & Milestones

Companion tracker to **[wims_design.md](wims_design.md)** (the requirements / design source of
truth). This file holds **implementation progress only** — what's built, tested, and running —
and references design sections by their `§` numbers. When a *design* changes, edit
wims_design.md; when *code* lands, edit here.

Status: `[ ]` todo · `[~]` in progress · `[x]` done

---

## How to run (current)

```
# Solo single-PC (tester release): server + local WSJT-X + N1MM on one machine.
python -m wims.solo            # localhost, no presence; opens the browser
#   In WSJT-X: Settings → Reporting → UDP Server 224.0.0.73:2237, "Accept UDP requests" ON.
#   Windows: scripts\windows\Start-Wims-Solo.cmd   ·  Linux/macOS: scripts/start-wims-solo.sh

# Fleet / multi-host (site server):
python src/wims/server/app.py --iface 127.0.0.1
#   Operate:  http://localhost:8787/          (roster / work stations / arm TX)
#   Status:   http://localhost:8787/status    (live health, RF, decodes)
#   Setup:    http://localhost:8787/setup     (contest log, networking, config)
```
- **TX control (new):** Operate has a **DISARMED-by-default** master switch; once armed,
  per-row **Work** answers a station (Reply) and **Halt TX** is an always-on panic stop.
  Server flags: `--tx-host`/`--tx-port` (unicast WSJT-X, e.g. `127.0.0.1`; default is the
  multicast group, matching ingest), `--no-tx` (read-only), `--enable-cq-freetext`
  (experimental, off). **Call CQ is not a native WSJT-X UDP action** — see design §2.12.
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

## Tests — unit suites green (no pytest dep; run `python tests/unit/test_*.py`)
`test_messages` · `test_encode` · `test_emulator` · `test_arbiter` · `test_controller` ·
`test_scoring` · `test_roster` · `test_activity` · `test_fleet` · `test_n1mm_log` ·
`test_server_state` · `test_agent_report` · `test_presence` · `test_server_tx` · `test_solo_casual`

**One-command smoke validation:** `scripts/validate.sh` — runs the unit suites, an
import check, the interlock bench, and a **live** no-RF run (boots server + emulator,
captures one SSE frame, asserts the state contract + emulated instances flow through).
Exit 0 = all green; per-check logs land in `scratch/validate/` (gitignored). Overridable
via `WIMS_IFACE` / `WIMS_HTTP_PORT` / `WIMS_INSTANCES` / `PYTHON`.

---

## Milestones (design intent: §4 / §4.5)

- [~] **R0 — Solo FT8 tester release.** One PC (N1MM + WSJT-X + WIMS server), single FT8
  frequency (any band, HF included): watch the ranked roster, verify needed↔dupe by editing
  the N1MM log, **arm TX** and **Work** a station (Reply). `python -m wims.solo` + Windows/Linux
  wrappers. **Done in code & bench/emulator-verified:** click-to-work + halt endpoints, DISARMED
  master switch, arbiter grant/release, `tx` state block, casual (non-contest) seed. **Remaining
  before shipping:** first bring-up against **real WSJT-X** into a dummy load (echo-exactness of
  Reply), the **Call CQ spike** (§2.12), and a tester runbook.

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
  QSOs). Operator **Resync log** (DXLOG re-read) done. Remaining: give-up / run-vs-S&P,
  geometry-aware reachability (§3.14), **cross-band opportunity factor (C7)** from prior-contest
  history.
- [ ] **M4 — multi-instance + rotator + safety.** Rotator: Yaesu/K3NG status + click-to-point
  from roster Az (§2.10 / §3.8).
- [ ] **M5 — WIMS op works one band on-air (S&P + tailend)** via roster + click-to-work → Reply
  echoing retained decode (CQ or **73**; GT2 pattern) on one empty seat; Free Text + optional
  closing QSY (G4 / §2.8). **Not** Call CQ — run/autorespond is WSJT-X UI (§2.12).
- [ ] **M6 — WIMS op covers multiple empty-seat bands (S&P + tailend)**, smooth local⇄WIMS handoff
  (§4.2); local run remains seat/RDP WSJT-X (§2.12).
- [ ] **M7 — remote + multi-operator** over the internet; non-cooperative lease handoff (§4.5).

---

## Module implementation status (design: §3 table)

| § | Module | Status | Built / remaining |
|---|--------|--------|-------------------|
| 3.1 | UDP listener/parser | `[~]` | Heartbeat/Status/Decode parsed + unit-tested vs live captures (`udp/messages.py`, `udp/sink.py`); grid extracted. QSO-Logged/ADIF parsers written, not yet captured live. |
| 3.2 | UDP controller/sender | `[~]` | `udp/controller.py` + `udp/encode.py`: `reply()` / `halt()`, `for_unicast`/`for_group`. **Now wired into the server**: `/api/tx/arm\|work\|halt\|cq`, **DISARMED-by-default** master switch, click-to-work from the roster (`RosterBuilder.entry_for` recovers the raw Decode to echo), arbiter grant/release. Verified vs emulator (arm→work→halt) + `test_server_tx`. Reply = echo retained Decode (CQ **or 73 tailend**, GT2 pattern — §2.12). **No product Call CQ** (`call_cq` not-supported; gated `--enable-cq-freetext`). Remaining: **real-WSJT-X bring-up**, **Free Text** (closing/QSY §2.8), Replay. |
| 3.3 | Multi-instance manager | `[~]` | **Seat agent** (§3.3.1): config/setup test + report + discovery **built**; remaining matrix: **interlock mute**, **rotator I/O**, thumbnails, process lifecycle, readiness, watchdog fail-safe. |
| 3.4 | Interlock / TX arbiter | `[~]` | `interlock/arbiter.py`: `TxArbiter` (≤1/group) + `OverlapDetector`; 5000-step stress + live bench, 0 overlap. **Arbiter now gates real TX** in the server: Work does `request()`, released on Halt and on the WSJT-X `Status` TX→RX edge; `holders()` on the `tx` state block. Remaining: fast-mute path, per-group config from profiles. |
| 3.5 | Decision / recommendation engine | `[~]` | Scoring built (`engine/scoring.py`): pluggable, explainable factors, condition weights. Roster builder (`engine/roster.py`). Remaining: **advisory** run/S&P (run ≠ actuator — §2.12), give-up, geometry, persistent grid memory, grid→WSJT-X for logging, **`cross_band` factor (C7)** + prior-contest station history. |
| 3.6 | Logger interface (N1MM) | `[~]` | seed + live `<contactinfo>`/`delete`/`replace` + operator `POST /api/log/resync` → `reconcile()`; dupe/mult self-computed. Remaining: `LogSource` backend abstraction; **prior-contest band-history seed for C7** (not this-contest dupes). |
| 3.7 | GridTracker interface | `[ ]` | — |
| 3.8 | Rotator controller | `[ ]` | **Design:** Yaesu/K3NG; Az ant + Az DX; font while rotating; click-to-point (§2.10). Code not started. |
| 3.9 | Safety / watchdog | `[ ]` | — |
| 3.10 | State store / logger | `[~]` | log copy + dupe/mult/resync (`state/logstore.py`, SQLite). Remaining: append-only JSONL event/decision stream. |
| 3.11 | Config | `[ ]` | scoring weights exist as defaults (`engine/scoring.py`); no Instance-Profile / config files yet. |
| 3.12 | Server API / integration hub | `[~]` | stdlib HTTP + SSE state contract (`server/state.py`), three pages. Remaining: **subscribe API (§2.11)**, click-to-work/point, claims; roster contract **`az_ant` / `rotator_moving` / Az DX**; published enriched feed. |
| 3.13 | Override interface | `[ ]` | — |
| 3.15 | Network discovery & diagnostics | `[~]` | passive fleet discovery + health + N1MM any-broadcast presence (`discovery/fleet.py`); **site-server presence plane E** (`discovery/presence.py` — dual-server refuse + agent clickable URLs). Remaining: active probes, expected-vs-actual board, topology map. |

**Dashboard panels live (Phase-1):** interlock/overlap · call roster · instances · decode-activity ·
decode log · N1MM-sync · loggers · system summary · **seat agents** (Status table + Setup detail).
**State-contract keys (`server/state.py`):** `instances, loggers, rx, interlock, roster, activity,
decodes, n1mm_sync, agents, tx`. Each roster candidate now carries a stable `id`
(`instance|call|grid`) for click-to-work; `tx` = `{enabled, armed, can_tx, controller, holders,
cq_enabled, last_action}`.

**Test bed (§5):** WSJT-X emulator built (`testbed/simulators/emulator.py`, reacts Reply→TX /
Halt→RX); interlock bench (`testbed/interlock_bench.py`). Remaining: captured-traffic replay, N1MM
stub, rotator stub, fast-mute harness.

**§2.6 roster feature backlog status:** A4/A5/A6, C1/C2 done; B3, C3, C4, D1, D3, the §3.15 pieces
partial; everything else missing — see the backlog table in wims_design.md §2.6 for priorities.
**New (design only):** **C7** / §2.9 cross-band evidence; **G4** / §2.8 QSY free text; **G5** /
**§2.10** rotator Az ant/Az DX + rotating font; **E1b** / **§2.11** band subscribe → roster;
**G6** / **§2.12** run vs S&P/tailend (Reply = WIMS incl. 73; run = WSJT-X UI).

### Design / feature todos (not yet coded)

- [ ] **C7 / §2.9 — Cross-band evidence + `cross_band` factor** — ship **structured evidence**
  (other needed bands, this-contest vs prior-contest source, seat readiness, suggested QSY) on
  the state contract so the operator can **assess other-band contact ability**; optional rank
  boost is secondary. History never becomes live dupe. Design: wims_design.md §2.9 / §3.5.
- [ ] **Prior-contest station history** — seed `call → bands` from multi-contest N1MM `DXLOG`
  without affecting live dupe/mult. Feeds §2.9 evidence panel + scoring. Design: §3.6.
- [ ] **G4 / §2.8 — Closing free text / QSY (assess-then-decide)** — Free Text UDP encode + live
  verify; work/complete dialog shows §2.9 evidence; operator **explicitly chooses** accept
  suggestion / other band / skip (default plain 73). Never auto-QSY. Claim-gated.
  Design: wims_design.md §2.8 / §2.9 / §1.1.
- [ ] **E1b / §2.11 — Subscribe to station/band → call roster** — operator subscription selects
  which fleet bands’ decodes appear on *their* roster; server still ingests all. Multi-op
  widget shows subscriptions. Distinct from TX claim. Design: wims_design.md §2.11 / §2.7.
- [ ] **G5 / §2.10 — Rotator status & control (Yaesu / K3NG)** — K3NG/Yaesu backend; state
  `rotators` + roster **Az ant** (live antenna az) and **Az DX** (bearing to other station).
  **Az ant uses a different font while actively rotating** (`rotator_moving`). Click-to-point
  from Az DX; soft limits; stop/park. Prefer **seat agent** owns serial (§3.3.1). Design:
  wims_design.md §1.4 / §2.10 / §3.8 / §3.3.1.
- [ ] **G6 / §2.12 — Run vs S&P + tailend boundary** — design **done** (2026-07-20, revised same
  day): S&P/tailend = WIMS Reply on retained decode (CQ **and** **73**, GT2 `initiateQso`);
  run/CQ + pile autorespond = WSJT-X UI only; no product Call CQ. Remaining code/UI: observe
  `tx_role` / run banner, click-to-work on CQ/73, Tailend label, help text for empty-seat run via
  seat/RDP. Design: wims_design.md §2.12 / §1.1 / §4.2.
- [ ] **§3.3.1 — Seat agent capability matrix (beyond config audit)** — per station agent:
  setup test (**done**); **interlock** sensor (SSB/CW CTS) + fast mute actuator (WSJT-X host);
  **rotator** status/control (K3NG); thumbnails; process lifecycle; local readiness; watchdog
  fail-safe. Design: wims_design.md §3.3.1.

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
- **2026-07-15** — Agent default **one-shot**; `--daemon` + `Start-WimsAgent-Continuous.cmd` for
  continuous export. Seat pack: kill-then-start N1MM/WSJT-X/agent (`Start-WimsSeat.cmd`, Startup
  install). N1MM process = `N1MMLogger.net.exe`; DBs under registry UserDir\\Databases.
  Server handoff: [wims_agent_dashboard.md](wims_agent_dashboard.md).
- **2026-07-15** — **Live N1MM delete/edit:** handle `<contactdelete>` (remove by ID → roster
  needed/dupe restores) and `<contactreplace>` (upsert). Log was append-only on `<contactinfo>`
  so a deleted QSO stayed greyed until DXLOG resync.
- **2026-07-15** — **Manual log resync:** `POST /api/log/resync` re-reads active contest DXLOG →
  `reconcile()` (add/update/delete by ID). Setup **Resync log** button + last-resync line;
  Status N1MM panel shows last resync summary/age. UDP remains live path; resync is safety net
  (copy fresh `.s3db` first if N1MM is remote). Setup contest list is ephemeral (Rescan → pick/cancel).
- **2026-07-15** — **Seat agent display fix:** Setup never painted agent detail because
  `renderAgents` returned early when `#agents-body` (Status-only) was missing. Setup now shows
  full WSJT-X/N1MM config audit; Status table adds process columns. Plan: [wims_agent_dashboard.md](wims_agent_dashboard.md).
- **2026-07-15** — **Plane E site-server presence (MVP):** multicast announce
  `224.0.0.73:8788` ~1 Hz (`discovery/presence.py`). Second server listens ~2 s then **refuses**
  (or demotes if a peer appears later) with peer URL diagnostics. Agents discover and show
  clickable Operate/Status/Setup on local `:8790` (zero-memory). Flags: `--no-presence`,
  `--force-server`, agent `--no-discover`. Design: [wims_networking.md](wims_networking.md) §3.1.
- **2026-07-16** — **Discovery hardened for zero-memory:** multi-NIC multicast + limited/directed
  broadcast announce; agent cascade UDP → HTTP `/healthz` /24 probe; rich `/healthz` with
  `role`/`console_base`/`urls`. Operators should not need `WIMS_SERVER` on the contest LAN.
- **2026-07-18** — Design only (no code): **closing free text / QSY on final 73** (§2.8, backlog
  G4) — WIMS supports operator-chosen Free Text (e.g. `QSY 432`) at QSO complete. **Cross-band
  opportunity (C7 / §2.9):** evidence-first so the operator can **assess other-band contact
  ability** and **decide** whether to use a QSY suggestion; score boost is secondary, never
  auto-applied (skip/plain 73 is default). Prior-contest history via §3.6 seed (evidence/scoring
  only, not live dupes). Scenarios S6b/S6c + open questions. Status todos listed above.
- **2026-07-18** — Design only: **rotator status & control** (§2.10, G5) — primary backend
  **Yaesu GS-232 via K3NG**; roster **Az ant** (antenna) + **Az DX** (to other station); **Az ant
  different font while rotating**; click-to-point from Az DX. **Band/station subscription**
  (§2.11, E1b) — subscribe populates that operator’s call roster with those bands’ decodes.
  Scenarios S5c/S5d.
- **2026-07-20** — Design only: **Run vs S&P / CQ control boundary (§2.12, G6)**. WSJT-X UDP has
  no usable Call CQ or run-autorespond. **Click-to-work = Reply** echoing retained Decode
  (GridTracker2 `initiateQso`): not CQ-only — WSJT-X 3.0.1 also auto-TX on **`73 `** (**tailend**).
  Product path: WIMS **S&P + tailend**; **run** stays in seat WSJT-X UI (or RDP). FreeText CQ
  lab-only. M5/M6 + scenarios S2/S2a/S2b/S6 updated. **README** aligned (S&P/tailend vs run).
- **2026-07-18** — Design: **§3.3.1 seat agent matrix** — each station runs an agent for setup
  test (**built**), interlock (sensor/actuator), rotator I/O, plus thumbnails, process lifecycle,
  readiness, discovery, fail-safe. Server keeps roster/score/claims/log.
- **2026-07-20** — **R0 solo-tester TX path (code).** First TX wiring into the server:
  `/api/tx/arm|work|halt|cq`, **DISARMED-by-default** master switch (fail-safe; a human always
  initiates), roster **click-to-work** (Reply, `RosterBuilder.entry_for` recovers the raw Decode),
  always-on **Halt** panic, `TxArbiter` grant on Work / release on Halt + WSJT-X TX→RX edge.
  `tx` state block + per-row roster `id`; Operate arm/Work/Halt/CQ controls. **`python -m wims.solo`**
  launcher (localhost, `--no-presence`) + `Start-Wims-Solo.cmd` / `start-wims-solo.sh`;
  `TxController.for_unicast`; server `--tx-host/--tx-port/--no-tx/--enable-cq-freetext`. **Call CQ is
  gated off** — no native WSJT-X UDP CQ (design §2.12); pending a live spike. Verified: `test_server_tx`
  (10), `test_solo_casual` (non-contest "DX" HF seed → needed↔dupe flip on log edit), live emulator
  arm→work→halt, `validate.sh` 21/21. **Not yet:** first real-WSJT-X bring-up, tester runbook.
  *Found (pre-existing, not R0):* on **loopback**, the plane-E presence announce on the shared
  `224.0.0.73` group starves the WSJT-X multicast ingest (0 pkts) — `validate.sh` live check now runs
  `--no-presence` (single-host); `wims.solo` already defaults `--no-presence`, so solo is unaffected.
