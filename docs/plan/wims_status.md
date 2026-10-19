# WIMS — Build Status & Milestones

Companion tracker to **[wims_design.md](wims_design.md)** (the requirements / design source of
truth). This file holds **implementation progress only** — what's built, tested, and running —
and references design sections by their `§` numbers. When a *design* changes, edit
wims_design.md; when *code* lands, edit here.

Status: `[ ]` todo · `[~]` in progress · `[x]` done

---

## How to run (current)

1. Put **WIMS** on the Desktop and in the Start menu (Linux: the app menu).
   Windows: double-click `scripts\Add WIMS to Desktop.bat`.
   Linux or Mac: `./scripts/add-wims-to-desktop.sh`.
2. Double-click **WIMS**. That is the same window as `scripts/start-wims.sh`
   and the Windows WIMS shortcut. Start Operate or the site server there.
   The browser opens at `http://localhost:8787/`. A second double-click
   brings the WIMS window that is already open to the front.
3. On one PC with WSJT-X, **Start-Wims-Solo** (`scripts/start-wims-solo.sh` or
   `scripts\windows\Start-Wims-Solo.cmd`) uses that same Operate start and
   opens the browser.
   In WSJT-X: Settings → Reporting → UDP Server `224.0.0.73:2237`, Accept UDP
   requests ON. Plane A is one port for all bands (decision 2026-09-05).
4. First Windows install: double-click `scripts\windows\Install-Wims.cmd`.
   Setup check: `Check-WimsSetup.cmd`, or the WSJT seat check in the WIMS window.
   Compare logs: double-click **Check logs**, or open the Log page → **Check logs**.
   `Add WIMS to Desktop` puts **Check logs** next to **WIMS**.

Checklist: [design-principles.md](../design-principles.md).

### Developer

Typed commands are for people changing WIMS. From the repo root the checkout
shim finds `src/` with no path variable: `python3 -m wims version`,
`python3 -m wims solo --no-open`, `python3 -m wims.logaudit`.
One-command smoke: `tools/dev/validate.sh`.

- **Zero-memory start:** site server defaults to plane A **`2237` only**
  (`FLEET_WSJT_PORTS`); `Start-WimsServer.cmd` auto-picks LAN iface. Solo uses
  the same port. Lab escape is a port list on the developer command.
- **TX control:** **no global arm / Enable TX** — roster **line click** = Work (Reply),
  **Halt TX** stops this console’s Work only (two bands from the same console → both).
  Server flags: `--tx-host`/`--tx-port` (unicast WSJT-X), `--no-tx`
  (read-only), `--enable-cq-freetext` (experimental, off). **Call CQ** is WSJT-X UI only (§2.12).
- **Log seed:** scans N1MM contest `.s3db` file(s) for **multiple contest instances**.
  Startup order: **`--seed-db` (that file only + remember)** → **last Setup pick**
  (host `last_log.json`) → **auto** latest dated contest with QSOs. Loads only that
  contest instance (not whole multi-year DXLOG). Setup picker + Resync; no ContestNR
  CLI in normal operation. Pref path: `$XDG_CONFIG_HOME/wims/last_log.json` or
  `~/.config/wims/…` (Windows `%APPDATA%\wims\`), override `WIMS_LAST_LOG`.
- **Ingest:** multicast `224.0.0.73:2237` (plane A). Digi → N1MM is **N1MM agent Log**
  (reader OFF). Presence/contacts: Broadcast Data → `127.0.0.1:12060` → agent → site.
  Map: **[wims_networking.md](wims_networking.md)** + **[operator_setup.md](../operator_setup.md)**.
- **Seat CAT stack (design):** preferred **Icom + wfview** path in networking **§3.2–§3.3**
  (WIMS never owns radio COM; RigCtld must be explicitly enabled in wfview).
- **No-RF test bed:** `python testbed/simulators/emulator.py --iface 127.0.0.1 --instances ROY-6M:50313000,CHIP-2M:144174000,TRL-432:432174000`
- **Interlock bench:** `python testbed/interlock_bench.py`

## Tests — unit suites green (no pytest dep; run `python tests/unit/test_*.py`)
`test_messages` · `test_encode` · `test_emulator` · `test_arbiter` · `test_controller` ·
`test_scoring` · `test_roster` · `test_activity` · `test_fleet` · `test_n1mm_log` ·
`test_server_state` · `test_agent_report` · `test_presence` · `test_server_tx` · `test_solo_casual` ·
`test_rotator` · `test_last_log` · `test_inhibit` · `test_key_discovery`

**One-command smoke validation:** `tools/dev/validate.sh` — runs the unit suites, an
import check, the interlock bench, and a **live** no-RF run (boots server + emulator,
captures one SSE frame, asserts the state contract + emulated instances flow through).
Exit 0 = all green; per-check logs land in `scratch/validate/` (gitignored). Overridable
via `WIMS_IFACE` / `WIMS_HTTP_PORT` / `WIMS_INSTANCES` / `PYTHON`.

**GitHub CI / release track:** `.github/workflows/ci.yml` runs the same `tools/dev/validate.sh`
on push/PR to `main` (Python 3.10 / 3.12 / 3.14) plus a `pyproject.toml` ↔
`wims.__version__` pin check. **Release design:** [wims_release_packages.md](wims_release_packages.md)
(rev 4). **Scaffolding landed:** root `install.sh` / `install.ps1`, `scripts/install-linux.sh`,
`tools/dev/packaging/write_manifest.py`, allow-list `tools/dev/package-release.sh`,
`release.yml` + `tester-packages.yml`, [INSTALL.md](../../INSTALL.md). Artifacts:
`wims-<ver>-windows-x86_64.zip` + `wims-<ver>-linux-x86_64.tar.gz` (omit `hardware/`);
Windows **bundled CPython+Tk** still PR 0/5. Tag scheme: numeric `__version__` +
`vX.Y.Z[-tester|-rcN]`. **Current release:** [`v1.0.16`](https://github.com/wa1hco/WIMS/releases/tag/v1.0.16).

**Tester product surface:** [docs/tester_roles.md](../tester_roles.md) — what installers
and launchers mean (solo / server / seat agent; KEY agent out of R0).

---

## Milestones (design intent: §4 / §4.5)

- [~] **R0 — Solo FT8 tester release.** One PC (N1MM + WSJT-X + WIMS server), single FT8
  frequency (any band, HF included): watch the ranked roster, verify needed↔dupe by editing
  the N1MM log and **click a roster line** to Work (Reply). `python -m wims.solo` + Windows/Linux
  wrappers. **Done:** roster-line **Work** (GT2, no global arm) + Halt, arbiter grant/release,
  `tx` state block, casual (non-contest) seed, **CI green gate**, GitHub Release
  [`v1.0.0`](https://github.com/wa1hco/WIMS/releases/tag/v1.0.0). **Remaining:**
  first bring-up against **real WSJT-X** into a dummy load (echo-exactness of Reply).

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
  from roster Az (§2.10 / §3.8):
  - [ ] **Show antenna pointing** — live az (and el when present) in the browser (Status / Operate)
  - [ ] **Command: rotate to azimuth** — operator enters or selects a bearing; WIMS commands the rotator
  - [ ] **Rotate to WSJT-X / roster DX az** — point at DX azimuth (decode grid / roster `az`);
    human initiates, never unattended slew
  - [ ] Backend: Yaesu GS-232 via K3NG (primary design); soft limits; serialize multi-rotator moves
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
| 3.2 | UDP controller/sender | `[~]` | `udp/controller.py` + `udp/encode.py`: `reply()` / `halt()`. Server: `/api/tx/work\|halt` — **no global arm**; roster line click = Work (GT2). Arbiter grant/release; `test_server_tx`. Reply = echo retained Decode (CQ **or 73 tailend**). Reply socket is unbound (OS picks the route; no path → plain sentence). **No product Call CQ**. Remaining: real-WSJT-X bring-up, Free Text (QSY §2.8), Replay. |
| 3.3 | Multi-instance manager | `[~]` | **Seat agent** (§3.3.1): config/setup test + report + discovery **built**; remaining matrix: **interlock mute**, **rotator I/O**, thumbnails, process lifecycle, readiness, watchdog fail-safe. |
| 3.4 | Interlock / TX arbiter | `[~]` | `interlock/arbiter.py`: `TxArbiter` (≤1/group) + `OverlapDetector`; 5000-step stress + live bench, 0 overlap. **Arbiter now gates real TX** in the server: Work does `request()`, released on Halt and on the WSJT-X `Status` TX→RX edge; `holders()` on the `tx` state block. Remaining: fast-mute path, per-group config from profiles. |
| 3.5 | Decision / recommendation engine | `[~]` | Scoring built (`engine/scoring.py`). Contest rules are a separate object (`engine/contest_rules.py`): ARRL VHF and NY QSO Party JSON files. Setup **Goal** menu: contest, award (DXCC, WAS, VUCC), just operating (WSJT-X Colors or a checklist), or custom. County and callsign prefix stay off (no list shipped). Logged contacts are the already-have list. Log to use is the log; Just operating uses WSJT-X Colors against that log. Remaining: **advisory** run/S&P (run ≠ actuator — §2.12), give-up, geometry, persistent grid memory, grid→WSJT-X for logging, **`cross_band` factor (C7)** + prior-contest station history. NYQP new-mult stays off (`per: unverified`). |
| 3.6 | Logger interface (N1MM) | `[~]` | Log to use on the Log page: the operator’s log, or a Goal suggestion (contest → newest matching N1MM; otherwise WSJT-X). Count-since / count-until change the needed/dupe lookup. N1MM seed + live contact UDP + resync when that contest file is the log. The selected file is re-read about once a second, before the roster is scored, and a locked read does not wipe the copy. A logged contact clears needed and Mult on the next push. The mult badge names the square, the band, and the log. Per-instance `wsjtx_log.adi` discovery and Log-page warnings. **Check logs** is on the Log page (summary first; shared files count once). The N1MM tab lists several stations and stays hidden when fewer than two are heard. Remaining: native Log4OM/CQRLOG, GridTracker roster filters (L9), challenge pace UI, **prior-contest band-history seed for C7**. |
| 3.7 | GridTracker interface | `[ ]` | — |
| 3.8 | Rotator controller | `[~]` | **Started:** `integrations/rotator/` (GS-232 dialect, SimRotator, RotatorRegistry); server `--sim-rotator`, agent `WIMS_ROTATOR_*` / report `rotators[]`; state `rotators` + roster `az_ant`/`delta_az`/`rotator_moving`; API `POST /api/rotator/point|stop`; UI Az ant (italic while slewing) + click Az DX. Remaining: live K3NG TCP/serial on agent, command relay seat←server, soft limits from profiles. |
| 3.9 | Safety / watchdog | `[ ]` | — |
| 3.10 | State store / logger | `[~]` | log copy + dupe/mult/resync (`state/logstore.py`, SQLite). Remaining: append-only JSONL event/decision stream. |
| 3.11 | Config | `[ ]` | scoring weights exist as defaults (`engine/scoring.py`); no Instance-Profile / config files yet. |
| 3.12 | Server API / integration hub | `[~]` | stdlib HTTP + SSE state contract (`server/state.py`), three pages. Remaining: **subscribe API (§2.11)**, click-to-work/point/set-az, claims; roster **`az_ant` / `rotator_moving` / Az DX**; published enriched feed. |
| 3.13 | Override interface | `[ ]` | — |
| 3.15 | Network discovery & diagnostics | `[~]` | passive fleet discovery + health + N1MM any-broadcast presence (`discovery/fleet.py`); **site-server presence plane E** (`discovery/presence.py` — dual-server refuse + agent clickable URLs). Remaining: active probes, expected-vs-actual board, topology map. |

**Dashboard panels live (Phase-1):** interlock/overlap · call roster · instances · decode-activity ·
decode log · N1MM-sync · loggers · system summary · **seat agents** (Status table + Setup detail).
**State-contract keys (`server/state.py`):** `instances, loggers, rx, interlock, roster, activity,
decodes, n1mm_sync, agents, tx`. Each roster candidate now carries a stable `id`
(`instance|call|grid`) for click-to-work; `tx` = `{enabled, can_tx, controller, holders,
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

- [~] **§2.13 — Fleet inventory & dynamic membership** — **Slice 1 done:** state key `bands`
  (per-band WSJT + N1MM aggregation), Status **Band inventory** table, instance `share_policy`.
  Remaining: logger binding verify, KEY/SSB rows, operator sessions, KEY list churn.
  Design: wims_design.md §2.13.
- [~] **§2.14 — Band sharing policy `interlock` | `coordinated`** — **Slice 1 done:** default
  `coordinated`; `--interlock-band BAND`; `POST /api/band/policy`; badges on Status; inhibit
  placeholder on instances when interlock. Remaining: KEY actuation gate on policy, soft
  “wants the band”, Operate banner. Design: wims_design.md §2.14.
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
- [x] **L1 — Contest rules interface (no verdict change).** `arrl-vhf.json` is the
  default `LogStore` rule. `is_dupe` / `is_new_mult` delegate to it. Scoring tests
  stay green.
- [x] **L2 — One Contest dropdown and a plain summary.** `contest_rules.json`
  (schema 3) beside `last_log.json`. Setup → Contest. Advanced stays collapsed.
  Each Advanced control has a plain-language tip (hover and a keyboard ?).
  No new CLI flag. Alias suggestion does not override an explicit Just operating
  choice. Just operating stays WSJT-X Colors on whatever log is selected.
  Superseded in the UI by L10; the saved file still migrates.
- [x] **L10 — Goal menu.** Setup → Goal, then a second menu (contest, award,
  worth working, or your list). “Just operating (not a contest)” replaces the
  old empty Contest choice and still uses WSJT-X Colors. Awards: DXCC, Worked
  All States, VUCC. Checklist adds state or province and call, each overall /
  per band / per mode. County and callsign prefix show as coming soon. Schema 3
  `contest_rules.json` keeps the saved contest. Advanced stays collapsed.
- [x] **L3 — Rules files, NY QSO Party first, Colors fallback.** `nyqp.json` from
  the published v1.1 rules (2026-09-25). FT8/FT4 banned. County change resets.
  `per: unverified` does not mark new mults. Colors ini bools are read;
  `DecodeHighlighting` is not. Without `cty.dat`, the four call/grid categories
  start on (see the design note in §3.6).
- [x] **L4 — WSJT-X log discovery + “log not accessible” warning.** Per-instance
  data dirs, shared path, Log page **Each radio’s log** lines, solo check **Logs** section.
- [x] **L5 — `WsjtxAdifLogSource` seeds the log copy.** Used when that log is
  the one selected under Log to use. Shared path is the only file when set.
  UDP type 5/12 uses the same id. An N1MM contest file is the log only when
  the operator chose it, or a contest Goal suggested the newest matching one.
- [x] **L11 — Log to use.** The Log page shows the log name, path, contact count,
  and cutoff. The operator picks the log. The Goal only suggests one when
  nothing is saved (contest → newest matching N1MM log; anything else →
  WSJT-X). Start now and This year change the needed/dupe lookup. A saved
  choice reloads immediately and stays across Goal changes. Setup no longer
  holds log controls. The N1MM tab is the multi-station list.
- [x] **L6 — Check logs.** ADIF, the N1MM log chosen in WIMS, optional LoTW.
  Summary first. Text + JSON. Read-only. Several instances on one file (same
  path, same inode, or the same bytes) are one log.
- [x] **L7 — Check logs window.** GridTracker `*.adi` under the GridTracker
  data folder when present. LoTW is a note, not a failure. Log page
  **Check logs**, and the Desktop **Check logs** icon, show the same summary
  with **Show details**. A path that does not answer within
  2 seconds is unreadable. Unchanged files are not read again. The live Log
  page log-access poll is still not on that timer.
- [~] **L8 — Further log readers.** Any logger’s ADIF export is `--adif PATH`.
  No Log4OM / DXKeeper / CQRLOG native database.
- [~] **L9 — GridTracker roster fallback.** If Advanced sets the fallback to
  GridTracker and the settings file is not a plain JSON we can read, needed
  uses WSJT-X Colors and says so. LevelDB filters are not read. No writes.

---

## Build log

- **2026-10-19** — **CX4BAN stayed a Mult with a blank grid.** WSJT-X wrote `<gridsquare:0>` on the new 20 m line. The 2021 GF15 contact is on 40 m, so it does not clear 20 m. The CQ `CQ DX CX4BAN GF15` is the square. The next roster push copies that square onto the blank log line, and the station is worked rather than a mult. Hover names the square, the band, and the log. Tests: `tests/unit/test_roster_logged.py`.
- **2026-10-19** — **Roster Mult after a logged contact.** Logging a contact updates needed and Mult on the next roster push (the page refresh, about one second). Log to use is the only log that counts. A contact in a different file stays a multiplier, and WSJT-X Colors does not switch logs. N1MM's meter band `2` is 2 m, an empty N1MM grid is taken from the decode, and a 6-character grid matches the 4-character square. The mult badge tip names the square, the band, and the log. A contact on another band, a portable suffix, or a contact before Start now still shows Mult, and the tip says why. Tests: `tests/unit/test_roster_logged.py`.
- **2026-10-18** — **Version `1.0.17`**. `pyproject.toml` and `wims.__version__` are `1.0.17`. Release notes: [v1.0.17](../releases/v1.0.17.md). The git tag and GitHub Release are not cut yet.
- **2026-10-18** — **Operate Message column.** Roster shows the exchange after the callsigns (R-12, RR73, 73, a grid, or leftover QSY / free text) in Message, just after Calling. A saved column set gains it once. Hover the cell for the full decode. No transmit change.
- **2026-10-18** — **Second double-click raises the WIMS window.** The desktop
  icon, `scripts/start-wims.sh`, and the Windows shortcut share one start.
  When the window is already open, another start brings it forward
  (un-minimized, raised, and focused) and does not open the site console.
  If that window does not answer, WIMS says what to do next.
  Tests: `tests/unit/test_launcher_handoff.py`.
- **2026-10-18** — **Updates list dates use this PC's local day.** A version tagged late in the evening shows that date, not the next UTC day. The row tip includes the local time.
- **2026-10-18** — **Operate max age labels.** The pulldown reads 15 sec, 30 sec, 1 min, 2 min, 3 min, and 5 min (values unchanged) so “2 min” is not the 2M band checkbox.
- **2026-10-18** — **Updates list, row tips, and a fitted window.** The Updates
  list merges published releases with version tags that have no release, newest
  first, so v1.0.11–v1.0.16 (and the older unreleased tags) show up. A tag with
  no notes uses the commits since the previous tag. Hovering a row shows that
  row. Restart site server names the revision the server loaded and whether it
  matches the installed code. The title and the line under WIMS label the
  launcher (loaded when the window opened) and the server (loaded when the
  server started). The window height fits through Other tools…; checking that
  box grows the window up to the screen, then the extra tools scroll.
  Unchecking returns to the compact height.
- **2026-10-18** — **Restart needed when the site server is on older code.**
  The site server records the git revision it loaded (`server_rev` on
  `/healthz`, existing fields unchanged). The WIMS window re-reads the
  checkout on each refresh and after an install, and marks **Restart site
  server** when this PC’s server is stale. The window shows both revisions.
  After Install, the Updates list says to restart the server to finish.
  **Other tools…** stays put; the extra tools open below it and scroll, and
  unchecking snaps the window back to the compact size.
  Tests: `tests/unit/test_server_rev.py`.
- **2026-10-17** — **Log page.** Log to use, the count-since presets, per-radio
  log warnings, the shared WSJT-X file, Check logs, and N1MM resync moved off
  Setup onto `/log`. The operator picks the log WIMS checks for needed and
  already worked. The line shows the name, path, contact count, and cutoff. A
  contest Goal suggests the newest matching N1MM log; Just operating, an award,
  or a custom list suggests the WSJT-X log. A saved choice wins and reloads
  without a restart. Start now and This year set a count-since time; an
  optional end time is a separate field. The window changes the lookup, and
  “how often a station counts” still applies inside it. WSJT-X ADIF has no
  contest name or exchange, and the Log page says so. The N1MM tab lists
  several stations and stays hidden when fewer than two are heard. Challenge
  pace (worked, elapsed, rate) is a follow-up in
  [wims_logs_and_rules.md](wims_logs_and_rules.md) §2.5.
- **2026-10-17** — **One start, and an Updates list on the WIMS window.** The
  desktop icon, `scripts/start-wims.sh`, and the Windows shortcuts open the
  same window (Update, Restart site server, Open site console stay). Operate
  from that window and from Start-Wims-Solo share one start: port 8787 and
  `/healthz`, seat reading, network default, log and rules, browser, messages,
  and `scratch/launcher-details.log`. The window lists published releases
  (version, date, notes). Check now and a look every few hours (not faster
  than every 15 minutes) run in the background. Install and Go back are
  buttons. Nothing installs by itself. Offline and GitHub rate limits stay
  quiet. Design: [wims_design.md](wims_design.md) (Launch and updates).
- **2026-10-17** — **Check logs is a summary, and it finishes.** Pairing had been
  every contact against every later contact: 1,000 contacts in two logs 0.08 s,
  5,000 in 1.9 s, 15,000 in 19.7 s, while reading a 15,000-contact file took
  about 0.3 s. Discovery parsed each instance log again inside that loop, and a
  dead network path had no timeout. The same bytes were also reported once per
  instance. Check logs now groups by call, band, mode, and a 3-minute window
  (20,000 contacts in two logs, 50 missing, about 1 s including the read).
  Shared path, inode, or identical file is one log. The first line is the
  summary; **Show details** lists only contacts missing from a log. Size and
  modification time skip an unchanged file. Desktop **Check logs** opens the
  same check as the Log page. The Check logs button keeps its ? tip.
- **2026-10-17** — **CI green: Windows KEY tests, interlock bench, unbound
  Work socket.** `test_key_cts` drives the Win32 path with a fake kernel32 on
  Linux (`ctypes.get_last_error` is absent there, and `COM7` is not a device).
  The interlock bench sends Reply on a multicast socket so the emulator still
  hears it. The unicast reply socket is not bound to the listen address (solo
  `127.0.0.1` could not reach another source: Linux errno 22, Windows 10051 /
  10049 / 10065). No route is a plain sentence. A Decode before the first
  Status stays off the roster (historical Band Activity). Expected send
  failures no longer print `FAIL`. The ingest stale check no longer
  subtracts 40s from a monotonic clock that can still be younger than that
  (a fresh CI runner treated the stamp as "never heard").
- **2026-10-17** — **Goal menu on Setup.** Contest / Award / Just operating /
  Custom, with a second menu. DXCC, Worked All States, and VUCC use the log as
  the already-have list. Just operating defaults to WSJT-X Colors; a checklist
  covers DXCC, grid, state or province, and call (overall, per band, or per
  mode). County and callsign prefix stay off — no list is shipped. Saved
  schema 3 contest choices migrate. Design: [wims_logs_and_rules.md](wims_logs_and_rules.md) §3.8.
- **2026-10-17** — **Setup Advanced tooltips.** Every control under Setup →
  Advanced has a short plain-language tip: a native hover title and a
  keyboard-focusable ?. Covers contest rules, how often a station counts,
  county reset, mode groups, modes that do not count, points, multipliers,
  log path, Check logs, and WSJT-X Colors when Just operating uses them.
- **2026-10-16** — **Zero-knowledge start and launcher path.** Desktop and Start
  menu icon named WIMS (`scripts/Add WIMS to Desktop.bat`,
  `scripts/add-wims-to-desktop.sh`). Second double-click reopens the console.
  A busy port says what to do next. Checkout shim so a start from the repo
  needs no path variable. Principle: [design-principles.md](../design-principles.md).
- **2026-10-15** — **Solo logs and contest rules (L1–L6, L7–L9 partial).**
  ADIF reader, per-instance `wsjtx_log.adi` discovery, `WsjtxAdifLogSource` when
  N1MM is not the log, JSON rules for NY QSO Party and ARRL VHF, WSJT-X Colors
  fallback, Setup Contest dropdown, `python -m wims.logaudit`. NYQP multipliers
  stay unmarked. JTTY / free-text roster risk left as-is. GridTracker roster
  filters and a UNC stat timeout are still open.
- **2026-10-15** — **Design only: solo logs, contest rules, log audit.** Proposal in
  [wims_logs_and_rules.md](wims_logs_and_rules.md). Milestones L1–L9. No runtime
  change. Contest rules are one original GPL-3.0 JSON file per contest (NY QSO
  Party first). Casual Setup is a single Contest dropdown; Advanced hides the
  editor and the `.udc` importer. Dropdown None uses WSJT-X Colors. N1MM stays
  authoritative when it is the log.
- **2026-10-14** — **IF→RF mapping is off unless the seat is listed.**
  `if_seats.json` (Setup checkbox, or the seat agent page on that PC) names
  rig-names / N1MM stations that report IF (Roy 222 at 21 MHz, Roy 432 at
  28 MHz). A Flex 10 m dial at 28.074 MHz stays 10m. `WIMS_TRANSVERTER` is
  only an override. WSJT-X Status and N1MM RadioInfo / ADIF both honor the
  list. Decision: [2026-10-14](../decisions/2026-10-14-if-reporting-seats.md).
- **2026-09-13** — **Version `1.0.16`**. Operate Halt stays live after Work
  in RX (claim 45s, refresh while TX). UDP Work/Halt dests are IPv4-only
  (mapped `::ffff:` / `%zone` coerced; no multicast fallback) so Windows
  errno 22 does not surface as `Work failed`.
- **2026-09-13** — **Version `1.0.15`**. N1MM Log OPERATOR is the rig-name
  (strip `WSJT-X - `). ADIF `BAND` 10m/15m maps to 70cm/1.25m IF. Launcher
  is the only N1MM-agent window (`--no-gui`; Broadcast/Log/KEY rows in the
  launcher). UDP ingest stall watchdog + dashboard stall badge. CI
  `adif_band` IF tests pass.
- **2026-09-13** — **Version `1.0.14`**. N1MM TCP Log Call: measured on
  live `:52001`/`ham.s3db` — N1MM skips the first byte after
  `<parameters:N>`. Prefix ADIF with a space *inside* N. Live test
  `W5WIMS` stored Call; without space Call was blank.
- **2026-09-13** — **Version `1.0.13`**. N1MM JTDX TCP Log wants lowercase
  `<call:` (JTDX/WSJT style). 1.0.12’s `<CALL:` left Call blank; wire
  format is now `<call:5>… <eor>` with no EOH/extra tags.
- **2026-09-13** — **Version `1.0.12`**. N1MM TCP Log rebuilds CALL-first
  ADIF (WSJT `<eoh>`/`<call:6>K1ABC ` left Call blank). Operate Work
  unicasts to MessageClient only (no multicast sendto / WinError 22).
  KEY COM retries after launcher sample; read-only open + share. Shared-trx
  STE design is the feature doc.
- **2026-09-13** — **Version `1.0.11`**. Install no longer rewrites tracked
  `Start-WimsServer.cmd` (that dirty file blocked `git pull` / Update). Pin
  stays in gitignored `python-path.txt`; launchers already call `_resolve-python.cmd`.
- **2026-09-13** — **N1MM page Bands** is this station’s radio + WSJT, not
  every networked QSO band (6m logger no longer shows 2m/70cm). Inactive
  SO2R RadioInfo is ignored. Dashboard meter labels are **6M / 2M**.
- **2026-09-13** — **Operate Halt TX is this-console only.** Work records a
  dashboard id; Halt stops live claims from that browser (two bands → both),
  not other operators and not a global stop-all. Button label lists the bands.
  Tests in `test_server_tx`.
- **2026-09-12** — **Version `1.0.10`**. Seat **Update WIMS** relaunch now drops
  `launcher.lock` before spawn (`pythonw` was exiting with no window). Status
  refresh no longer restores "Update available" over "Updating…". N1MM
  Broadcast POST is queued so RadioInfo cannot stall contactinfo (6m logger
  vanishing). Roster folds no-grid 73/RR73 into the existing row; dupe and
  sign-off are not "calling us". Presence prefers `192.168.10.0/24` on
  dual-homed loggers. Inactive-radio RadioInfo is not forwarded.
- **2026-09-12** — **Version `1.0.9`**. Launcher start/idle no longer blocks the
  UI on repeated ``tasklist`` / PowerShell / WMIC (and git fetch). Process
  lists are cached; detect + site probe run off the UI thread; git children
  use CREATE_NO_WINDOW.
- **2026-09-12** — **Version `1.0.8`**. False **⚠ shared id** when the site
  server sent Replay/Reply to `224.0.0.73:2237` (instance id in the payload,
  source = server IP). Ingest treated that as a second WSJT-X host. Control
  now unicasts only to MessageClient; inbound Replay/Halt/Reply are not
  presence. Windows Install skips LibreOffice / Store-stub Python and pins a
  real `python.exe` via `python-path.txt`.
- **2026-09-12** — Windows Install no longer treats **LibreOffice**'s bundled
  Python as the WIMS runtime. LibreOffice's `python.exe` reports
  `sys.executable` as `python-core-3.x.y` (a **directory**), which then failed
  the smoke test (`The term '...\python-core-3.12.12' is not recognized`).
  Finder requires a real `python.exe` with Tk, skips vendor embeds, and does
  not recurse all of Program Files. Pin stays in gitignored `python-path.txt`;
  `Start-WimsServer.cmd` uses `_resolve-python.cmd` like the other launchers.
- **2026-09-11** — **Version `1.0.7`**. Compact scrollable launcher (Other tools…
  no longer grows the window). Overview RadioInfo is **10 Hz units** (6m/2m were
  showing as 70cm/23cm). Git clones already on `main` no longer nag from a newer
  Release tag.
- **2026-09-11** — **Version `1.0.6`**. Operate band without decodes: Status UDP
  dial (not a remote `.ini`). Quiet radios: unicast Replay to elicit Status.
  Checkboxes from live instances; heartbeat-only falls back to UDP id.
- **2026-09-11** — **Version `1.0.5`**. WSJT-X start uses `C:\WSJT\wsjtx` if present,
  else `wsjtx-inhibit`. Operate band checks follow live WSJT-X (Heartbeat/Status),
  not roster decodes (`roster.live_bands`). Hide Update WIMS when already current.
- **2026-09-11** — **Version `1.0.4`**. Hide leftover `python.exe` consoles after
  Update (1.0.1 left the old site server window up). New children also
  `FreeConsole` when stdout is piped; relaunch uses the hidden VBS starter.
  Logon boot (`Start-WimsAtLogon`) uses `pythonw`.
- **2026-09-11** — WSJT-X start path: use `C:\WSJT\wsjtx\bin\wsjtx.exe` when present,
  else `C:\WSJT\wsjtx-inhibit\bin\wsjtx.exe` (`_resolve-wsjtx.cmd` + `find_wsjtx_exe`).
- **2026-09-11** — **Version `1.0.3`**. Optional logon **Grok CLI**
  (`Start-GrokAtLogon` / `Install-GrokLogonStartup`) with `--always-approve`.
- **2026-09-11** — Overview band list: N1MM `<RadioInfo>` Freq is **10 Hz units**
  (same as the log agent). The site server had been treating it as 100 Hz, so a
  6m logger showed as **70cm** and a 2m logger as **23cm**.
- **2026-09-11** — Launcher home is **compact** (two-column Running list, one-line
  header) and **scrollable**: Other tools… / role cards stay inside the window
  (mouse wheel + scrollbar) instead of stretching toward fullscreen. Default size
  shows Open site console / Start / Restart; Details lives under Other tools….
- **2026-09-11** — **Version `1.0.2`**. Logon boot from saved **seat intent**: `Start-WimsAtLogon.cmd`
  / `Install-WimsLogonStartup.cmd`. This PC’s intent (WSJT on, N1MM/server off)
  starts WSJT-X (`--rig-name` from named configs) + the WIMS launcher.
- **2026-09-11** — **Version `1.0.1`**. Desktop **WIMS** does not open a `python.exe` console:
  launcher uses `pythonw`; child site server / agents use `CREATE_NO_WINDOW`.
- **2026-09-11** — Startup checks **GitHub Releases** (launcher, site server,
  N1MM agent, WSJT agent) in addition to `git fetch`. ZIP / no-git PCs see
  **Update available** after a tagged Release. Push to `main` does not publish;
  `tools/dev/cut-release.sh` / `git push origin vX.Y.Z` does.
- **2026-09-11** — N1MM agent Log connects **TCP 127.0.0.1:52001** at start and
  reconnects while waiting (Configurer JTDX/Others TCP). BROADCAST row shows the
  real site-POST error (ERR N was a count, not a WinError); RadioInfo failures
  are rate-limited; presence can refresh a bad `WIMS_SERVER`.
- **2026-09-11** — Console “kiosk” is **Operate** in a compact resizable window
  (Chrome `--app=` style). Firefox dedicated profile + `-width`/`-height`; no
  `--kiosk` (fullscreen-locked).
- **2026-09-11** — Windows install treats **Git** as a prereq whenever the tree is a
  git checkout (not only when cloning): launcher “Update available” is `git fetch
  origin/main`, so a USB-copied clone still needs `git` on PATH. Release ZIP trees
  (no `.git`) still skip Git.
- **2026-09-07** — **Version `1.0.0`** + GitHub Release [`v1.0.0`](https://github.com/wa1hco/WIMS/releases/tag/v1.0.0).
  Install/release scaffolding (aligned to [wims_release_packages.md](wims_release_packages.md)):
  root `install.sh` / `install.ps1`, `scripts/install-linux.sh`,
  `tools/dev/packaging/write_manifest.py`, allow-list `package-release.sh`,
  `release.yml` + `tester-packages.yml`, `INSTALL.md`. Windows bundled CPython+Tk still open (PR 0/5).
- **2026-09-07** — **GitHub release + install scaffolding** landed earlier the same day
  (superseded by `v1.0.0` publish).
- **2026-08-29** — Tired-operator launcher: default **N1MM seat** home (one Start /
  Stop / Open site console + green-yellow-red banner). Role catalog under
  “Other PC types…”. Docs: [tired-operator-ux](../decisions/2026-08-29-tired-operator-ux.md),
  [contest-pc-roles](../decisions/2026-08-29-contest-pc-roles.md),
  [remote-n1mm-logging](../decisions/2026-08-22-remote-n1mm-logging.md). Seat monitor
  binds :8790 before discovery; Windows waits for LISTENING before browser.
  **False “Running” fix:** log agent always gets `--band` / `WIMS_BAND` (band picker
  required); KEY is advanced one-shot selftest (not a resident agent — no Task Manager
  stay); launcher clears Running on exit and banners log helper stop.
  Launcher Details: selectable + **Copy details** / **Open log file**
  (`scratch/launcher-details.log`) so Windows ops can paste errors without fighting
  a disabled text widget. Log agent startup prints are ASCII-only (Windows cp1252
  crashed on `→`); launcher sets `PYTHONUTF8` for child processes.
  **Log helper Tk status + scoped checks:** `python -m wims.log` / Start seat opens a
  compact window (Status / Interconnect / Config check). Shared `wims.helper_ui`;
  checks in `wims.log.check`. Windows hides the extra black console for the log child.
  **Live N1MM band:** filter follows RadioInfo on `127.0.0.1:12060` (wait/drop until
  heard; adapts on band change). Decision: `2026-08-29-n1mm-live-band.md`.
  **Minimize questions:** home screen drops band picker + site URL field; site from
  `WIMS_SERVER` / last-known / LAN discover (Advanced override only).
  **Compact log helper UI:** green/yellow/red banner + fix line + few facts;
  Details/Copy optional (`wims.helper_ui`).
  **Checkbox agent console (2026-08-30):** no fixed seat role. Detect N1MM/WSJT-X,
  check boxes, start Log / Seat / Key / Site server agents. Always say “agent”
  (not helper). Key agent: `wims.key daemon` stub (CTS + targets). Shared Tk
  chrome: `wims.agent_ui` (compat shim `wims.helper_ui`).
  **Safe seat replace on start:** `launcher/process_replace.py` stops orphan
  Log/Seat/Key by cmdline; never auto-kills site server / WSJT-X / N1MM.
  **Linux desktop icon:** `scripts/assets/wims.png` (white abstract W + “wims”
  on blue). Freedesktop does not render the Windows `.ico` reliably (looked
  transparent); launcher shortcut prefers PNG on Linux.
  **Site server adopt (no focus-steal):** if `:8787` already up, launcher marks
  Site server “up (existing)” and does not spawn/reopen browser in a loop
  (dual-primary exit used to restart + steal focus every few seconds).
  **Checkboxes = live status (not prefs):** no `agent_boxes` restore; app up →
  box on + agent up; app down → box off + agent stop.
  **Windows update (2026-08-31):** `Update-Wims.cmd` + launcher **Update WIMS**
  button when behind `origin/main` (`update_check.py`); Install-Wims also places
  Desktop **WIMS** + **Update WIMS** shortcuts.
  **Seat intent vs Running (2026-09-01):**
  **Ingest self-heal (2026-09-02):** ingest loop heartbeat + watchdog restarts
  dead/stuck ingest in-process (not keyed on rx — quiet VHF/UHF is normal);
  per-datagram errors no longer kill the ingest thread.
 launcher splits observational
  “Running on this PC” from remembered “This seat will run” (N1MM / WSJT-X /
  SSB-CW KEY / Site server → Log / Seat / Key / server agents).

- **2026-08-28** — Desktop GUI launcher (`python -m wims` / `wims.launcher`): role cards
  (Solo ★, Check, Site server, Seat agent, KEY lab) with tooltips, Solo band-port radios,
  Open Operate/Status/Setup, Put-on-Desktop shortcut helper. Windows Desktop **WIMS** icon
  now points at `Start-WimsLauncher.cmd` (`assets\wims.ico`); Linux
  `scripts/add-wims-to-desktop.sh`. Top-level CLI roles (`solo`/`server`/`agent`/`key`/
  `version`); `wims.solo --port`; thin `wims.key` wrapping inhibit bench selftest.
  Tests: `test_cli_launcher.py`. Docs: tester_roles + how-to-run.
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
- **2026-07-16** — Networking layout refined: **50 MHz** may include **remote WSJT-X** (e.g. TV
  station PC) with **common N1MM-50**; **144** may use **separate PC+radio** for FT8 and MSK but
  **one N1MM-144**; **222/432** single PC each, **SSB and/or FT8**. Docs: wims_networking §1–2/§8,
  wims_design deployment context.
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
- **2026-07-16** — Networking layout refined: **50 MHz** may include **remote WSJT-X** (e.g. TV
  station PC) with **common N1MM-50**; **144** may use **separate PC+radio** for FT8 and MSK but
  **one N1MM-144**; **222/432** single PC each, **SSB and/or FT8**. Docs: wims_networking §1–2/§8,
  wims_design deployment context. M4 rotator checklist: live az, set-az, point-to-DX az.
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
  roster **click-to-work** (Reply), always-on **Halt**, `TxArbiter` grant/release. Originally
  shipped with a global arm switch (later removed — GT2 workflow, 2026-07-22).
  *Found (pre-existing, not R0):* on **loopback**, the plane-E presence announce on the shared
  `224.0.0.73` group starves the WSJT-X multicast ingest (0 pkts) — `validate.sh` live check now runs
  `--no-presence` (single-host); `wims.solo` already defaults `--no-presence`, so solo is unaffected.
- **2026-07-22** — **Remove global TX arm (GT2 workflow).** No Enable/Disable TX on Operate;
  human initiation = **click roster line** (or Work) → `/api/tx/work`. Dropped `arm` API/state
  field; `can_tx` follows controller wired. Halt remains. Design §2.12 + runbook + `test_server_tx`
  updated.
- **2026-07-23** — **Roster Phase‑1 polish.** Drop Work button column + UTC (line click only; Age
  kept). Columns: **Az DX**, **km** (`distance_km`). Highlights: **calling-us** (red — `to_call`
  matches instance `de_call`) and **armed** (green edge — Status `tx_enabled` + `dx_call` match
  row). Contract: `is_calling_us`, `is_armed`, `distance_km`. Status tracks `de_call` / `dx_call` /
  `tx_enabled`. Rotator Δaz / point-on-Work / beam scoring still M4 (later).
- **2026-07-23** — **Rotator Phase‑2 start (M4).** Registry + sim + Yaesu helpers; roster **Az ant**
  / **Δaz** / moving font; click **Az DX** → point; Stop on rotator table; agent report can carry
  `rotators[]`. Lab: `--sim-rotator ROT-6M:45:WSJT-X`. No live K3NG serial yet.
- **2026-07-26** — **Port map: skip 2240; 432→2241, 902→2242, 1296→2243.** Fleet default
  `FLEET_WSJT_PORTS=2237,2238,2239,2241,2242,2243`. Docs §4.3 / §4.9 updated. Avoids common
  N1MM bind of unlabeled **:2240**.
- **2026-07-26** — **Doc: UDP :2240 / unlabeled N1MM binds.** Lab: `N1MMLogger.net` can own
  **:2240** (and :2237) while Configurer SO2R shows no “2240”. Design + diagnosis:
  **[wims_networking.md §4.9](wims_networking.md)**.
- **2026-07-23** — **Multi-band WSJT-X ports:** server joins band ports by default (no CLI
  memory). Solo still 2237-only. Escape hatch `--ports`. *(Map revised 2026-07-26 — see above.)*

- **2026-07-23** — **Station agent desktop launcher:** `Install-WimsAgent-Desktop-Shortcut.cmd`
  + green `assets/wims-agent.ico`; install also creates **WIMS Agent** + **WIMS Server**
  shortcuts. Continuous agent opens local UI `http://127.0.0.1:8790/`.
- **2026-07-27** — **Tester quick start:** `docs/tester_quickstart.md` — layered tracks A–D
  (no radio apps → WSJT only → N1MM+WSJT → optional multi-PC). Linked from README + runbook.
- **2026-07-20** — **Agent solo mode (noob-friendly setup check).** `wims.agent --solo` + new
  single-PC validation lens (`wsjtx_config._validate_solo`): the fleet "blank/@Invalid outgoing
  interface" **ERROR becomes a friendly note** (traffic staying on one PC is correct), and the
  site-server discovery is skipped. New `format_report_solo` prints a plain-language verdict
  (`[OK]/[! ]/[XX]`, ASCII for Windows consoles) with the exact WSJT-X/N1MM click-path per item;
  header count matches the body. Runs automatically at `wims.solo` startup (before the server) and
  standalone via `scripts\windows\Check-WimsSetup.cmd`. Windows README gained a "Solo tester" section.
  Tests: `test_agent_solo` (7). Fleet/lab agent output unchanged.
- **2026-07-28** — **Remember last N1MM contest log across restarts.** Setup pick and
  `--seed-db` write host pref (`state/last_log.py` → `~/.config/wims/last_log.json` /
  `%APPDATA%\wims`, override `WIMS_LAST_LOG`). Startup: explicit DB → remembered → auto
  latest dated contest. Fixes home casual `DX` / wa1hco.s3db losing to N2OY June every
  restart. Tests: `test_last_log`.
- **2026-07-31** — **TX-inhibit spike verified live + adaptive hang built** (tx_inhibit §3/§11.6.1).
  Spike verified: 15 unit tests, loopback selftest (median 0.24 ms transition), and a two-process
  gate↔agent UDP run (SSB burst + CW string = exactly one INHIBITED→OPEN cycle). Bench facts on a
  real dongle (Digirig, CP2102N): Linux `cp210x` returns `ENOTTY` for `TIOCMIWAIT` → spike's CTS
  watcher gained a 1 ms `TIOCMGET` poll fallback (FTDI Keyline unaffected); Digirig exposes no CTS
  pin at all → §4.1 same-port KEY convention inapplicable on Digirig seats (doc updated). **Adaptive
  hang classifier** (`adaptive_hang_s` + `KeyAgentScheduler` default): latest closure picks the mode
  (≥0.75 s → flat 0.5 s; else CW → 8×dit-estimate clamped 0.2–1.0 s, dit = min recent short closure,
  20 ms debounce); numeric `hang_s` = manual override, classifier off; `last_hang_s`/`hang_mode`
  exposed for telemetry. Tests: `test_inhibit` now 23 (WPM tracking 15/20/30, 7-dit word-gap hold,
  clamps, CW↔SSB flip, bounce immunity, override). wsjtx-3.1.0 improved_PLUS builds clean on this
  laptop (superbuild → `build/wsjtx-prefix/src/wsjtx-build/wsjtx`) — ready for Stage 2 (§11.6.2).
  Known pre-existing failure: `test_agent_report` (N1MM probe monkeypatch), unrelated.
- **2026-08-02** — **Inhibit wire protocol collapsed to one message type** (per WA1HCO): every
  datagram means *"inhibit this band for `ttl_ms`"*; **release = `ttl_ms: 0`** — no `state`
  field, no clear code path in the gate (tx_inhibit §11.3). Gate counters now
  `hold_rx`/`release_rx`/`expiries`/`invalid` (releases never enter the deadline table, so
  expiries stay pure keepalive-loss alarms). Protocol magic renamed `wims_inhibit` →
  `tx_inhibit` (patch carries no WIMS reference, §11.7.4); class `TxInhibitGate` → `PttGate`.
  Code+tests+spike updated, 23/23 green; §11.7 netcat two-liner demoed live against the gate.
  Doc-side same day: radio-inhibit prior-art survey (K2TR's Elecraft mid-key **latch**
  measurement; Flex TX REQ initiation-only; Kenwood TS-890 has no external inhibit line) +
  the arbitration-model statement (radios: two humans, first-PTT-wins; WIMS: one human vs
  N machines, human always wins — why level semantics + puncture had to be built new).
  Same day, second simplification (per WA1HCO): **gate tracks ONE hold** — per-station
  deadline table removed; last hold wins, any valid release opens; multi-station
  arbitration declared out of scope for WSJT-X (SSB/CW side ORs KEY lines in hardware,
  tx_inhibit §4.3). `holding_stations()` → `holding_station()`; InhibitStatus `stations`
  list → `station`. 23/23 green after both changes.
- **2026-08-02** — **Stage 2 begun: `PttGate` lands in the fork** (wsjtx-improved-wims
  `feature/tx-inhibit` @ 9990730). `Transceiver/PttGate.{hpp,cpp}` — C++/Qt5 port of the
  proven `InhibitGate` semantics (single hold, ttl-only protocol, PreciseTimer deadman,
  hold/release/expiry/invalid counters, `hold_test` bench slot, `line = intent ∧ ¬inhibit`
  on RTS/DTR via QSerialPort, immediate unconditional ptt ack). House style: trailing-`_`
  members, CRLF, no reformat (CMake diff = 2 lines: source list + `Qt5::SerialPort` on
  `wsjt_qt`). Full `wsjtx` binary builds clean from the repo tree (fresh build dir against
  the superbuild's hamlib; tree is **Qt5**, noted). Not yet wired: gate thread setup,
  DTR/RTS PTT reroute (the one existing-code touch), badge, InhibitStatus type 18.
- **2026-08-03** — **Mainline fork published with gate wired:**
  [wa1hco/wsjtx-wims](https://github.com/wa1hco/wsjtx-wims). Local `~/ham/wsjtx-wims`.
  Push order: (1) baseline tag `baseline-v3.0.2` = official `WSJTX/wsjtx` v3.0.2;
  (2) `TxInhibit/` gate + Configuration DTR/RTS reroute + status badge +
  `NetworkMessage::InhibitStatus` (type 17) + docs (superbuild / build / inhibit).
  Protocol matches Python spike (`tx_inhibit`, ttl-only). Official CI
  (`.github/workflows/build-{linux,windows,macos}.yml` + `release.yml`) kept for
  downloadable test binaries via `build/v*` tags. WIMS design link updated.
- **2026-07-31** — **WSJT-X Improved → own GitHub project** for Stage 2 tracking:
  [wa1hco/wsjtx-improved-wims](https://github.com/wa1hco/wsjtx-improved-wims). Baseline import of
  extracted Improved 3.1.0 (`improved_AL_PLUS_260522`) as tag
  `base-3.1.0-improved-AL-PLUS-260522`; branch `feature/tx-inhibit` reserved for the
  `PttGate` patch (class renamed from `TxInhibitGate` 2026-07-31 — "gate" already implies
  the inhibit). 2026-08-02: hang purpose sharpened (per WA1HCO) — hang exists *only* to
  keep the WSJT-X radio's PTT from following break-in dits/dahs; long-closure
  (SSB-PTT/VOX/semi-BK) hang cut **0.5 s → 20 ms debounce** (`LONG_HANG_S`), hardware
  safety under arbitrary keying being a station requirement, not the agent's job. CW
  8×dit rule unchanged. Tests updated, 23/23 green. Superbuild drop remains local under
  `~/ham/wsjtx-3.1.0_improved_AL_PLUS_260522/` (not in the WIMS tree). Design cross-link added in
  [wims_tx_inhibit.md](wims_tx_inhibit.md).
- **2026-08-11** — **Release-track Phase 0:** fix seat-agent N1MM probe so UserDir\\Databases
  is found via `n1mm_user_dirs()` (test was patching agent helpers while `database_dirs()`
  only consulted logdb’s host scan — failed on Linux CI/dev). `test_agent_report` green
  again. Add `.github/workflows/ci.yml` (push/PR → `tools/dev/validate.sh` on Python
  3.10/3.12/3.14 + version pin check). Releases later landed as `v1.0.0` (2026-09-07).
- **2026-08-11** — **Tester roles doc:** [tester_roles.md](../tester_roles.md) freezes the
  install surface (solo / site server / console / seat agent; KEY agent lab-only). Fixed
  stale “Arm TX” and 432→2240 port in quickstart/Windows README; linked from README.
- **2026-08-12** — **Design §2.13** (fleet inventory, dynamic membership, browser sessions,
  multi-KEY, multi-N1MM answer, inhibit+Halt roles) folded from operator scenarios; networking
  logger invariant clarified. Code not yet; todos listed under design backlog.
- **2026-08-12** — **Design §2.14** band-sharing policy: **`interlock`** (original real-time
  inhibit, SSB/CW priority) vs **`coordinated`** (manual handoff; WIMS informs both sides, no
  automatic inhibit). Goals + §3.4.1 + tx_inhibit §1 cross-linked.
- **2026-08-12** — **Slice 1 (inventory + policy) code:** `state.fleet_to_dict` → `bands[]` +
  per-instance `share_policy` / `inhibit` placeholder; LiveFleet `set_share_policy`;
  `POST /api/band/policy`; `--interlock-band`; Status Band inventory table + policy pills.
  Tests in `test_server_state`. KEY/SSB rows and inhibit actuation still later.
- **2026-08-14** — **Split inhibit generator designs:** **inhibit-test** + **inhibit-agent**
  (wsjtx-inhibit; design [inhibit_agent.md](inhibit_agent.md) — no WIMS mentions, exportable)
  vs **WIMS Key agent** ([wims_key_agent.md](wims_key_agent.md)). Not coded yet.
- **2026-08-16** — **Agents do not debounce PTT** (per WA1HCO): inhibit-agent and WIMS Key
  agent assume **manual switches that already debounce**. Long/SSB hang **20 ms → 0**
  (`LONG_HANG_S`); hang remains **CW-only** (8×dit). Aligns with shipped inhibit-test
  (continuous KEY hang = 0). Spec + `test_inhibit` updated.
- **2026-08-16** — **inhibit-agent coded** in sister repo `wsjtx-inhibit`
  (`tools/inhibit-agent/`): CLI (`--port` + `--addr host:port`) for scripts; GUI
  (no args; auto Keyline + `127.0.0.1:22372`) for operators; Linux and Windows.
  Hang matches inhibit-test. Design copy: [inhibit_agent.md](inhibit_agent.md).
- **2026-09-02** — **Inhibit wire transfer into WIMS (docs only):** sister
  `wsjtx-inhibit` now ships **type-18** `NetworkMessage::TxInhibit` +
  **per-Controller ID leases** (JSON hold obsolete). New implementation brief
  [`docs/protocols/wsjtx_tx_inhibit.md`](../protocols/wsjtx_tx_inhibit.md);
  banners on [wims_tx_inhibit.md](wims_tx_inhibit.md) §11.3,
  [wims_key_agent.md](wims_key_agent.md), [inhibit_agent.md](inhibit_agent.md).
  **Code still JSON** (`src/wims/interlock/inhibit.py`, spike, `wims.key`) —
  next: encode/parse + lease gate + Key agent Controller ID.
- **2026-09-02** — **WIMS lab inhibit speaks type 18:** `interlock/inhibit.py`
  encode/parse = `NetworkMessage::TxInhibit` (schema 3); `InhibitGate` =
  per-`controller_id` leases OR'd (release clears one row only); JSON rejected
  as invalid. `KeyAgentScheduler` requires `controller_id`; hang aligned to
  TX_INHIBIT.md (**10.5 × dit**, clamp 0.315–1.260 s). Spike `--controller-id`;
  `test_inhibit` 30/30 + inhibit bench selftest green. Still out: Key
  daemon product fan-out, InhibitStatus type-17 target discovery.
- **2026-09-02** — **Rename lab harness:** `testbed/inhibit_spike.py` →
  `testbed/inhibit_bench.py` (talk about the **inhibit bench**, same family as
  `interlock_bench.py` / sister-repo inhibit-test). `python -m wims.key`
  {selftest,gate,agent} loads the bench; historical build-log “spike” means this.
- **2026-09-03** — **N1MM/SSB-CW seat agent:** `python -m wims.seat --log/--key`
  shares RadioInfo live band; Key runtime = same-band policy, Status+InhibitStatus
  discovery, CTS→type-18. Launcher N1MM + SSB/CW intents start one `n1mm_seat`
  process. Parse type 17 in `udp.messages`. Tests: `test_key_discovery`, messages.
- **2026-09-03** — **RadioInfo goes multicast:** log/seat agents now join
  `224.0.0.73:12060` for N1MM RadioInfo (bind `0.0.0.0`, unicast still heard;
  `--radio-group` to override) — fixes Windows seat never hearing fleet N1MM
  (old listener bound `127.0.0.1` only). Seat/log singleton checks corrected:
  `wims.seat` counts as `n1mm_seat` (WSJT monitor no longer blocks the seat;
  a second forwarder is refused). Tests: `test_log_check` (radio socket + check
  text), `test_cli_launcher` (role catalog).
- **2026-09-05** — **N1MM agent Broadcast relay + docs refresh:** fleet Broadcast
  Data → `127.0.0.1:12060`; agent POSTs `/api/n1mm/broadcast`; console nav
  Operate/Overview/WSJT-X/N1MM/Setup. Operator how-to:
  [`docs/operator_setup.md`](../operator_setup.md).
- **2026-09-05** — **Plane A single port 2237:** operator docs and server default
  `--ports` are **2237 only** (no 2238–2243 in bring-up). Decision:
  [`../decisions/2026-09-05-plane-a-single-port-2237.md`](../decisions/2026-09-05-plane-a-single-port-2237.md).
- **2026-09-05** — **Doc consistency pass:** `wims_networking.md` / design summary /
  status “How to run” rewritten so operator checklists match **2237 + N1MM agent**
  (built-in digi reader OFF). Historical Scheme A multi-port kept only as labeled
  archaeology.
