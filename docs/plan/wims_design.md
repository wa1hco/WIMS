# WIMS — WSJT-X Instance Management System: Requirements & Design

*Working name: **WIMS** (WSJT-X Instance Management System).*

This is the **requirements / goals / design** source of truth for WIMS — a supervised,
human-in-the-loop console for multi-instance VHF contesting, plus the integration plumbing
around N1MM+, GridTracker, and Green Heron. It describes *what* WIMS must do and *why*, and
records design decisions as they're made.

**Build status, milestones, the module-implementation table, and the build log live in the
companion tracker [wims_status.md](wims_status.md).** Keep the two separated: change this file
when the *design* changes; record *progress* there.

---

## WIMS goals

WSJTX Instance Management System (WIMS) is a tool to manage multiple instances of WSJT-X either
on the same band or on several bands. A station may have several antennas with receivers and
WSJT-X running to look in different directions. A station may have WSJT-X monitoring for FT8,
EME, or meteor scatter simultaneously. A station may have several bands receiving simultaneously.

WSJT-X sends each decoded message to WIMS which displays them in a call roster along with
information about the source. In a manner similar to GridTracker's call roster, the operator can
click on a message to cause the receiving station to start a contact with the DX station.

On each completed contact WSJT-X sends a message to N1MM to log the contact information.

WIMS sorts the reported DX according to user preferences. The idea is to display only stations
relevant to the goals of the contest and in the order that is most likely to increase score by
the most.

WIMS has access to the N1MM log to create its own internal copy of the log and also receives
messages from N1MM when the log is updated.

WIMS has support for setup where it verifies connection to all the WSJT-X and N1MM instances,
guides the user in the setup, and reports loss of communication. WIMS has features to automate
the setup.

WIMS supports one or more SSB/CW stations that have priority over WSJT-X operation. When the
SSB/CW operator wants to transmit, WIMS halts (within 10 ms) any WSJT-X operation that would
violate the contest rules. WSJT-X may not stop the transmission within the time budget, so WIMS
has an additional ability to reduce the transmit level to zero so that audio buffering is not an
issue.

The SSB/CW operator has a small program that shows the activity of WIMS on the relevant band, to
give the SSB/CW operator the option to wait for the current contact to complete.

In general WIMS runs on a separate computer from the WSJT-X and SSB/CW computers.

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
                           N1MM+ (log, ◀┘          └▶ Green Heron (rotator)
                           dupe/needed)
                               ▲
                 GridTracker ──┘  (grid forwarding, log export, packet relay/viz)
```

Key constraints carried over from the notes: **zero overlap on transmitters** (*per
shared-resource group* — see below), **WSJT-X transmissions cannot be interleaved**, and WIMS —
not WSJT-X — decides which station to work, run vs S&P, and when to give up.

### Deployment context (current operation)

A **fixed, unlimited multi-multi** entry in the **ARRL June & September VHF** contests —
stationary, **one grid, no roving on our side**. Three vehicles: **"Roy"** (truck) 222 + 432;
**"Chip"** (truck) 903 + 1296 + up (microwave); **"Trailer"** 50 + 144. Each vehicle = a host
running WSJT-X instance(s) for its digital bands plus operators on SSB/CW. Today the vehicles
have a network between them **but no shared visibility — coordination is by chat only.** WIMS's
headline value is the **cross-vehicle operations console**: one combined call roster, per-vehicle
band-activity + health, one merged log / dupe-mult view — replacing "anyone there?" over chat.

- *Mapping:* **vehicle = host**, **band = instance**; each mixed SSB/CW + digital.
- *Network:* single **`192.168.10.0/24`, wired L2 switches** → one broadcast domain, so **WSJT-X
  multicast works across all vehicles natively** (the "everyone joins the group" model holds
  end-to-end). Per-vehicle unicast relay (host agent) is a **fallback**, not required. *Watch:*
  managed switches with **IGMP snooping** + no querier can prune multicast — verify on
  plain/unmanaged L2 it floods fine. Internet is **1–2 Starlinks**, separate Starlink WiFi for
  other devices — **out of the WIMS data path** (WIMS is LAN-only; Starlink CGNAT/latency never
  involved).
- *Rover dupe still applies:* our position is one fixed grid, but we **work rovers** (others'
  stations moving between grids); each grid×band is a mult, so the `(call, band, grid)` dupe key
  (grid from the WSJT-X decode) stays necessary for worked stations.
- *Arbiter scope:* multi-multi = multiple simultaneous transmitters by design; zero-overlap is
  enforced **per resource group** (transmitter/antenna/PA chain, §3.14) — Roy-432, Chip-1296,
  Trailer-6m all TX concurrently; contention is only *within* a shared radio/antenna (§3.4).
- **Operating model — NO automated operation.** Every active transmitter always has a human
  operator: either the **local op in the seat**, or the **WIMS console operator** who **smoothly
  takes over** a band when its seat is empty (e.g. 222/432 in Roy when nobody's there). WIMS is a
  **remote operating position + force-multiplier** — one console op covers several empty-seat
  bands via the call roster + click-to-work. WIMS **ranks/recommends; the human initiates every
  TX**. The key UX is **clean handoff** (local ⇄ WIMS op, request/grant/release) with always
  exactly one operator per instance (ties to §3.13, §2.3, scenario S7).

---

## 1. External-component behavior (what we must verify before trusting it)

Goal: characterize each building block (and lock in the known quirks as regression checks)
*before* trusting it inside WIMS. Behavior that can be exercised without RF belongs in the test
bed (§5).

### 1.1 WSJT-X UDP protocol
- **Outbound messages** — Heartbeat, Status, Decode, QSO Logged, ADIF, per `NetworkMessage.hpp`
  (schema 2/3, big-endian QDataStream; ref `Documents/wsjtx-3.0.1/Network/NetworkMessage.hpp`).
  WIMS must **extract grid** from `CQ CALL GRID` / Tx1 decode text.
- **Inbound control** — confirm each command WIMS sends actually acts: Reply, Halt Tx, Free Text,
  Replay, Configure. *(Confirm exact message names/IDs against the WSJT-X UDP protocol header.)*
- **Trigger CQ via UDP** — open question: can a UDP message start a CQ, or only reply to a
  decode? Determine the supported mechanism.
- **Mid-cycle Halt Tx — timing** — Halt Tx (UDP msg ID 8, `auto only`=false) stops WSJT-X feeding
  the audio buffer, but RF persists until the buffer drains. Expected ~50–200 ms, dominated by OS
  audio-buffer drain + PTT release — *not* the LAN. This is the slow path; treat UDP Halt Tx as
  cleanup, not the 10 ms inhibit (§3.4 fast mute). **Measure** the real delta (timestamp the UDP
  send; capture the RF envelope on an SDR/scope).
- **Fast TX inhibit — mute latency** — for the 10 ms SSB/CW-priority halt, the emission is killed
  by zeroing the **TX audio gain downstream of WSJT-X's buffer**, not by Halt Tx. In SSB/USB data
  mode, no audio = no emission even with PTT still keyed, so audio mute decouples "stop emitting"
  (fast) from "drop PTT / Halt Tx" (relaxed cleanup). Candidates, cheapest first: **(a)** Windows
  endpoint/session volume API (`IAudioEndpointVolume` / `ISimpleAudioVolume` → 0), applied at the
  WASAPI mix stage so it attenuates already-buffered samples; expect ~10–30 ms. **(b)** software
  audio bridge (virtual cable → local gain app); few ms. **(c)** analog VCA / CMOS switch on the
  audio line; sub-ms, deterministic — the only *guaranteed* 10 ms option. Use a ~2–5 ms cosine/RC
  ramp, never a hard cut (key-click splatter). The mute must run **on the WSJT-X host** (local
  agent, §3.3); the LAN (~1 ms) stays out of the critical path. (Sensor / trigger / actuator breakdown + the two stop layers: §3.4.1.)
- **Multicast vs unicast** — this station uses **multicast `224.0.0.73:2237`** (TTL 3), so WIMS
  joins the group and receives alongside GridTracker/N1MM, non-disruptively. `BroadcastToN1MM=false`
  (N1MM is not fed by WSJT-X's direct unicast — it consumes the multicast). Config:
  `AppData/Roaming/WSJT-X/WSJT-X.ini`; two named instances available (`WSJTX_Flex_A/B`).
- **Port/ID per instance** — confirm N instances can each emit on a distinct port / unique ID
  without collision.

### 1.2 GridTracker
> **Role (resolved, §4.3):** with WSJT-X standardized on **multicast**, GridTracker is a
> **parallel read-only subscriber**, *not* a relay — which sidesteps the forward/grid-drop quirks
> below. On a WIMS-managed instance GridTracker is a **band viewer only**; it must not initiate TX
> (that bypasses the arbiter, §3.4). WIMS's own call roster (§Goals / §3.12) is the click-to-work
> path. So GridTracker is optional per operator preference; go-boxes run none.
- **Grid forwarding quirk** — only relevant if GridTracker is in a *relay* path; multicast avoids
  that. Regression note: grid is forwarded to WSJT-X *only* when triggered from the Call Roster;
  any other trigger logs without grid.
- **Relay/forward behavior** — N/A under multicast (parallel subscriber, no forwarding). Re-test
  only if a station is forced to unicast.
- **Multi-instance handling** — how GridTracker presents traffic from several WSJT-X instances at
  once (still relevant as a viewer).
- **Log export interface** — mechanism for pushing the contest log into GridTracker (feeds §1.5
  and the auto-export feature).

### 1.3 N1MM+
- **Live UDP address change** — N1MM accepts UDP address changes without a restart.
- **Forwarded-packet false positive** — regression: packets from a 2nd WSJT-X instance forwarded
  via GridTracker make N1MM think the first WSJT-X is still running. Find the disambiguator
  (unique ID? port? source?).
- **Instance shutdown** — closing the WSJT-X instance N1MM launched is not enough; the small
  warning window must also be dismissed. Script/automate the dismissal.
- **Dupe / needed — RESOLVED: contactinfo feed + self-compute (no round-trip).** The spot
  round-trip is **dead**: N1MM's `<spot>` broadcast is bare (call/freq/mode, *no* status), and
  `lookupinfo` (External Lookup) is a callbook-data mechanism, greyed out unless an external
  lookup source is configured — neither returns a mult/dupe verdict. **Design:** WIMS subscribes
  to N1MM **`<contactinfo>`** broadcasts as a real-time log feed (50 fields incl. `call`, `band`,
  `mode`, `ismultiplier1/2/3`, `points`, unique `ID`, `timestamp`, edit-tracking via
  `oldcall`/`IsOriginal`), builds its internal log copy keyed on `(call, band, grid)`, and
  **self-computes** dupe + new-mult. Dupe is trivial and rover-correct; VHF mult = `grid × band`,
  calibrated by N1MM's `ismultiplier` on each logged QSO (mirrors a simple rule N1MM keeps honest
  — no contest-engine reimplementation).
  - *Grid source:* N1MM's `gridsquare` is **contest-dependent and was empty** in the DX-config
    test (grid went to `comment`/Cabrillo only). So WIMS takes grid from the **WSJT-X decode**
    (§3.1), not N1MM. *(To confirm later: does `gridsquare`/`exchange1` populate under an actual
    VHF-contest config? Not blocking, since grid comes from WSJT-X.)*
  - *Config (`N1MM Admin.s3db` → Settings/ExternalBroadcast):* broadcasts default **off**,
    destination **127.0.0.1:12060**; enable `IsBroadcastContact`. N1MM also reads WSJT-X UDP
    directly (`EnableWSJTJTDXUDPReader`) → consumes the multicast itself, not via GridTracker relay.
- **N1MM log DB seed + resync** — `DXLOG` table maps 1:1 to `contactinfo` (same fields + same
  unique `ID`). Read-only seed + `reconcile()` resync. **Resync** = re-read `DXLOG` + reconcile by
  ID (handles deletions); operator-triggerable, no N1MM resync feature needed. *N1MM's own
  (networked) Resync merges peer logs into `DXLOG` by unique ID over N1MM's TCP peer channel;
  since WIMS mirrors `DXLOG`, it **inherits** the result at its next reconcile — the two compose,
  and WIMS never speaks N1MM's proprietary network protocol.* **Live edits/deletes:** expect N1MM
  `contactreplace`/`contactdelete` broadcasts — *to verify by editing/deleting a QSO with the
  listener running.* **Open:** confirm `GridSquare` populates under a real VHF-contest config
  (grid comes from WSJT-X regardless).
- **Spot grid source** — spots sent to N1MM must carry grid; source it from the **WSJT-X Decode
  datagram** (`CQ CALL GRID` / Tx1 text) parsed in §3.1, *not* the GridTracker forward path —
  sidesteps the §1.2 grid-drop quirk for decisions. Handle decodes with no grid (e.g.
  `CALL CALL R-12`) via the `call→current-grid` map (§3.5).
- **Log export** — auto-export contest log out of N1MM (to GridTracker + WSJT-X). Format and
  trigger.
- **Inbound contacts** — verify QSOs WIMS/WSJT-X make land correctly in the N1MM master log with
  band/mode/grid.

### 1.4 Green Heron rotator
- **Control protocol** — confirm Green Heron RT-21 command/position protocol (ASCII over
  serial/TCP) for set-azimuth and read-position.
- **Position read-back** — accuracy and update rate good enough for automated pointing.
- **Conflict handling** — what happens if two callers issue moves; does WIMS need to serialize
  rotator commands.
- **Multiple rotators / antennas** — station has several antennas pointed in different directions
  (§Goals). Confirm we can address N independent rotators (per antenna/band) and map
  `antenna ↔ rotator ↔ band/mode`.
- **EME az/el + scheduling** *(blocked / needs hardware decision)* — EME (§Goals) needs
  **elevation** as well as azimuth, and pointing follows the **moon's position** (ephemeris-driven),
  not a DX grid. RT-21 is azimuth-only — confirm the elevation control path (2nd controller? az/el
  rotator?) and the moon-tracking source. Could change rotator hardware.

### 1.5 Cross-app end-to-end
- **Full QSO flow** — decode → reply → logged → appears in N1MM with grid → exported to
  GridTracker/WSJT-X.
- **Grid propagation** — grid survives the whole chain (ties to §1.2 quirk).
- **Multi-instance isolation** — N1MM and WIMS correctly attribute traffic to the right
  instance/band/mode.
- **Packet-flow capture** — capture and visualize real traffic between WSJT-X ↔ GridTracker ↔
  N1MM (feeds the test-bed replay library, §5).

---

## 2. Dashboard — watch the interlock / management program

Single-screen, at-a-glance view so one operator can monitor all digital activity and override by
SSB/CW or hand off to a 2nd op.

### 2.1 Must-show (safety-critical)
- **Transmit-overlap status** — the headline indicator: who holds the TX token right now, and a
  hard, unmissable alert if overlap is ever detected/prevented. Runs the §3.4 `OverlapDetector`
  passively, grouped by shared resource; a violation count + last event are retained as an audit
  trail.
- **Per-instance state grid** — one row per WSJT-X: band, mode, freq, RX/TX, current cycle, last
  decode count.
- **Interlock queue** — which instance is requesting TX, order, and what the arbiter
  granted/denied. (Populates once the command path / click-to-work lets the server grant TX.)
- **Watchdog / runaway status** — heartbeat per app + the "prevent stupid operation" guard state.

### 2.2 Operational awareness
- **Decision log** — station chosen, needed-vs-dupe reason, run/S&P mode, give-up events
  (scrolling).
- **Call roster** — sorted by score value (§Goals); a **rover** reappearing in a **new grid**
  shows as a fresh, high-value row (new mult), not greyed as a dupe. Scored via §3.5 with a visible
  per-factor breakdown; kept current from N1MM `<contactinfo>` so a worked station drops to a dupe
  **per band×grid**. (Feature backlog: §2.6.)
- **N1MM sync status** — `contactinfo` feed alive? log-copy freshness, last log update, last
  resync; plus the startup `.s3db` seed (so the existing log is visibly pulled in before any live
  broadcast). N1MM has no heartbeat — "no recent packet" means quiet, not a fault.
- **Rotator(s)** — per-antenna azimuth (and **elevation for EME**) vs target.
- **Remote station readiness** — PA, 120 V line power, SDR up, PC alive (ties to §1.4 / readiness
  checks).

### 2.3 Controls (human override)
- **Click-to-work** — operator clicks a roster decode → WIMS has the receiving station start the
  contact (§Goals; §3.12). WIMS is the primary operating UI, not monitor-only.
- **Per-instance enable/disable, halt-now.**
- **Global stop-all-TX (panic).**
- **Mode / strategy override per instance.**
- **Manual rotator point** (az, plus el for EME).

### 2.4 Design notes
- **Stack = browser, served by the WIMS server.** Stdlib HTTP + **Server-Sent Events** push the
  §3.12 JSON state to a static HTML/JS page (`src/wims/server/`). No framework/build step; lowest
  lock-in. The **JSON state contract (`server/state.py`) is the durable boundary** — the frontend
  is the only replaceable part.
- **Two-page console.** Both pages share one SSE feed (`/events`) with a header nav toggle:
  **`/` Operate** = workable stations (call roster + interlock/overlap safety banner);
  **`/status` System status** = system/nodes summary, WSJT-X instances, N1MM loggers + sync,
  decode-activity, decode log. Shared `static/wims.css` + `wims.js` (every render no-ops when its
  panel is absent); each page is just the DOM containers it owns.
- **Two-phase UI build (guiding principle).** *Phase 1 — developer-oriented:* information-dense,
  expose internals + diagnostics, breadth over polish; its job is to **validate the design and
  discover what information we actually need** (rendering is deliberately disposable; the
  discovered info-model + API are what's retained). *Phase 2 — operator-oriented:* cull to what
  the operator needs, lay it out, polish, lock conventions. Built against the same (evolved) API.
- Color states defined once (RX/TX/idle/fault) and reused — settle in Phase 2.
- Refresh rate fast enough to see a TX cycle begin (sub-second).

### 2.5 Network setup, health & confidence
Goal: make a complex multi-host UDP fleet **describable, verifiable, and visible** without
reaching for Wireshark — WIMS is already on the wire, so it can be the diagnostic tool (fed by
§3.15).
- **Live topology map** — nodes (WSJT-X instances, N1MM(s), GridTracker, rotators, hosts, WIMS) +
  UDP flows + multicast-group membership + who-logs-whom, health-colored.
- **Expected-vs-actual fleet** — passive discovery of every WSJT-X instance (id/host/band/mode/
  freq/state), health (ALIVE/STALE/DEAD + QUIET = alive-but-no-decodes), id-collision detection
  (same id from 2 hosts), and a diff vs the expected fleet that **names** each discrepancy (missing
  / dead / unexpected / band-mismatch / quiet). Dual-socket (WSJT-X 2237 + N1MM 12060 → loggers
  shown per station name).
- **Protocol-aware packet view ("Wireshark-lite")** — a live **decode log** (time / instance / dB
  / dF / message across the whole fleet, CQ-highlighted) plus per-source packet/decode rates,
  message-type counts, decode hex on demand — filtered to the ham protocols WIMS understands.
- **Per-instance confidence tile** — state + **WSJT-X window / waterfall thumbnail** (via host
  agent, §3.3) + a **UDP-native decode-activity map** (df × cycle × SNR heatmap from the decode
  stream, confirms decodes flowing with no screen capture).
- **Headless aspiration** — WIMS reliable enough that the WSJT-X GUIs are *unnecessary* for normal
  operation: all operation via the call roster + a few info panels; WSJT-X still runs
  (decode/modulate engine) but its window is optional. Thumbnails are the trust-but-verify backstop.
- **Remote-desktop integration (deep-dive layer)** — *layered & decoupled* from the lightweight
  thumbnails. WIMS stores each host's remote-desktop ID/address (§3.14) and offers per-host
  **one-click launch** of an external tool (**RustDesk preferred** — open, self-hostable,
  scriptable, has a web client; AnyDesk works for launch-only, closed). Optional **embedded
  view-only RustDesk pane** scoped to the WSJT-X window for a *live* expanded tile; keep periodic
  stills as the default many-tile view (N live sessions are heavy). WIMS orchestrates/launches; it
  does not reimplement remote desktop. Remote-desktop tools handle their own NAT traversal, so the
  interactive layer works across the internet independent of the data-path overlay (§4.3).

---

### 2.6 Call-roster feature backlog

Consolidated from WIMS design discussions, **GridTracker's Call Roster** (good ideas worth
copying), and decisions taken while building. One reviewable list to select from. **Prio** =
contest value for fixed multi-multi VHF (H/M/L). **Src**: W = WIMS idea, G = GridTracker, D =
decision here. *(Per-feature implementation status is tracked in [wims_status.md](wims_status.md).)*

**Guiding reframe:** GridTracker chases *awards* (DXCC/WAS/grids, LoTW/eQSL-confirmed) for general
operating; WIMS ranks for *contesting* — **mult = grid×band, points, run vs S&P**, with **N1MM as
the dupe/mult authority** (no award confirmation). Copy GridTracker's *interaction model* (all
stations, sortable, filterable, status-per-station, alerts, click-to-work); keep WIMS's contest
scoring as the "wanted" engine.

**A. Population & per-station status**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| A1 | **Show all decoded stations, not just CQ callers** | the headline gap — S&P targets + stations mid-QSO, so the op can pounce/plan | G | **H** |
| A2 | **Per-station status** | tag each row: calling CQ / running / answering ‹call› / in-QSO / **calling us** | G | **H** |
| A3 | **Directed-at-us flag** | unmissable highlight when a station calls our station/grid | G | **H** |
| A4 | Multi-band / multi-instance aggregate | one roster across all ~6 instances | W | H |
| A5 | Age-out stale rows | drop decodes older than a TTL | both | M |
| A6 | Rover in a new grid = fresh high-value row | not greyed as a dupe | W | H |

**B. Columns & sorting**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| B1 | **Sort by any column (asc/desc)** | score default, but also SNR / age / call / band / distance | G | **H** |
| B2 | **Distance + bearing columns** | bearing drives rotator pointing (§3.8); distance = workability | G | **H** |
| B3 | Core columns | score/call/grid/band/inst/SNR/age + dF, mode, status | both | H |
| B4 | Configurable columns (show/hide/reorder) | Phase-2 operator polish | G | L |

**C. Scoring / "wanted" (the contest engine)**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| C1 | Score = weighted factors, **explainable breakdown** | visible per-row "why" | W | H |
| C2 | Factors: new-mult (grid×band) / points / SNR / CQ / rover | | W | H |
| C3 | Weights vary by band condition (open/marginal/dead) | server flag today; UI selector later | W | M |
| C4 | **N1MM is mult authority; roster self-computes prospective + reconciles** | no LoTW/eQSL confirmation | D | **H** |
| C5 | Run vs S&P / needed>dupe / give-up signals | | W | M |
| C6 | Geometry-aware reachability | only rank stations the antenna can hear/point at (§3.14) | W | M |

**D. Grid & data integrity**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| D1 | **Authoritative call→grid memory** (accumulate across all decodes) | load-bearing — mult = grid×band; WSJT-X often lacks grid in a decode | D/G | **H** |
| D2 | **Supply remembered grid to WSJT-X for logging** | correct grid in log → correct N1MM mult (mechanism TBD, Open questions) | D | **H** |
| D3 | Dupe shown greyed (with context) vs hidden | GT keeps B4 rows visible; WIMS excludes — reconsider | G | M |

**E. Filtering**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| E1 | **Band / instance filter** | directly fixes "too many rows" | G | **H** |
| E2 | New-mults-only / hide dupes toggle | trim to high value | both | M |
| E3 | Mode / distance / min-score filters | | G | L |

**F. Alerts**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| F1 | **Alert on new mult / rover in new grid** | audio + visual when high-value appears | G | **H** |
| F2 | TTS callouts, friends list | | G | L |

**G. Interaction / control** (the command path, §2.3 / §3.12)

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| G1 | **Single-click to work** a station → Reply via arbiter + lease | | both | **H** |
| G2 | Per-instance enable/halt, global panic-stop | safety controls | W | H |
| G3 | Right-click context menu / multiple roster windows | Phase-2 | G | L |

**Top of the list (high-prio):** A1/A2/A3 (all-stations + per-station status + calling-us), B1/B2
(column sort + distance/bearing), D1/D2 (grid memory + grid-for-logging), E1 (band filter), F1
(new-mult alert), G1 (click-to-work). View controls (B1, E1) are cheap (client-side over the
existing feed); A1/A2 need the decode pipeline to **retain non-CQ decodes with a status**; G1 is
the command path.

---

## 3. Specific pieces of the WSJT-X management program

Build and test each module independently against the test bed (§5) before integrating in §4.
*(Implementation status: [wims_status.md](wims_status.md).)*

| # | Module | Responsibility | Inputs | Outputs |
|---|--------|----------------|--------|---------|
| 3.1 | **UDP listener/parser** | Decode WSJT-X (and N1MM) datagrams into typed events; **extract grid** from `CQ CALL GRID` / Tx1 decode text | UDP from all instances | Normalized event stream (incl. grid) |
| 3.2 | **UDP controller/sender** | Turn an arbiter grant + chosen decode into the actual command: `reply(instance, decode)` / `halt(instance)`, plus Free Text/Replay. Lease-gated (§3.4/§4.5) | Commands from arbiter/engine | UDP to WSJT-X |
| 3.3 | **Multi-instance manager** | Track N instances; map **port/ID ↔ band/mode ↔ antenna/direction ↔ rotator**; lifecycle (launch/close incl. warning-window dismissal). Includes a **per-WSJT-X-host local agent** (the §3.4.1 fast TX-audio-mute **Actuator** — OS-specific audio-path control + analog-mute GPIO; also captures a **WSJT-X window/waterfall thumbnail** — windowed screen-grab, downscaled, pushed periodically/on-demand for §2.5 confidence tiles). Also a **setup wizard**: collect each **Instance Profile** (§3.14) via a form, auto-discover what it can, **validate** before on-air, verify connectivity to every WSJT-X/N1MM instance, report loss of comms (§Goals) | Heartbeats, profiles, mute commands | Instance registry, mute actuation, thumbnails, setup/validation status |
| 3.4 | **Interlock / TX arbiter** | Grant one transmitter **per shared-resource group** (transmitter/antenna/PA chain, §3.14) — *not* one global token; different bands/vehicles TX concurrently by design. Within a group: zero overlap, no interleaving, single-holder **by construction**. An `OverlapDetector` independently watches *observed* TX state as defence-in-depth. Enforces SSB/CW priority two ways: a **preventive gate** (won't initiate a WSJT-X TX on a band where an SSB/CW station is keyed — band-by-band per contest rules) and a **fast reactive halt** (audio-gain mute on the WSJT-X host, §1.1, kills emission inside 10 ms for mid-cycle keying, then PTT-down + Halt Tx cleanup). Full design: §3.4.1. **Constraint:** WIMS must be the *only* TX initiator on a managed instance — no external app (GridTracker click-to-work, JTAlert, etc.) may send Reply/Tx to it, or it bypasses the arbiter and can cause overlap (§4.3). **TX is gated by the operator control lease (§4.5):** only the current lease-holding console can initiate; no valid lease → instance is RX-only (fail-safe) | TX requests, instance states, SSB/CW priority, lease state | TX grant/deny, fast-mute command |
| 3.5 | **Decision / recommendation engine** | **Advisory, not autonomous** — ranks & recommends for the WIMS operator, who **initiates every TX by click-to-work**; WIMS never transmits unattended. Suggest next-best station, run vs S&P, needed > dupe, give-up. Maintains a **`call→current-grid` map** (with staleness) so a **rover** reappearing in a new grid is treated as a fresh QSO + candidate mult, ranked high; mult value is per `grid × band`. The grid map is **authoritative grid memory** (accumulated across *all* decodes, GridTracker-style but better-retained) — load-bearing because mult = grid×band and WSJT-X often lacks a station's grid in a given decode (e.g. `CALL CALL +08`); WIMS may **supply the remembered grid to WSJT-X for logging** so the QSO records the correct grid → N1MM computes the right mult (mechanism TBD, Open questions). **N1MM is the multiplier authority:** for *logged* QSOs WIMS defers to N1MM's `ismultiplier`; for *prospective* roster candidates (which N1MM can't judge until logged) WIMS self-computes new-mult with the identical `grid×band` rule and continuously **reconciles** to N1MM's verdicts. **No LoTW/eQSL/award confirmation** — that is general-operating chasing (GridTracker), not contest dupe/mult. Ranks the roster by **expected score gain** via a **scoring model** (§3.11) — QSO points + mult value per the contest. **Geometry-aware** (§3.14): only works/ranks stations a given instance's antenna can actually hear — within a fixed beam's sector, or reachable by a re-point inside the soft az limits. The scoring model is **pluggable + explainable** — score = sum of named weighted **factors** (new_mult, points, snr, cq, rover) with a per-factor **breakdown** the operator sees; strategies swappable by name; **weights vary by band condition** (open/marginal/dead); dupe/non-CQ/unreachable excluded with reason | Decodes+grid, dupe/mult status, scoring model, instance profiles | Ranked + explained reply targets, give-up signals |
| 3.6 | **Logger interface** (`LogSource` backend; **N1MM = first impl**) | Abstract behind a small **backend interface** so other loggers (DXLog.net, Log4OM, N3FJP, WSJT-X-native…) plug in later — the engine depends only on the normalized `LoggedQso` + interface, never on N1MM specifics. **Minimal portable contract** (because WIMS self-computes dupe/mult): `seed()` snapshot + `live_events()` add/update/delete stream + `resync()`; optional `mult/points` if the backend supplies it (N1MM does, others may not). **No dedicated WIMS N1MM** — since all contest N1MMs are networked and share one merged log, the **server reads from *any* designated networked N1MM** (e.g. the SSB/CW position's). The logger-of-record invariant (one N1MM *ingests* each WSJT-X stream) is independent of which N1MM WIMS *reads*. **N1MM impl:** seed by reading a `DXLOG` `.s3db` read-only, live via `<contactinfo>` broadcasts (12060) from any N1MM, dedup by `ID`. Maintain log copy keyed on `(call, band, grid)`; self-compute dupe + new-mult (grid×band). Logging path stays WSJT-X→logger; WIMS reads, never double-logs; grid from WSJT-X decode | seed snapshot, live log events, WSJT-X grid | Log copy, dupe/mult verdicts, export trigger |
| 3.7 | **GridTracker interface** | GridTracker is an **optional, parallel read-only viewer** (multicast subscriber, §4.3) — coexists, not in WIMS's control or logging path. WIMS's own roster (§3.12) supersedes its operating role; GridTracker's residual value is its map/viz + ADIF/log-export integrations. Interface = leave the multicast open for it; optionally feed log export | Log, QSO events | (optional) export to GT |
| 3.8 | **Rotator controller** (`Rotator` backend; Green Heron first, **hamlib `rotctld` for breadth**) | Serialize moves across **N rotators**; one **controller-of-record per rotator** (§4.3) — WIMS owns it, or an external program does, never both. **Pluggable pointing sources, arbitrated:** (a) auto from DX-station grid (roster), (b) **operator override — click a roster row to point at its grid, or enter bearing/grid** (the band-opening / N1MM-chat-tip case → fast manual pointing), (c) EME az/el moon-track (§1.4). **Enforces soft az/el limits (§3.14)**; operator override always available and prioritized | Target az/el, antenna sel, profile limits, operator points | Rotator commands |
| 3.9 | **Safety / watchdog** | Heartbeats, runaway detector, sanity limits, fail-safe (TX off). Detects faults by comparing live behavior to each instance's **fault baselines (§3.14)** (silence, freq drift, stuck rotator, PTT-duty, comm-loss). On any fault, trigger the §3.4 fast mute on every host before slower Halt Tx/PTT-down | All module health, instance baselines | Alerts, kill signals, fast-mute trigger |
| 3.10 | **State store / logger** | Single source of truth + audit log of every decision; internal log copy + roster keyed on **`(call, band, grid)`** so rovers aren't collapsed into dupes. **Persistence: own `wims.db` (SQLite, stdlib, WAL)** for queryable state (indexed dupe/mult lookups) + **append-only JSONL** for the raw event/decision stream (replay/audit). SQLite is the derived view, rebuildable from JSONL + N1MM seed. WIMS writes only `wims.db`; never N1MM's `.s3db` | All events | Persisted state, logs |
| 3.11 | **Config** | Per-instance **Instance Profile** (§3.14), strategy/parameter selection, antenna↔rotator map, and the **per-contest scoring model** feeding §3.5 — selects the scoring strategy by name + the per-condition weight sets | Config files / setup form | Runtime config |
| 3.12 | **Server API / integration hub** (the **server↔console boundary**, §4.5) | The unicast API between the **site server** and **operator consoles** (local or remote): serve live state + accept commands — **call-roster feed + click-to-work** (→ Reply via §3.2, lease-gated), **click-to-point** (→ rotator §3.8), and **lease claim/release/forced-takeover** (§4.5). Also **re-publish WIMS's normalized/enriched event stream** (decodes + grid + dupe/mult + priority) so other apps consume WIMS's annotated feed — integration hub, not a closed monolith. Stdlib HTTP + SSE serving the JSON state contract (`state.py`) → static dashboard | State store, lease state | Feed to consoles §2, roster/point/lease actions, published event feed |
| 3.13 | **Override interface** | Let the SSB/CW op or 2nd op supervise/override. The **SSB/CW op's small client app** (§Goals) = a lightweight **console** on the SSB/CW main screen showing WIMS activity on their band (reads the **existing SSB/CW N1MM**, no extra logger). Their **agent** detects keying — **PTT read as the USB-serial CTS line** (§3.4.1 Sensor) — and raises the SSB/CW-priority signal → §3.4.1 fast inhibit, **direct peer-to-peer** (§4.5) | Operator input, priority requests | Commands to arbiter, priority signal |
| 3.15 | **Network discovery & diagnostics** | Be the **protocol-aware network tool so the operator never opens Wireshark**. Passively enumerate live nodes from the multicast WIMS already joins (WSJT-X instances by id/host/group/port/version, N1MM sources, GridTracker); **register N1MM presence from *any* broadcast** (`<RadioInfo>`/`<AppInfo>` beacons, not just `<contactinfo>`, so the link is verifiable at setup with no QSO — capturing StationName + `mycall` + last-seen). Optional active probes (host ping, N1MM:12060, rotator/CAT reachability). **Diff observed vs the declared Instance Profiles (§3.14)** and name every discrepancy. Feeds the §2.5 topology map / health / Wireshark-lite views and the readiness gate | All UDP, profiles, probe results | Live topology, health, discrepancy list |

### 3.4.1 SSB/CW priority interlock (gate + fast halt)

Contest rule: **one signal per band.** When an SSB/CW operator transmits, no WIMS-managed WSJT-X
may transmit **on that same band**. Enforced by **two mechanisms** over a **shared SSB/CW
transmit-state signal**.

**Shared signal — SSB/CW TX-state announcement.** Each SSB/CW position has an agent that **senses
its transmit state** and **announces every transition** (key-down / key-up, with **band** + station
id) as a small **UDP broadcast/multicast** on the LAN. Sensing mechanism: **read the PTT as the
USB-serial *CTS* input line** — the rig's PTT/keying line wired to a USB-serial CTS pin; watch CTS
edges. Hardware-true, sub-millisecond, no rig-CAT round-trip. (Fallbacks if CTS isn't wired:
DSR/DCD line, VOX/audio detect, or N1MM `RadioInfo IsTransmitting` — the last is fine for the
*dashboard* but **too slow for the trigger**.) Every WIMS manager subscribes, so **each WIMS knows
the live TX state of every SSB/CW station, per band.**

**Mechanism 1 — preventive gate (primary; not time-critical).** Before WIMS issues a Reply /
TX-start to a WSJT-X instance on band X, it **verifies no SSB/CW is keyed on band X** (from the
tracked state). If one is, it **holds** the command (defers to the next cycle). This stops the
conflict from ever starting and handles the common case with **no real-time pressure** — a simple
check at TX-initiate time, **band-by-band** per the contest rule. Most conflicts never reach the
10 ms path.

**Mechanism 2 — fast reactive halt (the 10 ms path).** Covers the race the gate can't: SSB/CW keys
up **while a WSJT-X TX is already in progress** on that band (e.g. mid-FT8-cycle). The same CTS
key-down announcement is consumed by a **fast-path receiver on each WSJT-X host — which listens
only for its own band(s)** — that immediately fires the audio-path mute. **Two stop layers, both
fire:**
- **Layer 2 (fast) — control the audio path directly.** Zero the TX audio gain on the WSJT-X host,
  **independent of WSJT-X**, over a 2–5 ms cosine ramp (never a hard cut — key-click splatter).
  Kills *emission* inside 10 ms even while WSJT-X's buffer is still draining (SSB/USB data mode:
  **no audio = no RF**, even with PTT keyed). **OS-specific actuator — needs a platform
  abstraction:** Windows WASAPI volume (`IAudioEndpointVolume` / `ISimpleAudioVolume` → 0); Linux
  ALSA / PulseAudio / PipeWire sink-input volume; macOS CoreAudio; or an OS-independent analog
  **VCA / CMOS switch** (sub-ms, deterministic — the only actuator that meets 10 ms with certainty;
  the software APIs are ~10–30 ms, measure §1.1).
- **Layer 1 (cleanup) — tell WSJT-X to halt.** UDP **Halt Tx** + PTT-down — the proper stop /
  re-arm, but slow (~50–200 ms audio-buffer drain).

**Trigger path is direct, never via the server.** *Co-located* (SSB/CW + WSJT-X on one PC) → local
IPC, or an **analog gate** (the PTT line itself pulls down the WSJT-X TX audio — zero software).
*Cross-host* → the Layer-2 UDP announcement is consumed **directly** by the WSJT-X host's fast-path
receiver (~1 ms LAN). The **server plays no part in the interlock at all** — conflict is **purely same-band** (this
station has no cross-band coupling: no shared PA, no harmonic conflicts), so the band carried in
the announcement is the entire rule. No conflict map, no server in the path; the interlock
**survives a server restart** (§4.5).

**Latency budget (Mechanism 2):** CTS edge sub-ms + UDP ~1 ms (cross-host) or ~0 (co-located) +
actuator ramp 2–5 ms (analog) or 10–30 ms (software audio API). The **actuator is the dominant
uncertain term**; the analog VCA is the only guaranteed-10 ms path.

### 3.14 Instance profile (per-WSJT-X config schema)

WSJT-X instances vary widely, and that variation drives **setup, operation, and fault detection**
alike. Each instance gets one structured **Instance Profile**, captured via a setup form/wizard
(§3.3), validated before on-air, consumed at runtime by the engine/rotator/arbiter, and used as
the "expected normal" baseline by the watchdog (§3.9). Auto-discover what we can (WSJT-X ID, port,
rig); prompt for what we can't (antenna geometry, intended limits).

- **Identity & transport** — label; **unique WSJT-X id = launch each instance with `--rig-name`
  (e.g. `ROY-432`)** — this both isolates that instance's config dir *and* sets the UDP `id` field,
  which is the **real disambiguator** (unique IP is *not* enough: two instances on one PC share an
  IP, and the protocol keys on `id`). Convention: `VEHICLE-BAND`. host (IP/name); UDP **multicast
  group/port** (standardize on multicast, §4.3); **reachability** = LAN vs remote-over-tunnel
  (host-agent relay, §4.3); host **remote-desktop ID/address** (RustDesk, §2.5); the instance's
  **`logger_of_record`** = `local-n1mm` | `wims-n1mm` (which single N1MM logs this instance, §4.3
  invariant); whether an operator **GridTracker** subscribes (read-only viewer — never a TX
  controller on a managed instance).
- **Operating** — band; mode(s) + submode/**period length** (FT8 15 s, MSK144 15 s, Q65
  15/30/60/120 s — drives interlock windows & fault timeouts); dial freq; **RX-only vs
  TX-capable**; role (run / S&P / monitor); priority weight.
- **Radio / TX path** — rig model; CAT path; **PTT method** (CAT / VOX / RTS / DTR — affects halt
  behavior); TX audio device; **fast-mute mechanism** (volume API / virtual cable / analog-GPIO
  pin, §1.1); PA/amp id + power.
- **Antenna geometry** —
  - *type:* **fixed** or **rotatable**.
  - *fixed:* **bearing (°)**, **beamwidth (°)**, gain, fixed elevation. (Engine must know the
    sector this beam actually covers.)
  - *rotatable:* rotator id; az hardware range; **intended/soft az limits (min/max)** — the
    operator's tighter limits for cable-wrap, blocked directions, EMC/neighbors,
    don't-point-at-the-house; wrap/overlap point; az offset/calibration; slew rate; park az.
  - *elevation:* none / fixed / **rotatable (EME)** → el limits; **polarization** (H / V /
    switchable).
  - antenna switch / shared antenna; feedline.
- **Shared resources** — which other instances share this rotator / antenna / amp / host
  (contention → arbiter & rotator serialization).
- **Fault baselines (expected normal)** — heartbeat interval; expected decode-rate window
  (prolonged silence = fault?); expected dial freq (± drift); rotator read-back sanity
  (stuck/runaway); PTT-duty sanity; comm-loss timeout. Per-instance, because a 6 m FT8 run instance
  and a 2 m EME instance look nothing alike.

**Setup-time validation (§3.3) catches misconfig before RF:** duplicate WSJT-X ID / port
collisions; two TX-capable instances sharing one rotator/antenna with no contention policy;
**intended az limits that exclude the instance's needed directions** (warn); el/polarization
present iff EME; a fast-mute mechanism present for every TX-capable instance (else the 10 ms
inhibit can't be met); **exactly one N1MM logs each instance** — flag any instance read by *zero*
loggers (won't be logged) or *two+* (double-log), per the §4.3 invariant.

**How the profile drives each concern:** *setup* = form + validation + auto-discovery; *operation*
= §3.5 geometry-aware decisions (is a bearing reachable, within a fixed beam's sector, or a
re-point inside soft az limits?) and §3.8 enforcing soft limits / never commanding past them;
*fault* = §3.9 comparing live behavior to the per-instance baseline.

---

## 4. Overall WSJT-X management program

Integration of §3 modules into one supervised, fail-safe controller.

### 4.1 Control loop (sketch)
1. Ingest decodes/status from all instances (§3.1), extracting grid from grid-bearing decodes.
2. Look up dupe/new-mult status from WIMS's internal log copy (fed by N1MM `contactinfo`, §3.6,
   calibrated by `ismultiplier`); decision engine (§3.5) picks an action using that status, the
   `call→grid` map, and strategy params (§3.11).
3. Engine requests TX from the arbiter (§3.4).
4. Arbiter grants **one** transmitter, enforcing no overlap / no interleave; controller (§3.2)
   issues the command.
5. Watchdog (§3.9) supervises everything; can halt all TX.
6. Push state to dashboard (§3.12); accept overrides (§3.13).
7. Log every decision (§3.10).

### 4.2 Operating modes (per instance — always a human operator, never unattended)
- **Local-operated** — a local op drives that band's WSJT-X directly; WIMS observes + assists
  (visibility, dupe/mult, interlock), does not transmit.
- **WIMS-operated** — the WIMS **console operator** works the band via the call roster +
  click-to-work (covers an empty seat); WIMS **ranks/recommends**, the operator **clicks every
  TX**. One console op can cover several bands.
- **Handoff** — transfer of an instance between operators (local⇄WIMS, and **WIMS console⇄WIMS
  console**) via the **control lease (§4.5)**: request → grant → release, plus **non-cooperative
  forced takeover** when the holder is gone/idle. Invariant: **exactly one lease-holder per
  instance**; no holder → instance is RX-only (fail-safe).
- *No automated/unattended TX.* WIMS is a remote operating position, not an autobot.

### 4.3 Cross-cutting
- Fail-safe default = transmitters OFF on any fault or lost heartbeat.
- Deterministic arbiter — overlap must be impossible by construction, not by timing luck.
- **Distributed split** — WIMS runs on a separate computer from the WSJT-X/SSB-CW hosts; the
  time-critical TX inhibit (10 ms) executes in a **local agent on each WSJT-X host** (§3.3),
  triggered **directly by the SSB/CW host agent, peer-to-peer (§3.4.1), not via the server** — one Layer-2 UDP datagram over the gigabit LAN (~1 ms). The wire is not in the inhibit critical path; the
  audio-buffer drain and PTT path on the host are.
- **One logger of record per WSJT-X instance** — the *invariant* that makes a mixed N1MM fleet
  safe. A double-logged QSO happens only when two N1MMs independently ingest the same WSJT-X "QSO
  Logged" (each mints its own `ID`, no dedup). So each instance is assigned exactly one logging
  N1MM:
  - *Operator stations* (own N1MM): the **local N1MM logs**, 24/7 — including when WIMS drives that
    instance overnight (WIMS only *drives* WSJT-X via UDP; it does not change the logging path).
    Operating rule: **leave N1MM running** whenever WIMS may drive the station (avoids risky
    mid-session logger reassignment).
  - *Go-boxes* (no local N1MM): a **designated networked N1MM** (e.g. the SSB/CW position's, or the
    server-host's — *not necessarily a dedicated WIMS one*, §3.6) is the logger of record for them
    — keeps the go-box minimal (WSJT-X + host agent, no N1MM).
  - *Mechanism:* segregate WSJT-X UDP streams (per-instance **multicast group/port**) so each N1MM
    ingests only its assigned instances; WIMS subscribes to **all** (it reads, never logs, so
    cannot double-log). N1MM supports two independent WSJT-X readers (`WSJTJTDXUDPIP/IP2`,
    `…Port/Port2`, `EnableWSJTJTDXUDPReader/Reader2`) for source-specific addressing. All N1MMs
    network into one merged log; WIMS reads its own local networked N1MM's `DXLOG`. Declared
    per-instance in the Instance Profile (§3.14, `logger_of_record`), enforced by exactly-one-logger
    setup validation.
- **Single flat LAN across vehicles** — `192.168.10.0/24` on **wired L2 switches** = one broadcast
  domain, so **WSJT-X multicast works across all vehicles natively**; the "everyone joins the
  group" model holds. Each WSJT-X must send on the **LAN NIC, not loopback** (loopback stays on one
  PC — other machines see nothing). Per-vehicle unicast relay (host agent) is a **fallback only**
  (use if managed switches' **IGMP snooping** prunes multicast — verify there's a querier or use
  unmanaged switches).
- **Remote operators = unicast consoles, not multicast forwarding** (§4.5) — the **server** (at the
  site) is the only multicast consumer; remote operator **consoles** connect over a unicast TLS
  WebSocket / **Tailscale** link (Tailscale's lack of multicast is irrelevant — none is forwarded).
  Internet (Starlink) carries only the console↔server link, never the radio data path. Losing a
  remote console → its instances fail-safe to RX (§4.5).
- **Open monitoring, single control per device** — the general principle behind the
  logger/TX/rotator rules. *Monitoring is open:* WSJT-X multicasts, so **any number of apps** (WIMS,
  N1MM, GridTracker, a third-party grid-based rotator program, JTAlert…) can subscribe in parallel
  — WIMS does **not** monopolize the stream, and may even re-publish an enriched feed (§3.12).
  *Control is singular:* each controllable device (a **transmitter** §3.4, a **logger** §4.3
  logger-of-record, a **rotator** §3.8) has exactly **one controller of record** — WIMS or an
  external program, never both, declared per device in the Instance Profile (§3.14). External
  vendors sit behind normalized backend interfaces (`LogSource` §3.6, `Rotator` §3.8, rig CAT via
  hamlib) so new ones plug in without touching the engine.
- **Standardize WSJT-X on multicast** — on the LAN, every consumer (N1MM, GridTracker, WIMS)
  **joins the group as a parallel subscriber**; nobody relays. This removes the GridTracker relay
  loop and its §1.2 forward/grid-drop quirks entirely. *GridTracker stays a read-only band viewer;
  it must NOT be used to initiate TX on a WIMS-managed instance — that bypasses the arbiter (§3.4).
  WIMS's own call roster (§Goals/§3.12) provides click-to-work through the interlock, so GridTracker
  is optional, not in the control path.*
- Config-driven so a contest can be set up without code changes.
- Screen-share path to manage the remote station.

> **Milestones** (M1–M7) and per-module build status live in
> **[wims_status.md](wims_status.md)**.

---

## 4.5 Client/server architecture & control leases

**Role:** WIMS is the **digital operating position** ("the WSJT-X wrangler") — one human covering
~3 radios / ~6 instances on 6 m so the SSB/CW op can focus on that. In slow spells one op can run
SSB/CW and watch the WIMS screen at once.

**Split WIMS into a site server + operator consoles** — this is *the* architecture (the §3.12
dashboard API promoted to the system boundary):

- **WIMS server** — runs at the contest site on the LAN. The *single* multicast consumer, state
  authority (roster, log copy, dupe/mult, fleet health), and the *only* sender of control to
  WSJT-X.
- **Operator console** — thin client (the dashboard UI) over **one unicast connection** to the
  server; identical whether on the LAN or across the internet.

**Packaging — one installable, three stackable roles.** Single codebase, configured per machine:
**server** (one per site), **console** (N, operator UIs), **agent** (one per radio host / SSB-CW
position — fast mute, thumbnail, optional relay, SSB/CW-TX monitor). Setup guide, fault monitoring,
dashboard are *features inside* server+console, not separate roles. A machine may stack roles (site
PC = server+console; radio PC = agent; SSB/CW PC = agent+console). **The SSB/CW-priority safety loop
stays LOCAL to the agent** — the agent detecting the SSB/CW op keying mutes the conflicting
co-located WSJT-X *directly* (hits the 10 ms budget, survives a server/console restart). The server
plays **no part** in the interlock: it is keyed purely on **band** (same-band only — no cross-band coupling at this station), carried in the announcement, and the trigger is **direct agent-to-agent** (§3.4.1, Layer-2 UDP), never via the server.

**Leases scope control, not view.** Every console *views* all instances (open monitoring); the
lease only decides **who may TX which instance** — so two consoles can split the fleet (A leases
instances 1–3, B leases 4–6), or one grabs all, or they rebalance live. Per-instance granularity is
what enables the split.

**Remote operation without forwarding multicast.** The server is the only multicast subscriber; a
remote console receives *normalized* state + thumbnails and sends *commands* — all unicast over a
TLS WebSocket / Tailscale link. So **Tailscale being unicast-only is a non-issue** — multicast
never crosses the internet. Latency is irrelevant for digital (15 s FT8 cycles ≫ 50–100 ms RTT),
and the safety-critical **10 ms SSB/CW mute stays in the host agent at the site**, never on the
remote operator's path.

**Control leases (non-cooperative handoff).** A single authoritative server means **no split-brain**
(never two operators transmitting). Per **instance** (or resource group), the server holds an
**operator lease**:
- Exactly one console holds it; only its commands are honored (§3.4).
- Holder sends a **heartbeat**; if it stops (operator away, sleep, link drop) the lease goes
  **stale**.
- A new console **claims** it — instantly if stale, or via **forced takeover** (short on-screen
  warning/countdown) if live-but-idle. No cooperation from the leaving operator needed.
- All control flows through the server, which honors only the current lease, so a zombie console's
  stale commands are rejected → **overlap impossible.**

**Dragon-slayer — fail-safe to RX.** An instance with **no valid lease holder simply does not
transmit (drops to RX).** So "operator vanished, nobody grabbed control" is *safe*, not dangerous.
Handoff is therefore only ever about **continuity**, never **safety** — overlap/runaway are
impossible by construction (this is where "no automated operation" pays off: no operator → no TX).

**Caveat — single point of failure, NOT solved by consensus.** One authoritative server can die.
Do **not** use multiple servers + leader election (real dragons). Instead make the server
**restart-and-resync fast**: its state is reconstructable (re-seed log from N1MM, re-discover
instances from multicast in seconds). Crash → restart → consoles reconnect, minimal loss.

---

## 5. Test bed for the WSJT-X management program

Exercise the program safely with **no RF** and reproducible scenarios.

### 5.1 Simulators / harness
- **WSJT-X emulator** — emits realistic Heartbeat/Status/Decode for N configurable instances
  (distinct rig-name ids, bands, `CQ CALL GRID`, rover grid-changes) on the multicast, and
  **reacts to Reply → TX / Halt → RX**. Scenario-file scripting drives the §5.2 cases.
- **Captured-traffic replay** — replay real packet captures from §1.5 at correct timing.
- **N1MM stub** — accepts spots and returns dupe/new-mult status (§1.3), rover-aware on
  `(call, band, grid)`; emits `contactinfo` broadcasts; accepts QSOs.
- **Rotator stub** — accepts rotator commands for N rotators, reports simulated **az/el** position
  (EME).
- **Fast-mute harness** — measure/verify TX-audio mute latency (Windows volume API vs analog) on a
  host agent (§1.1).
- **Assertion harness** — an `OverlapDetector` (§3.4) flags any group with >1 transmitter; the
  **"no two instances ever TX at once"** invariant, exercisable live.

### 5.2 Scenario library
- All-dupe band (engine should hold / move on).
- Needed station appears mid-cycle (priority + reply).
- Interlock stress — multiple instances request TX simultaneously; verify zero overlap, no
  interleave.
- Give-up case — station that never completes.
- App crash / restart — instance drops and returns; WIMS re-syncs.
- Misconfigured profile — setup validation (§3.14) catches port/ID collision, shared rotator with
  no contention policy, az limits excluding needed directions, missing fast-mute on a TX instance.
- Forwarded-packet false positive replay (the §1.3 N1MM quirk).
- Runaway trigger — confirm watchdog halts TX.

### 5.3 Bench → on-air staging
- **No-TX/inhibit mode** — global flag prevents any real transmit while logic runs live.
- **Dummy load** stage before antenna.
- **Single-instance on-air** before multi-instance on-air.
- Define explicit go/no-go gates between each stage.

---

## 6. Operating scenarios

Short narrative scenarios that describe how the system behaves in real operating situations,
written *before* detailed design so they drive the specification — requirements, module
responsibilities (§3), and test-bed cases (§5.2). Fill these in over time; each completed scenario
should trace to the modules and tests it motivates.

### Scenario template
Copy this block for each new scenario.

```
### S# — <short title>
- Context / preconditions:
- Trigger:
- Walkthrough:
- Expected behavior (definition of "correct"):
- Drives / exercises:   (modules §3.x, tests §5.x, requirements)
- Open questions raised:
- Mode:                 manual / supervised / auto
```

### Worked example (sample — rewrite as you like)

#### S1 — Cold start & station readiness check
- **Context / preconditions:** Pre-contest. Remote station powered; N WSJT-X instances launched,
  one per band/mode.
- **Trigger:** Operator requests "bring up / arm."
- **Walkthrough:** WIMS confirms each instance's heartbeat, checks N1MM, GridTracker, and the
  rotator are reachable, and verifies station readiness (PA, 120 V line power, SDR up). Each band
  turns green on the dashboard; anything missing shows red.
- **Expected behavior:** Operation stays blocked until all *required* readiness checks pass; every
  failing item is named on the dashboard, not just flagged.
- **Drives / exercises:** §3.3 multi-instance manager, §3.9 safety/watchdog, §2.2 readiness panel;
  go/no-go gate for M1 and M5.
- **Open questions raised:** Which checks are mandatory vs. advisory? How is "PA ready" actually
  sensed?
- **Mode:** setup.

### Scenario backlog (to write)
Candidate situations worth covering — rename, add, or cut freely:
- S1 — Cold start & station readiness check *(example above)*
- S2 — Run on an open band (work needed, skip dupes)
- S3 — Interlock contention: two instances want to TX in the same window
- S4 — Meteor scatter (MSK144): patience and the give-up decision
- S4b — EME: az/el moon-tracking, long periods, scheduling around moonrise/set
- S5 — Rare grid / multiplier appears: priority + rotator point
- S5b — **Rover in a new grid**: same call worked earlier reappears from a different grid → WIMS
  self-computes "not a dupe, new mult" from the log copy (§3.6) → ranked high, rotator re-points;
  stale-grid handling for grid-less decodes
- S6 — Run vs S&P switch as conditions change
- S7 — Human override: op grabs one instance, then hands it back
- S8 — Multi-op handoff (primary op → 2nd op)
- S9 — Fault / runaway: stuck TX or lost heartbeat → watchdog halts
- S10 — Known quirk in the wild (GridTracker grid drop / N1MM false "still running")
- S11 — Remote control / screen-share link degrades → fail safe
- S12 — End of contest: auto log export + reconcile across N1MM and GridTracker
- S13 — **Mixed N1MM fleet**: go-box (no N1MM, logged by WIMS's central N1MM) + operator station
  (own N1MM) + hybrid 222/432 station (operator by day, WIMS-driven FT8 overnight, local N1MM logs
  throughout). Verify one-logger-of-record holds, no double-logging, all QSOs reach WIMS's log copy.
  GridTracker running as a viewer on the operator station does not perturb logging or TX.

---

## Open questions / parking lot
- **"Aurora is 6000"** *(needs clarification)* — from the original notes; meaning unresolved
  (budget? product? propagation note?). Clarify and file under the right section.
- Confirm exact WSJT-X UDP message IDs/names against the current protocol header.
- **10 ms SSB/CW halt — mechanism** — *resolved approach:* not WSJT-X Halt Tx (too slow, ~50–200 ms
  buffer drain) but a fast **TX-audio-gain mute on the WSJT-X host**, with Halt Tx/PTT-down as
  cleanup (§1.1, §3.4). Open sub-question: does the Windows volume API (~10–30 ms) meet budget, or
  is an analog VCA/switch (sub-ms, guaranteed) required? → measure (§1.1).
- **Abort vs. block-next-cycle** — is a true mid-cycle abort needed, or does blocking the next TX
  cycle + letting the SSB/CW op wait (their "small program") suffice? Determines whether the 10 ms
  inhibit is on the critical path at all.
- **Unicast vs multicast — RESOLVED:** **multicast** standard (this station already uses
  `224.0.0.73:2237`); makes all consumers parallel subscribers (§1.1, §4.3).
- **WSJT-X thumbnail capture mechanism** — waterfall/main-window imagery is *not* in the WSJT-X UDP
  protocol, so the §3.3 host agent must **screen-capture** the window (Windows `PrintWindow`/DWM for
  a non-foreground window; handle minimized; pick frame rate ~0.5–2 fps or on-demand; downscale to
  keep LAN cost trivial). Complementary UDP-native **decode-activity map** needs no capture. Decide
  capture lib + how it coexists with a headless/RDP session.
- **"Needed vs dupe" path to N1MM — RESOLVED** (§1.3): spot round-trip dead (`<spot>` bare,
  `lookupinfo` is callbook-only/greyed). WIMS subscribes to N1MM `<contactinfo>` as a log feed and
  self-computes dupe + new-mult (grid×band) using WSJT-X-sourced grid, calibrated by N1MM
  `ismultiplier`.
- **Grid → WSJT-X for logging** — WIMS's `call→grid` memory (§3.5) frequently knows a station's grid
  when the live WSJT-X decode doesn't (GridTracker retains grids better). To get the right grid into
  the log (→ correct N1MM mult), can WIMS push a grid to WSJT-X over UDP — there is no obvious "set
  DX grid" message, **verify against the protocol header** — or must the grid reach the log another
  way (enriched feed / logger-side fill)? Resolve the mechanism.
- Choose dashboard tech stack. *(Resolved: stdlib HTTP + SSE + static HTML — §2.4.)*
- **EME pointing hardware** *(blocked)* — elevation control + moon-tracking is unspecified; RT-21 is
  azimuth-only (§1.4, §3.8). May require additional/different rotator hardware → resolve before
  §3.8 design.
- **GridTracker's role — RESOLVED** (§4.3/§1.2/§3.7): under multicast, GridTracker is an optional
  **parallel read-only viewer**, not a relay and not a TX controller; WIMS's roster (§3.12) is the
  click-to-work path. Coexists per operator preference; go-boxes run none.
- **Scoring model source** — per-contest QSO-point + multiplier rules feed §3.5 ranking and §3.11
  config. Hand-author per contest, or derive from N1MM's loaded contest definition?
- **Instance profile — format & auto-discovery** — file format for the Instance Profile schema
  (§3.14) and how much the setup wizard can auto-discover (WSJT-X ID/port/rig via UDP/CAT) vs must
  prompt for (antenna geometry, intended az/el limits). Decide the form vs file-edit balance.
- **ARRL VHF operating rules (no automation)** — WIMS does **not** automate; every QSO is
  operator-initiated (local or WIMS console op), so the robotic-operation concern is moot. Lighter
  check: confirm multi-multi rules on a **console operator working multiple transmitters / remote
  operating positions** within the same site are fine (expected to be, for fixed unlimited
  multi-multi at one site).
