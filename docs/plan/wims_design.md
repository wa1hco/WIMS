# WIMS — WSJT-X Instance Management System: Requirements & Design

*Working name: **WIMS** (WSJT-X Instance Management System).*

This is the **requirements / goals / design** source of truth for WIMS — a supervised,
human-in-the-loop console for multi-instance VHF contesting, plus the integration plumbing
around N1MM+, GridTracker, and rotators (Yaesu protocol / K3NG). It describes *what* WIMS must do
and *why*, and
records design decisions as they're made.

**Build status, milestones, the module-implementation table, and the build log live in the
companion tracker [wims_status.md](wims_status.md).** Keep the two separated: change this file
when the *design* changes; record *progress* there.

**Fleet networking map** (WSJT-X / N1MM / GridTracker multicast ports, logger segregation,
consoles, **resilience & guided setup** for tired/non-expert seat ops):
**[wims_networking.md](wims_networking.md)** (§12).

---

## WIMS goals

WSJTX Instance Management System (WIMS) is a tool to manage multiple instances of WSJT-X either
on the same band or on several bands. A station may have several antennas with receivers and
WSJT-X running to look in different directions. A station may have WSJT-X monitoring for FT8,
EME, or meteor scatter simultaneously. A station may have several bands receiving simultaneously.

WSJT-X sends each decoded message to WIMS which displays them in a call roster along with
information about the source. In a manner similar to GridTracker's call roster, the operator can
click on a retained decode (CQ/QRZ **or a 73 for tailend**, GridTracker2-style) to cause the
receiving station to start a contact via UDP **Reply**. **Calling CQ and autoresponding to the
pile** is done in the **WSJT-X UI** at the seat (or remote desktop to that seat) — the UDP API
cannot run that mode usefully; see **§2.12**.

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
                           N1MM+ (log, ◀┘          └▶ Rotator(s) Yaesu/K3NG
                           dupe/needed)
                               ▲
                 GridTracker ──┘  (grid forwarding, log export, packet relay/viz)
```

Key constraints carried over from the notes: **zero overlap on transmitters** (*per
shared-resource group* — see below), **WSJT-X transmissions cannot be interleaved**, and WIMS
**ranks/recommends** who to work and when to give up — the human initiates every TX. **Run (CQ)
vs S&P is split by protocol reality (§2.12):** WIMS drives **S&P and tailend** over UDP
(click-to-work → Reply on a retained decode, including **73**); **run/CQ + pile autorespond stays
in the WSJT-X UI** because the UDP API cannot start a CQ or keep answering callers.

### Deployment context (current operation)

A **fixed, unlimited multi-multi** entry in the **ARRL June & September VHF** contests —
stationary, **one grid, no roving on our side**. Vehicles / sites: **"Roy"** (truck) 222 + 432;
**"Chip"** (truck) 903 + 1296 + up (microwave); **"Trailer"** 50 + 144; plus possible
**off-trailer radio sites** (e.g. **TV station** tower for one or more **50 MHz** WSJT-X hosts).
Today the sites have a network between them **but no shared visibility — coordination is by chat
only.** WIMS's headline value is the **cross-site operations console**: one combined call roster,
per-band activity + health, one merged log / dupe-mult view — replacing "anyone there?" over chat.

**Digital fleet (authoritative — networking detail in
[wims_networking.md](wims_networking.md)).** Plane map, seat-local CAT (not a WIMS plane), and
the preferred **Icom + wfview** seat stack: **[wims_networking.md](wims_networking.md) §3 /
§3.2 / §3.3**.

**Digital fleet summary:**

| Band | N1MM (one, logger-of-record) | WSJT-X hosts |
|------|------------------------------|--------------|
| **50** | **N1MM-50** (typically trailer / central) | **1–N** FT8 instances: trailer beam PCs **and/or remote** (e.g. **TV station PC + radio**). Remote hosts do **not** run a second N1MM for 50 — they only emit plane A multicast; N1MM-50 is sole reader. |
| **144** | **N1MM-144** | **Up to two** hosts: separate **radio + PC** for FT8 and for MSK144 (or EME); both use **the same** N1MM-144. |
| **222** | **N1MM-222** | **One seat PC** (e.g. Roy): **SSB and/or FT8** as the period requires (not always digital). |
| **432** | **N1MM-432** | **One seat PC** (e.g. Roy): **SSB and/or FT8** as equipped. |

→ **4 N1MMs** (one per band), all networked into one contest log (plane C). WSJT-X count is
**variable** (remote 50, optional second 144 PC, 222/432 idle of FT8 during SSB runs). Shorthand
“band = one PC” is **false** on 50 and often 144; **true** for typical 222/432 seats.

- *Mapping:* **site/vehicle ≈ one or more hosts**, **instance = one WSJT-X** (`--rig-name` / UDP
  id); **band = one TX resource group** (one radiated signal — all 50 MHz radios, including TV
  station, share `50-signal`; 144 FT8 + MSK share `144-signal`).
- *Logger vs radio location:* **N1MM need not co-reside with WSJT-X.** Radio and WSJT-X stay at the
  antenna site; the band’s N1MM may sit at the trailer and ingest multicast. Full rules:
  [wims_networking.md](wims_networking.md) §1.1–§1.3.
- *Network:* single **contest LAN**, **wired L2** across trailer, Roy, and remote 50 (TV site) so
  **WSJT-X multicast works natively**. **Segregate UDP by band** (port or group) so each N1MM is
  the sole logger for its band; WIMS joins **all** streams. Per-site unicast relay is a
  **fallback**, not required. *Watch:* managed switches with **IGMP snooping** + no querier can
  prune multicast — verify on plain/unmanaged L2 it floods fine. Internet is **1–2 Starlinks**,
  separate Starlink WiFi for other devices — **out of the WIMS data path** (WIMS radio path is
  LAN-only; Starlink CGNAT/latency never involved). Remote 50 **must** be on contest L2, not
  “over the public internet only.”
- *Rover dupe still applies:* our position is one fixed grid, but we **work rovers** (others'
  stations moving between grids); each grid×band is a mult, so the `(call, band, grid)` dupe key
  (grid from the WSJT-X decode) stays necessary for worked stations.
- *Arbiter scope:* multi-multi = multiple simultaneous transmitters by design; zero-overlap is
  enforced **per resource group** (transmitter/antenna/PA chain **or same-band signal**, §3.14)
  — 50, 144, 222, 432 may TX concurrently; **all** 50 MHz instances (trailer + remote) contend for
  one `50-signal` token (§3.4).
- **Operating model — NO automated operation.** Every active transmitter always has a human
  operator: either the **local op in the seat / remote site**, or the **WIMS console operator** who
  **smoothly takes over** a band when its seat is empty (e.g. 222/432 when nobody's there). WIMS is
  a **remote operating position + force-multiplier** — one console op covers several empty-seat
  bands via the call roster + click-to-work. WIMS **ranks/recommends; the human initiates every
  TX**. The key UX is **clean handoff** (local ⇄ WIMS op, instant claim/takeover, §4.5) with always
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
- **Free Text as closing / QSY message** — verify end-to-end that Free Text can carry a short
  operator message (e.g. `QSY 432`) on the final TX of a contact: character limit, whether it
  replaces the scheduled 73/RR73 or requires free-text mode, earliest/latest safe injection in a
  cycle, and whether QSO Logged still fires. Feeds §2.8 (closing free text / QSY).
- **Trigger CQ / run mode via UDP — RESOLVED: not supported (usable).** Protocol facts
  (`NetworkMessage.hpp` + **live `MainWindow::replyToCQ` in WSJT-X 3.0.1**) lock the design in
  **§2.12**. Summary:
  - **No inbound message** starts a CQ, selects Tx1–Tx6, or turns on Call 1st / “answer callers
    while I run.” `Configure` can set DX call/grid and *Generate Messages* but does **not**
    Enable Tx or put the instance into run mode.
  - **Reply (msg 4)** *is* the click-to-work path — but it is **broader than CQ-only** in actual
    WSJT-X 3.0.1 (the NetworkMessage.hpp wording is outdated). WIMS must **echo a prior Decode’s
    fields** (GridTracker2 `initiateQso` pattern). WSJT-X finds that line in Band Activity and
    runs `processMessage`; it sets double-click / auto-TX when the text is **CQ/CQDX/QRZ**,
    contains **`73 `** (classic **tailend**), or **Hold Tx Freq** is checked — see §2.12.
  - **Free Text (msg 9)** with `Send=true` can force one free-text transmission (including a
    one-shot `CQ MYCALL GRID` string) but WSJT-X **does not auto-sequence** after it — no
    autorespond to callers. Unsuitable as run mode; experimental FreeText-CQ remains off by
    default and is **not** a product path for contest run.
  - **Halt Tx (msg 8)** still works and is the WIMS stop path for both S&P and observed run.
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
- **Multicast vs unicast** — this station uses **multicast `224.0.0.73` + one UDP port per band
  stream** (TTL 3; default ports **2237–2242** for 50→1296 per [wims_networking.md](wims_networking.md)
  **§4** — e.g. 144 MHz → **2238**). Sequential ports are a **human-minimal default**, not a
  protocol law: a **Band Stream Registry** (Setup/agent) may assign any free ports and apply
  WSJT-X / N1MM config. **Dual consumers per stream:** N1MM-band = logger only; WIMS joins
  **all** streams for decode/roster (never double-logs). `BroadcastToN1MM=false` when N1MM
  already reads the band multicast. Config: `WSJT-X.ini` (Windows) or `~/.config/WSJT-X*.ini`
  (Linux, including `WSJT-X - <rig-name>.ini`). Seat CAT (wfview, etc.) is orthogonal — §1.1
  is UDP only; see networking **§3.2–§3.3**.
- **Outgoing interface is mandatory** — Settings → Reporting → **Outgoing interface** must be the
  **contest LAN NIC**. Blank / Qt `@Invalid()` / loopback is a **silent failure mode**: WSJT-X
  still decodes, but Heartbeat/Status/Decode never reach WIMS or other hosts (observed: one
  instance on `127.0.0.1` visible to WIMS, another on `224.0.0.73` with `@Invalid()` interface
  invisible despite local decodes). **Setup, config verification (`wsjtx_config`), and continuous
  readiness must all treat this as a first-class error** — see
  [wims_networking.md](wims_networking.md) §4 / §12.
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
  and WIMS never speaks N1MM's proprietary network protocol.* **Live edits/deletes:** N1MM
  `<contactdelete>` removes the QSO from the log copy by `ID` (roster needed/dupe updates
  immediately); `<contactreplace>` upserts like `<contactinfo>` (edit = delete + replace).
  **Open:** confirm `GridSquare` populates under a real VHF-contest config
  (grid comes from WSJT-X regardless).
- **Spot grid source** — spots sent to N1MM must carry grid; source it from the **WSJT-X Decode
  datagram** (`CQ CALL GRID` / Tx1 text) parsed in §3.1, *not* the GridTracker forward path —
  sidesteps the §1.2 grid-drop quirk for decisions. Handle decodes with no grid (e.g.
  `CALL CALL R-12`) via the `call→current-grid` map (§3.5).
- **Log export** — auto-export contest log out of N1MM (to GridTracker + WSJT-X). Format and
  trigger.
- **Inbound contacts** — verify QSOs WIMS/WSJT-X make land correctly in the N1MM master log with
  band/mode/grid.

### 1.4 Rotator (Yaesu protocol / K3NG — primary)
This station’s rotator control path is **not Green Heron-first**. Fleet rotators are driven by
**K3NG rotator controller** software (Arduino-based, or a maintained fork/version in use on the
seat) speaking the **Yaesu GS-232A/B-style** serial protocol over USB-serial or TCP serial bridge.

- **Protocol (Yaesu GS-232 family)** — verify the command subset K3NG exposes that WIMS needs:
  **read az** (e.g. `C` / `C2`), **move to az** (e.g. `Mxxx`), stop, optional **el** (`W` / elevation
  queries) if an elevation motor is fitted. Confirm degree format, leading zeros, and whether
  the local K3NG build is GS-232A vs GS-232B (response differences). Document the exact dialect
  against the **version of K3NG** deployed at the site.
- **Transport** — serial device path or host:port to each controller; one logical rotator id per
  antenna/rotator. Host agent (§3.3) may own the serial port if WIMS server is remote.
- **Position read-back** — poll rate good enough for UI + “within beam?” (sub-second not required;
  ~0.5–2 s typical). Accuracy vs true heading (calibration / az offset in profile §3.14).
- **Moving / settled** — detect in-motion vs on-target (commanded az vs reported az + timeout);
  UI must show “slewing…” so the op doesn’t call CQ mid-spin.
- **Conflict handling** — serialize commands **per rotator**; one controller-of-record (§4.3).
  WIMS is that controller when the instance is WIMS-managed.
- **Multiple rotators / antennas** — map `antenna ↔ rotator ↔ band/instance` (Trailer multi-beam
  may be fixed az — no rotator; Roy/Chip bands may each have a rotator). Fixed beams still show
  roster **Az** as DX bearing; only rotatable instances get click-to-point.
- **EME az/el + scheduling** *(open)* — EME needs elevation + moon track. K3NG can support el if
  hardware is present; otherwise separate path. Ephemeris source TBD.
- **Optional backends later** — Green Heron RT-21, hamlib `rotctld`, etc. behind the same
  `Rotator` interface (§3.8); **Yaesu/K3NG is the first implementation**.

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
- **Call roster** — **GridTracker-style flat table, one row per station heard** (every decode with a
  callsign, CQ or mid-exchange), scored via §3.5 with the score **kept as a sortable column** (not the
  only view). **Population is subscription-scoped (§2.7 / §2.11):** the operator **subscribes to a
  fleet station/band** (seat or band instance); only decodes from subscribed bands appear in *that
  operator’s* roster. Columns: **DX callsign · Calling** (who they address — `CQ` or the worked call)
  **· Band · Mode · Grid · dB · Freq** (RF = instance dial + decode audio df) **· Az DX**
  (great-circle bearing **from our receiving instance’s `de_grid` to the DX grid**) **· km**
  (great-circle distance) **· Age · Op** (band manager — stubbed until §3.14) **· Score**.
  **UTC column dropped** from the default table (Age is enough; `ts` remains on the wire).
  **No Work button** — click the **row** to Work (GT2-style). **Highlights:** **calling-us**
  (red background — station’s `to_call` matches instance `de_call`, like WSJT-X Band Activity
  red) and **armed** (green edge — Status `tx_enabled` and `dx_call` match this row, even if not
  yet transmitting). Priority: calling-us > armed > mult. Later (M4 / §2.10): **Az ant**, **Δaz**,
  rotating font, optional point-on-Work. **Every header sorts**; need/band filters persist.
  Rover new grid = fresh mult row; worked stations dimmed per band×grid. Contract fields include
  `is_calling_us`, `is_armed`, `az` (Az DX), `distance_km`, `ts`, `to_call`, scores. Geometry:
  `engine/geo.py`. Full rotator + subscription: §2.10 / §2.11. (Backlog: §2.6.)
- **N1MM sync status** — `contactinfo` feed alive? log-copy freshness, last log update, last
  resync; plus the startup `.s3db` seed (so the existing log is visibly pulled in before any live
  broadcast). N1MM has no heartbeat — "no recent packet" means quiet, not a fault.
- **Rotator(s)** — per-antenna **live az** (and el if fitted) vs **commanded target**, moving/
  settled, health (link up to K3NG). Full design §2.10 / §3.8.
- **Remote station readiness** — PA, 120 V line power, SDR up, PC alive (ties to §1.4 / readiness
  checks).

### 2.3 Controls (human override)
- **Band / station subscribe** — operator selects which fleet station(s)/band(s) to cover; that
  **subscription is what fills their call roster** with decodes from those bands (§2.11). Distinct
  from (but related to) TX control claim (§4.5): subscribe = “show me this band”; claim = “I may
  command TX/rotator on it.”
- **Click-to-work (S&P + tailend)** — operator **clicks a roster line** (GridTracker2-style; no
  Enable/Disable TX arm) → WIMS sends **Reply** echoing that station’s retained decode via the
  arbiter + control claim (§Goals; §2.12; §3.12). Covers answering **CQ/QRZ** and **tailending** on
  a **73** (and other lines WSJT-X will accept — §2.12). Primary WIMS-driven TX path. **Not** a
  substitute for the WSJT-X run/CQ UI.
- **No “Call CQ” console button (product path)** — starting a run is done in the **WSJT-X UI** at
  the seat (or via remote desktop/KVM to that seat). See §2.12. An experimental FreeText CQ API
  may exist for lab spikes only; it must not be presented as run mode.
- **Click-to-point** — operator uses the roster **Az DX** (bearing to DX) to command the band’s
  rotator to that heading via Yaesu/K3NG (§2.10 / §3.8). Separate from click-to-work so the op can
  point without starting TX, or work without re-pointing a fixed beam.
- **Closing free text / QSY on final 73** — optional operator-chosen free-text (e.g. `QSY 432`)
  sent via WSJT-X Free Text on the completing contact, instead of a plain 73/RR73. Full design:
  §2.8. **Assess-then-decide:** operator reviews cross-band evidence (§2.9) and chooses accept /
  other band / skip; never auto-applied. WIMS never auto-sends free text unattended.
- **Per-instance halt-now** (UDP Halt Tx) — stops S&P QSOs WIMS started **and** can interrupt a
  local run (fail-safe / SSB-CW priority / panic). Does not “disable CQ mode” in WSJT-X settings.
- **Global stop-all-TX (panic).**
- **Mode / strategy override per instance** — advisory run-vs-S&P **recommendation** and give-up
  signals (§3.5); does **not** flip WSJT-X into CQ (that remains seat UI, §2.12).
- **Manual rotator point** — enter az (or grid → bearing), stop, park; el for EME if fitted.

### 2.4 Design notes
- **Stack = browser, served by the WIMS server.** Stdlib HTTP + **Server-Sent Events** push the
  §3.12 JSON state to a static HTML/JS page (`src/wims/server/`). No framework/build step; lowest
  lock-in. The **JSON state contract (`server/state.py`) is the durable boundary** — the frontend
  is the only replaceable part.
- **Three-page console.** All pages share one SSE feed (`/events`) with a header nav:
  **`/` Operate** = workable stations (call roster + interlock/overlap safety banner);
  **`/status` Status** = **live health** — system/nodes, WSJT-X instances, N1MM loggers + live
  sync, decode-activity, decode log (RF / operators / signals);
  **`/setup` Setup** = **configuration & install diagnostics** — contest log picker (multi-contest
  `.s3db`), networking checklist, seed paths, host app config audit (WSJT-X / N1MM / GridTracker;
  growing). Setup is generally static or slow-changing; Status is the “is the contest healthy?”
  view. Shared `static/wims.css` + `wims.js` (every render no-ops when its panel is absent).
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
§3.15). **Resilience for non-expert seat operators** (reboots, fatigue, 222/432 not run by WIMS
authors): contest profile as source of truth, guided seat bring-up, continuous 🟢/🔴 readiness with
**one plain-language fix**, fail-soft (no TX while red) — full how-it-works in
**[wims_networking.md §12](wims_networking.md#12-resilience--guided-setup-tired-operators-restarts)**.
- **Live topology map** — nodes (WSJT-X instances, N1MM(s), GridTracker, rotators, hosts, WIMS) +
  UDP flows + multicast-group membership + who-logs-whom, health-colored.
- **Expected-vs-actual fleet** — passive discovery of every WSJT-X instance (id/host/band/mode/
  freq/state), health (ALIVE/STALE/DEAD + QUIET = alive-but-no-decodes), id-collision detection
  (same id from 2 hosts), and a diff vs the expected fleet that **names** each discrepancy (missing
  / dead / unexpected / band-mismatch / quiet). Dual-socket (WSJT-X 2237 + N1MM 12060 → loggers
  shown per station name). **Per-seat readiness** collapses this to 🟢 READY / 🟡 DEGRADED /
  🔴 BROKEN / ⚪ OFF plus a single next action (networking §12.5).
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
| B2 | **Distance + bearing columns** | **Az DX = bearing to DX** (done as `az`); distance = workability; drives click-to-point (§2.10) | G | **H** |
| B2b | **Az ant + Az DX on rotator bands** | live antenna heading + bearing-to-DX; **Az ant uses different font while rotating** | W | **H** |
| B3 | Core columns | score/call/grid/band/inst/SNR/age + dF, mode, status | both | H |
| B4 | Configurable columns (show/hide/reorder) | Phase-2 operator polish | G | L |

**C. Scoring / "wanted" (the contest engine)**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| C1 | Score = weighted factors, **explainable breakdown** | visible per-row "why" | W | H |
| C2 | Factors: new-mult (grid×band) / points / SNR / CQ / rover (+ **cross_band** → C7) | | W | H |
| C3 | Weights vary by band condition (open/marginal/dead) | server flag today; UI selector later | W | M |
| C4 | **N1MM is mult authority; roster self-computes prospective + reconciles** | no LoTW/eQSL confirmation | D | **H** |
| C5 | Run vs S&P **advisory** / needed>dupe / give-up | run = recommend seat WSJT-X UI, not Call CQ (§2.12) | W | M |
| C6 | Geometry-aware reachability | only rank stations the antenna can hear/point at (§3.14) | W | M |
| C7 | **Cross-band opportunity factor + evidence** | rank boost is secondary; primary is **operator-visible evidence** so they can assess other-band contact ability and decide whether to act (QSY / prioritize). Evidence: current log/decodes + **previous contest logs** (same call, other bands not yet worked this contest). See §2.9 | W | **H** |

**D. Grid & data integrity**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| D1 | **Authoritative call→grid memory** (accumulate across all decodes) | load-bearing — mult = grid×band; WSJT-X often lacks grid in a decode | D/G | **H** |
| D2 | **Supply remembered grid to WSJT-X for logging** | correct grid in log → correct N1MM mult (mechanism TBD, Open questions) | D | **H** |
| D3 | Dupe shown greyed (with context) vs hidden | GT keeps B4 rows visible; WIMS excludes — reconsider | G | M |

**E. Filtering & subscription**

| # | Feature | Contest form | Src | Prio |
|---|---------|--------------|-----|------|
| E1 | **Band / instance filter** | client filter within feed | G | **H** |
| E1b | **Subscribe to station/band → roster population** | operator chooses which fleet seats/bands feed *their* call roster; unsubscribed bands do not appear there (§2.11) | W | **H** |
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
| G1 | **Single-click to work** a station → Reply via arbiter + control claim | S&P + **tailend** — echo retained decode (CQ/QRZ/73/…); GT2 pattern (§2.12) | both | **H** |
| G2 | Per-instance halt, global panic-stop | safety; Halt works for S&P and observed run | W | H |
| G3 | Right-click context menu / multiple roster windows | Phase-2 | G | L |
| G4 | **Closing free text / QSY on final 73** | operator option to send e.g. `QSY 432` via Free Text when completing a contact; **operator assesses C7 evidence then chooses** accept / other band / skip — never auto-applied; §2.8 / §2.9 | W | **H** |
| G5 | **Click-to-point rotator from roster Az DX** | command K3NG (Yaesu protocol) to bearing-to-DX; show **Az ant** + **Az DX**; Az ant font changes while rotating; §2.10 | W | **H** |
| G6 | **Run vs S&P boundary (§2.12)** | S&P = WIMS Reply; run/CQ + autorespond = WSJT-X UI; console shows mode + calling-us; no product Call-CQ | W | **H** |

**Top of the list (high-prio):** A1/A2/A3 (all-stations + per-station status + calling-us), B1/B2/B2b
(column sort + Az ant/Az DX), D1/D2 (grid memory + grid-for-logging), **E1b** (subscribe → roster),
F1 (new-mult alert), G1 (click-to-work **S&P + tailend**), **G6** / **§2.12** (run vs S&P/tailend), **G5** /
**§2.10** (rotator status + fonts + click-to-point), **C7** / **§2.9** (cross-band evidence +
operator decision), **G4** (QSY free text on complete).
View controls (B1, E1) are cheap (client-side over the existing feed); A1/A2 need the decode
pipeline to **retain non-CQ / 73 decodes with a status** (needed for tailend); G1 is the
S&P/tailend Reply path (not Call CQ); G4 needs Free Text encode + verified WSJT-X behavior; C7 must
ship **evidence**, not only a score number; G5 needs Yaesu/K3NG backend + `az_ant` /
`rotator_moving` on the contract; E1b is the multi-op roster scope; G6 is design + UI honesty
(mode banner, Tailend label, no fake Call CQ).

Additional roster detail from the operator notes: color-code rows by **who owns the station
locally** (fleet-owned / this-operator-controlled vs. everyone else) so an operator sees at a
glance which decodes are on instances they cover — ties to the band-focus model (§2.7) and the
control claim (§4.5).

---

### 2.7 Multi-operator console (identity, band focus, coordination)

WIMS supports **several human operators at once**, each in their own browser window, sharing one
site server. This is the multi-console side of §4.5.

- **Operator identity, no security.** Each operator identifies by **callsign + name** — there is
  **no login/password**. The fleet is a known, cooperative team, so WIMS **assumes good will**;
  identity is for coordination and attribution, not access control.
- **Band / station subscription (choose what you cover).** Each operator **subscribes** to the
  fleet station(s)/band(s) they elect to cover — full rules in **§2.11**. **That subscription is
  what populates their call roster** with decodes from those bands. Unsubscribed bands do not
  clutter their roster; Status/fleet views can still show coverage gaps. **Bands with no
  subscriber are highlighted** so empty seats are obvious.
- **In-console chat.** A **chat window** lets operators coordinate band selection and general
  organization — moving today's out-of-band vehicle chat into the console.
- **Operator-status widget** — one entry per open operator window: **callsign + name**, **bands
  subscribed / claimed**, **count of needed stations** in that operator's roster, and **time since
  last action**. Needed-by-band is dimmed when no operator has subscribed, and flagged when a band
  has needed stations but no operator activity.

### 2.8 Closing free text / QSY on completed contact

**Need.** When WSJT-X finishes a contact it normally sends a final **73 / RR73**. In multi-band VHF
contesting the operator often wants that closing TX to carry a short operational hint for the other
station — classic example: **`QSY 432`** (or `QSY 222`, `QSY 50`, …) so they know where to find us
next. That is free-text territory, not a standard exchange field.

**What WIMS can do** (human-in-the-loop; never unattended free-text TX):

1. **Wire Free Text UDP** (§1.1 / §3.2) — encode Free Text, send to the instance that holds the
   QSO, confirm live that WSJT-X actually queues/transmits free text (character limit, whether it
   replaces Tx6/73 or requires free-text mode, when mid-cycle is too late). This is prerequisite;
   Free Text is already on the §3.2 remaining list.
2. **Operator option at work-time or mid-QSO** — when starting a contact (click-to-work) or while
   one is in progress, offer:
   - **Presets** for our fleet bands (`QSY 50`, `QSY 144`, `QSY 222`, `QSY 432`, microwave as
     equipped) constrained to FT8 free-text length;
   - **Free-type** short text with validation (too long / illegal chars rejected before send);
   - **Skip** (default) → normal WSJT-X 73/RR73 path.
3. **QSY suggestions are assess-then-decide, not auto** — WIMS may *propose* a closing free-text
   (e.g. QSY to a needed band) from the same evidence as **C7 / §2.9**, but the **operator must
   assess other-band contact ability and explicitly choose** accept suggestion / pick another band
   / skip. Default remains plain 73. No silent or one-shot auto-QSY. Detail of the assessment UI
   is §2.9.
4. **Timing** — inject Free Text for the **final TX** of the contact (closing message), not as a
   substitute for the whole exchange. Exact WSJT-X semantics are an open verification item (§1.1):
   does Free Text override the next scheduled message, force free-text mode until cleared, and
   does QSO Logged still fire after a free-text 73-equivalent? Measure against a real instance.
5. **Safety / claims** — Free Text is a TX-affecting command: claim-gated like Reply (§3.4 / §4.5),
   subject to arbiter grant and fail-safe-to-RX. No free text while the instance is halted or the
   band is red on readiness.
6. **Cross-console** — optional note in the decision log / chat that we asked the station to QSY
   to band X (helps the other seat watch for them).

**Out of scope for v1:** inventing a new WSJT-X protocol message; auto-sending QSY without an
operator action; multi-cycle free-text conversations.

### 2.9 Cross-band opportunity — evidence for operator assessment

**Need.** Ranking a station higher because they *might* be workable on another band is only useful
if the operator can **judge that claim**. Prior-contest activity does not prove they still have
that band, the path is open now, or our seat is free — the operator decides whether the
cross-band opportunity is real and whether to use a QSY suggestion (§2.8).

**Principle:** WIMS **surfaces evidence and ranks with an explainable factor**; the operator
**assesses other-band contact ability** and **decides** whether to prioritize the station and/or
send a closing QSY. Score boost alone is not enough — **evidence must be visible**.

**Evidence WIMS should show per DX call** (roster expand / work-dialog panel; durable on the
state contract so the console can render it):

| Field | Why the operator cares |
|-------|------------------------|
| **Other fleet bands still needed** this contest (band × grid if known) | Is there score left on another band? |
| **Evidence per other band** | *How* do we think they can do that band? |
| — worked / heard **this contest** on that band | Strong: active now |
| — worked on that band in a **prior contest** (which contest / year) | Weaker: history only |
| — grid then vs grid now (rover?) | History may not apply |
| **Our seat readiness** on those bands (ready / degraded / no op / busy) | Can *we* take them if they QSY? |
| **Suggested QSY band(s)** ranked by need + evidence strength + seat readiness | Starting point for the dialog — not a command |

Optional later: distance/bearing vs typical reach on the higher band, current condition flag on the
other band (open/marginal/dead) — helps “can they make it *now*?” judgment.

**Operator workflow**

1. **See** cross-band evidence on the roster (badge/column or expand) and full detail when working
   or completing a station.
2. **Assess** — e.g. “they did 432 last June and we still need them, but 432 is dead and our Roy
   seat is empty → skip QSY” or “heard them on 222 this hour, needed mult → QSY 222.”
3. **Decide** explicitly:
   - accept a suggested closing free text (`QSY 432`), or
   - choose a different band / custom free text, or
   - skip (plain 73) and/or ignore the score boost for action.
4. WIMS never treats “suggestion accepted” as default; **skip is the safe default**.

**Scoring (`cross_band` factor)** remains a weighted rank input so high-opportunity stations float
up for *attention*, with a breakdown the operator can inspect (same facts as the panel). Ranking
does **not** force QSY or work order — click-to-work and free-text stay human-initiated.

**Out of scope:** auto-QSY; assuming prior-contest presence means they have the band this weekend
without showing that assumption; hiding evidence behind a single score number.

### 2.10 Rotator status & control (Yaesu / K3NG) ↔ roster Az ant / Az DX

**Need.** Multi-band VHF means several antennas, some on **remotely operated rotators** (K3NG /
Yaesu over the LAN). On those bands the operator must see **both** headings side by side on the
call roster and tell at a glance when the antenna is **moving**.

**Roster columns (rotator-mapped bands only for Az ant)**

| Column | Value | Notes |
|--------|--------|--------|
| **Az ant** | Live **antenna azimuth** from the remote rotator (K3NG read-back) | Shown only when the band/instance has a WIMS-controlled (or status-reporting) remote rotator; fixed beams show `—` |
| **Az DX** | Great-circle bearing **from us to the other station** (`de_grid` → DX grid) | Always when grid known; this is the click-to-point target. Already partially built as `az` |

**Font cue while rotating.** When the rotator reports **actively rotating / slewing**
(`rotator_moving` / not yet settled on target), **Az ant is drawn in a different font** than when
settled (e.g. *italic* while moving, upright when still — exact face is Phase-2; the contract
exposes a boolean so the console can style without re-deriving motion). Settled antenna az uses
the normal roster font. Do **not** rely on color alone (color is already busy for need/dupe/TX).

Optional later: **Δaz** (shortest-arc |Az ant − Az DX|) or in-beam cue for “already pointed.”

**Status panel** — state contract key e.g. `rotators` (and mirrored onto roster rows):

| Shown | Meaning |
|-------|---------|
| Rotator / antenna id | Which physical rotator |
| **Current az** (= Az ant) | Where the antenna is now |
| Target az | Last commanded heading |
| Moving / settled | Drives **Az ant font** on the roster |
| Link health | Serial/TCP to controller up? |
| Mapped band(s) / instances | Who uses this rotator |

**Control (command)** — human-initiated only (same philosophy as TX):

1. **Click-to-point** — from a roster row: command the instance’s rotator to that row’s **Az DX**.
   Soft az limits from Instance Profile (§3.14) enforced; reject/clip with reason. While the move
   runs, **Az ant** updates and uses the rotating font until settled.
2. **Manual point** — enter degrees or a grid (→ bearing); stop; park.
3. **Optional later:** auto-point on click-to-work (config; default off so pointing stays explicit).
4. Serialize commands per rotator; claim-gated if multi-console (§4.5) so two ops don’t fight the
   same mast. Subscription (§2.11) alone does not grant move rights — claim does.

**Backend (`Rotator` interface, §3.8 first impl = Yaesu/K3NG):**

- Connect to each controller (USB-serial or TCP), poll position, send move/stop.
- Dialect locked to the **deployed K3NG version** (command/response table in config or code
  comments + a live verify on Setup).
- Pluggable: later Green Heron / hamlib without changing roster or API.

**Safety:** never command past soft az limits; stuck-rotator / no-readback → watchdog fault
(§3.9); lost link → show RED on Status, blank or stale Az ant with clear health, no silent
“pointed” assumption.

**Out of scope for v1:** full moon-track EME el control (unless el already on the same K3NG);
third-party rotator apps as co-controllers on the same serial port (one controller-of-record).

### 2.11 Band / station subscription → call roster population

**Need.** A multi-multi fleet produces more decodes than one operator can use. The operator
**subscribes to a station on a band** (a fleet seat / WSJT-X instance or whole band) so that
**only decodes from subscribed bands appear in their call roster**.

**Model**

- **Subscribe** = “put this band’s decodes on *my* Operate roster.” Per-console preference (and
  shown on the multi-op widget §2.7). Multiple operators may subscribe to the same band
  (observe/work coordination); TX/rotator still claim-gated (§4.5).
- **Server** still ingests **all** fleet decodes (one site truth). Subscription is a **view/scope**
  for that operator’s roster (client filter and/or per-session server projection — either is fine
  if the state contract remains clear). Status / fleet / decode-log may remain wider so coverage
  gaps stay visible.
- **Unsubscribe** removes those rows from *that* operator’s roster immediately (age-out rules
  still apply for rows that remain subscribed).
- Default at open: empty subscription or last session’s set (config); never force all bands onto
  one screen without an explicit “subscribe all.”

**Relationship to other controls**

| Action | Effect |
|--------|--------|
| Subscribe band | Decodes from that band appear on **my** call roster |
| Claim control | I may click-to-work / Free Text / click-to-point on that instance |
| Unsubscribe | Roster no longer shows that band for me (others unaffected) |

**Rotator rows under subscription.** When the subscribed band has a remote rotator, roster rows
include **Az ant** + **Az DX** and the rotating-font cue (§2.10). Fixed-beam subscribed bands show
Az DX only.

### 2.12 Run vs S&P — CQ control boundary (protocol-limited)

**Problem.** Contest ops need both **S&P** (answer someone else’s CQ / **tailend** a finished QSO)
and **run** (call CQ and auto-answer callers). Early WIMS sketches assumed the console could choose
run vs S&P and drive both. **WSJT-X’s UDP API does not support run mode** (Call CQ + autorespond
to the pile). Separately, **click-to-work is richer than “CQ only”**: GridTracker2 already starts
TX against non-CQ roster lines by echoing the decode as Reply — useful for **tailending**. This
section is the design resolution for both facts.

#### Protocol facts (locked — §1.1 + WSJT-X 3.0.1 source + GT2)

| Wanted action | UDP support | Practical outcome |
|---------------|-------------|-------------------|
| Start QSO from a **retained decode** (CQ, **73** tailend, …) | **Reply** (msg 4) echoing that decode’s fields | **Click-to-work** (GT2 `initiateQso` pattern) |
| Enable Tx / generate standard **CQ** msgs / Call 1st (run) | **None** | Cannot enter **run** from WIMS |
| One free-text “CQ MYCALL GRID” TX | Free Text + Send (msg 9) | One shot only; **no auto-sequence** after it |
| Autorespond to callers **while we CQ** | WSJT-X internal auto-seq / Call 1st only | **Seat WSJT-X UI**, not WIMS |
| Stop TX mid-cycle or end of period | **Halt Tx** (msg 8) | Works for S&P and observed run |
| Set DX call/grid, generate messages only | **Configure** (msg 15), Generate Messages=true | Fills Tx1–Tx6; **does not** Enable Tx (GT2 secondary action) |

**How Reply actually works** (WSJT-X 3.0.1 `MainWindow::replyToCQ` — *not* the conservative
NetworkMessage.hpp prose):

1. Client sends **Reply** with the **exact** fields of a prior Decode (time, snr, dt, df, mode,
   message text, low-confidence, modifiers). GridTracker2 does this for **any** call-roster row
   that still has a stored `message` from that instance — no local CQ filter.
2. WSJT-X rebuilds the Band Activity line and **finds it** in the decode window (must still be
   on-screen / not cleared). No match → ignore (debug: “decode not found”).
3. If found, WSJT-X runs `processMessage` (same family as a UI double-click). It sets the
   double-click / **Enable Tx** path (`m_bDoubleClicked` + Quick Call → `auto_tx_mode(true)`) when
   the message text:
   - starts with **`CQ ` / `CQDX ` / `QRZ `**, or
   - contains **`73 `** ← **tailend after a completed QSO**, or
   - **Hold Tx Freq** is checked (accepts a broader set of lines).
4. WSJT-X then generates standard messages and (with Quick Call) enables TX and auto-sequences
   **that** QSO — “as if the station was calling CQ” from the operator’s point of view.

So: **NetworkMessage.hpp’s “CQ or QRZ only” is incomplete.** Live behavior also accepts **73**
for auto-TX (tailend), and with Hold Tx Freq can accept more. WIMS should treat Reply as
**“work this retained decode”**, not “CQ filter only.”

**Still not supported over UDP:** starting our own CQ and staying in run to autorespond to the
pile. That remains seat WSJT-X UI.

#### Design decision

1. **S&P + tailend is the first-class WIMS TX path.** Console operator: rank → click roster
   station → claim + arbiter → **Reply** echoing the **retained Decode** for that row (same
   mechanism as GridTracker2 call-roster click). Prefer the best retained line for that call on
   that instance (newest CQ, else newest **73** for tailend, else newest workable decode).
   WSJT-X auto-sequences **that** QSO. Optional Free Text close / QSY on the final cycle (§2.8).
   Human initiates every work; no unattended TX.
2. **Tailend is a product feature, not a side effect.** VHF contest ops often pounce when a needed
   mult finishes with someone else (`… 73`). Roster should keep non-CQ / 73 rows (A1/A2) and allow
   click-to-work on them; UI may label **Tailend** vs **S&P CQ** so the op knows what they’re
   doing. If Reply is rejected (decode aged out of Band Activity), surface a clear error — do not
   silently invent a synthetic CQ line.
3. **Run (CQ + autorespond) is WSJT-X-primary.** To call CQ and answer callers, the operator uses
   the **WSJT-X UI** on the seat PC (or remote desktop / KVM / screen-share **to that seat** —
   not inventing CQ over UDP). Typical seat setup: generate standard messages, Enable Tx, Call 1st
   (or manual double-click on callers) as the local op prefers.
4. **WIMS does not ship a product “Call CQ” control.** Experimental FreeText CQ (`--enable-cq-freetext`)
   may remain as a **lab spike only** (one-shot free text, no autorespond). Default off; never
   presented as run mode; not required for M5/M6.
5. **Configure → Generate Messages** may be used later as a non-TX helper (“load this call into
   WSJT-X without enabling TX”) — secondary to Reply click-to-work; claim-gated if exposed.
6. **WIMS still owns interlock, halt, visibility, and ranking while a seat runs.** Observing a
   local CQ is not “unattended automation by WIMS” — the human at the seat (or RDP session)
   enabled TX. Fail-safe Halt / SSB-CW mute still apply.

#### Two complementary roles per instance

| Role | Who starts RF | CQ / autorespond | WIMS does |
|------|---------------|------------------|-----------|
| **S&P / tailend (WIMS-driven)** | Console click-to-work → Reply on retained decode | N/A (we are not CQing) | Roster (CQ + mid-QSO + 73), rank, Reply, Free Text close, claim, arbiter, halt |
| **Run (WSJT-X-driven)** | Op in WSJT-X: Enable Tx + CQ | **WSJT-X** auto-seq / Call 1st | Observe Status/decodes; **calling-us** alerts; rank callers; Halt / interlock; optional recommend “stop run, S&P/tailend this mult” |
| **Idle / monitor** | Nobody | — | Roster + health only; RX-only (fail-safe) |

An instance may **flip** between roles over the contest (open band → run at seat; dead → WIMS S&P
from console). Role is **not** a WIMS UDP command — it is operational practice + observed state.

#### Observed mode (console honesty)

Infer and show per instance from WSJT-X **Status** (and recent Tx message), e.g.:

- `tx_role`: `idle` | `snp_wims` | `run_local` | `qso` (best-effort labels)
- Signals: `tx_enabled`, `transmitting`, `dx_call`, `tx_message` (CQ-shaped vs directed)

UI rules:

- When `run_local`: banner **“Running CQ in WSJT-X — autorespond is local; WIMS will not Call CQ.”**
  Click-to-work remains available to **interrupt** into S&P/tailend on a high-value station
  (after Halt if needed — exact sequencing is implementation detail, claim-gated).
- When idle/S&P: no Call CQ button; empty-seat help text points at **local WSJT-X or RDP to seat**
  if the op wants to run.
- **Calling-us** rows (A3) stay high priority especially in run — the local auto-seq is answering
  them; WIMS makes sure the console op sees who is in the pile if they are multi-band covering.
- Click-to-work enabled when a **Reply-capable retained decode** exists for that row (CQ/QRZ/73
  preferred; greyed with reason if only a stale mid-exchange line and Hold Tx Freq is not assumed).

#### Multi-op / empty-seat implications

- **Empty seat covered by WIMS console** = **S&P + tailend** product story (M5/M6). That matches
  the protocol. “WIMS runs CQ on empty 222 overnight” is **out of scope** without a human in the
  WSJT-X UI (local or RDP) enabling run — and that human is the operator of record for run TX,
  consistent with **no automated/unattended TX** (§4.2).
- **Local seat op running CQ** + **WIMS console watching** = normal: WIMS is assist + interlock +
  fleet roster; does not fight WSJT-X for CQ generation.
- **Handoff run → S&P:** local op (or RDP) Disable Tx / Halt; console claim; click-to-work.
- **Handoff S&P → run:** finish or Halt the WIMS QSO; op enables CQ in WSJT-X.

#### What we deliberately do *not* do

- UI automation (send keys / click Enable Tx) as a primary design — brittle, OS-specific, fights
  the operator, easy to violate fail-safe assumptions. Not planned.
- Treating FreeText CQ as auto-run.
- Pretending Configure + Generate Messages equals Call CQ or Enable Tx.
- Synthesizing a fake `CQ CALL GRID` decode to force Reply — fragile, fights Band Activity match,
  and mis-logs intent; use the **real** decode (including real **73** lines for tailend).
- Unattended “always CQ when band open” robots.

#### Controllers / modules impact

- **§3.2** — product commands: `reply(instance, decode)` (echo retained Decode like GT2), `halt`,
  Free Text (close/QSY), Replay; optional later `configure` for generate-messages-only. **No**
  `call_cq` in the supported API surface (lab flag only). Retain full decode fields on the roster
  (time/snr/dt/df/mode/message/…) so Reply can match Band Activity.
- **No global TX arm / Enable / Disable (RESOLVED — GT2 workflow).** Operate does **not** have a
  master Enable TX / Disable TX switch. **Human initiation is the roster action itself:** click a
  call-roster **line** (or its Work control) → WIMS sends Reply — same mental model as
  **GridTracker2** (select station → work). No automated/unattended TX: nothing transmits until
  that click. Gates that remain: `--no-tx` read-only, control claim (§4.5), arbiter ≤1 per group
  (§3.4), readiness fail-soft. **`halt` is always available** (panic stop). State block: `enabled` /
  `can_tx` (wired controller) — no `armed` flag.
- **§3.5** — “run vs S&P” is an **advisory recommendation** (conditions open → suggest seat run;
  thin → suggest WIMS S&P/tailend), not an actuator. Give-up still applies to **WIMS-started**
  QSOs. Ranking should value **fresh 73** on needed mults (tailend opportunity), not only CQs.
- **§3.12 / console** — click-to-work when a Reply-capable retained decode is available; show
  S&P vs Tailend affordance; mode banner per § above.
- **Emulator (§5)** — Reply→TX / Halt→RX; add a **73-line** scenario so tailend is exercised, not
  only CQ; optional later: emulate local run Status for UI tests, without inventing a UDP Call CQ.

#### Acceptance (design-level)

- Documented and UI-visible that **run ≠ WIMS UDP**.
- Live S&P: click CQ on roster → WSJT-X sequences QSO (Reply path).
- Live **tailend**: click a station whose last useful line is **73** → WSJT-X enables TX / generates
  msgs toward that call (GT2-equivalent); requires decode still in Band Activity.
- Live run: CQ + answer callers only when Enable Tx / Call 1st done in WSJT-X; WIMS shows
  transmitting + calling-us without having issued a Call CQ.
- FreeText one-shot CQ never required for contest operation.

---

## 3. Specific pieces of the WSJT-X management program

Build and test each module independently against the test bed (§5) before integrating in §4.
*(Implementation status: [wims_status.md](wims_status.md).)*

| # | Module | Responsibility | Inputs | Outputs |
|---|--------|----------------|--------|---------|
| 3.1 | **UDP listener/parser** | Decode WSJT-X (and N1MM) datagrams into typed events; **extract grid** from `CQ CALL GRID` / Tx1 decode text | UDP from all instances | Normalized event stream (incl. grid) |
| 3.2 | **UDP controller/sender** | Product TX path is **S&P + tailend (§2.12):** arbiter grant + retained Decode → `reply(instance, decode)` (GT2 echo of decode fields — CQ/QRZ **or 73**); `halt(instance)`; **Free Text** (closing / QSY — §2.8); Replay. **No supported `call_cq`** — cannot start run/autorespond (lab FreeText-CQ flag only, default off). Claim-gated (§3.4/§4.5) | Commands from arbiter/engine | UDP to WSJT-X |
| 3.3 | **Multi-instance manager** | Track N instances; map **port/ID ↔ band/mode ↔ antenna/direction ↔ rotator**; lifecycle (launch/close incl. warning-window dismissal). Includes a **per-station local agent** — full responsibility matrix **§3.3.1** (setup test, interlock mute, rotator I/O, thumbnails, process health, …). Also a **setup wizard**: collect each **Instance Profile** (§3.14) via a form, auto-discover what it can, **validate** before on-air, verify connectivity to every WSJT-X/N1MM instance, report loss of comms (§Goals) | Heartbeats, profiles, mute/rotator commands | Instance registry, agent reports, mute/rotator actuation, thumbnails, setup/validation status |
| 3.4 | **Interlock / TX arbiter** | Grant one transmitter **per shared-resource group** (transmitter/antenna/PA chain, §3.14) — *not* one global token; different bands/vehicles TX concurrently by design. Within a group: zero overlap, no interleaving, single-holder **by construction**. An `OverlapDetector` independently watches *observed* TX state as defence-in-depth. Enforces SSB/CW priority two ways: a **preventive gate** (won't initiate a WSJT-X TX on a band where an SSB/CW station is keyed — band-by-band per contest rules) and a **fast reactive halt** (audio-gain mute on the WSJT-X host, §1.1, kills emission inside 10 ms for mid-cycle keying, then PTT-down + Halt Tx cleanup). Full design: §3.4.1. **Constraint:** on a WIMS-managed instance, **no second remote app** (GridTracker click-to-work, JTAlert, etc.) may send Reply/Tx — that bypasses the arbiter and can cause overlap (§4.3). **Local WSJT-X UI run/CQ is allowed** (§2.12): the seat operator Enable Tx / Call 1st is attended TX, not a second remote controller; WIMS still observes TX and enforces interlock/Halt/mute. **Console-initiated TX is gated by the control claim (§4.5):** only the claim-holding console may Reply/FreeText; nobody steering and no local Enable Tx → RX-only (fail-safe) | TX requests, instance states, SSB/CW priority, claim state | TX grant/deny, fast-mute command |
| 3.5 | **Decision / recommendation engine** | **Advisory, not autonomous** — ranks & recommends for the WIMS operator, who **initiates every S&P/tailend TX by click-to-work (Reply)**; WIMS never transmits unattended. Suggest next-best **CQ or fresh-73** target, **advisory** run vs S&P (run means “use WSJT-X UI / seat”, not a WIMS actuator — §2.12), needed > dupe, give-up on **WIMS-started** QSOs. Maintains a **`call→current-grid` map** (with staleness) so a **rover** reappearing in a new grid is treated as a fresh QSO + candidate mult, ranked high; mult value is per `grid × band`. The grid map is **authoritative grid memory** (accumulated across *all* decodes, GridTracker-style but better-retained) — load-bearing because mult = grid×band and WSJT-X often lacks a station's grid in a given decode (e.g. `CALL CALL +08`); WIMS may **supply the remembered grid to WSJT-X for logging** so the QSO records the correct grid → N1MM computes the right mult (mechanism TBD, Open questions). **N1MM is the multiplier authority:** for *logged* QSOs WIMS defers to N1MM's `ismultiplier`; for *prospective* roster candidates (which N1MM can't judge until logged) WIMS self-computes new-mult with the identical `grid×band` rule and continuously **reconciles** to N1MM's verdicts. **No LoTW/eQSL/award confirmation** — that is general-operating chasing (GridTracker), not contest dupe/mult. Ranks the roster by **expected score gain** via a **scoring model** (§3.11) — QSO points + mult value per the contest. **Geometry-aware** (§3.14): only works/ranks stations a given instance's antenna can actually hear — within a fixed beam's sector, or reachable by a re-point inside the soft az limits. The scoring model is **pluggable + explainable** — score = sum of named weighted **factors** (new_mult, points, snr, cq, rover, **cross_band**) with a per-factor **breakdown** the operator sees; strategies swappable by name; **weights vary by band condition** (open/marginal/dead); dupe/non-CQ/unreachable excluded with reason. **`cross_band` (C7 / §2.9):** advisory rank boost when the same call may offer needed contacts on *other* fleet bands — evidence (a) **current contest** log/decodes, (b) **previous contest logs**. Factor is secondary: engine also emits **structured cross-band evidence** on the roster/state contract so the operator can **assess other-band ability and decide** whether to prioritize or send a QSY (§2.8). Score alone must never hide the evidence. Explainable e.g. `cross_band +12 (needed 432; prior Jun on 432)` | Decodes+grid, dupe/mult status, scoring model, instance profiles, **station history (prior contests)** | Ranked + explained targets, **cross-band evidence for operator assessment**, optional QSY *suggestions* (not auto) |
| 3.6 | **Logger interface** (`LogSource` backend; **N1MM = first impl**) | Abstract behind a small **backend interface** so other loggers (DXLog.net, Log4OM, N3FJP, WSJT-X-native…) plug in later — the engine depends only on the normalized `LoggedQso` + interface, never on N1MM specifics. **Minimal portable contract** (because WIMS self-computes dupe/mult): `seed()` snapshot + `live_events()` add/update/delete stream + `resync()`; optional `mult/points` if the backend supplies it (N1MM does, others may not). **No dedicated WIMS N1MM** — since all contest N1MMs are networked and share one merged log, the **server reads from *any* designated networked N1MM** (e.g. the SSB/CW position's). The logger-of-record invariant (one N1MM *ingests* each WSJT-X stream) is independent of which N1MM WIMS *reads*. **N1MM impl:** seed by reading a `DXLOG` `.s3db` read-only, live via `<contactinfo>` broadcasts (12060) from any N1MM, dedup by `ID`. Maintain log copy keyed on `(call, band, grid)`; self-compute dupe + new-mult (grid×band). Logging path stays WSJT-X→logger; WIMS reads, never double-logs; grid from WSJT-X decode. **Station history for C7:** optionally seed a lightweight `call → {bands seen/worked}` map from **prior contest** `DXLOG` rows (multi-contest `.s3db` already listed on Setup) without treating them as this-contest dupes — history only feeds evidence/scoring/QSY suggestions (§2.9), never the live dupe key | seed snapshot, live log events, WSJT-X grid, **optional prior-contest DXLOG** | Log copy, dupe/mult verdicts, export trigger, **station band-history (for operator assessment)** |
| 3.7 | **GridTracker interface** | GridTracker is an **optional, parallel read-only viewer** (multicast subscriber, §4.3) — coexists, not in WIMS's control or logging path. WIMS's own roster (§3.12) supersedes its operating role; GridTracker's residual value is its map/viz + ADIF/log-export integrations. Interface = leave the multicast open for it; optionally feed log export | Log, QSO events | (optional) export to GT |
| 3.8 | **Rotator controller** (`Rotator` backend; **first impl = Yaesu GS-232 dialect via K3NG**; optional later Green Heron / hamlib `rotctld`) | Serialize moves across **N rotators**; one **controller-of-record per rotator** (§4.3) — WIMS owns it, or an external program does, never both. **Status:** poll live az (el if fitted), **moving/settled**, link health → state contract for Status panel + roster **Az ant** / **`rotator_moving`** (font cue) + **Az DX** (§2.10). **Pluggable pointing sources, arbitrated:** (a) **click-to-point from roster Az DX**, (b) **manual az/grid entry**, (c) optional auto-point on click-to-work (config, default off), (d) EME az/el moon-track later (§1.4). **Enforces soft az/el limits (§3.14)**; operator always initiates moves (no unattended spinning). Host agent may own serial if server is remote | Target az/el, antenna sel, profile limits, operator points, K3NG link | Rotator commands, live position + moving flag |
| 3.9 | **Safety / watchdog** | Heartbeats, runaway detector, sanity limits, fail-safe (TX off). Detects faults by comparing live behavior to each instance's **fault baselines (§3.14)** (silence, freq drift, stuck rotator, PTT-duty, comm-loss). On any fault, trigger the §3.4 fast mute on every host before slower Halt Tx/PTT-down | All module health, instance baselines | Alerts, kill signals, fast-mute trigger |
| 3.10 | **State store / logger** | Single source of truth + audit log of every decision; internal log copy + roster keyed on **`(call, band, grid)`** so rovers aren't collapsed into dupes. **Persistence: own `wims.db` (SQLite, stdlib, WAL)** for queryable state (indexed dupe/mult lookups) + **append-only JSONL** for the raw event/decision stream (replay/audit). SQLite is the derived view, rebuildable from JSONL + N1MM seed. WIMS writes only `wims.db`; never N1MM's `.s3db` | All events | Persisted state, logs |
| 3.11 | **Config** | Per-instance **Instance Profile** (§3.14), strategy/parameter selection, antenna↔rotator map, and the **per-contest scoring model** feeding §3.5 — selects the scoring strategy by name + the per-condition weight sets | Config files / setup form | Runtime config |
| 3.12 | **Server API / integration hub** (the **server↔console boundary**, §4.5) | The unicast API between the **site server** and **operator consoles** (local or remote): serve live state + accept commands — **band/station subscription** (§2.11 → which decodes fill *this* console’s call roster), **call-roster feed + click-to-work** (→ Reply via §3.2, claim-gated), **click-to-point** (→ rotator §3.8), and **control-claim / instant takeover** (§4.5). Roster rows carry **Az DX**, and **Az ant + rotator_moving** when a remote rotator is mapped. Also **re-publish WIMS's normalized/enriched event stream** (decodes + grid + dupe/mult + priority) so other apps consume WIMS's annotated feed — integration hub, not a closed monolith. Stdlib HTTP + SSE serving the JSON state contract (`state.py`) → static dashboard | State store, claim state, **per-console subscriptions** | Feed to consoles §2, roster/point/claim/subscribe actions, published event feed |
| 3.13 | **Override interface** | Let the SSB/CW op or 2nd op supervise/override. The **SSB/CW op's small client app** (§Goals) = a lightweight **console** on the SSB/CW main screen showing WIMS activity on their band (reads the **existing SSB/CW N1MM**, no extra logger). Their **agent** detects keying — **PTT read as the USB-serial CTS line** (§3.4.1 Sensor) — and raises the SSB/CW-priority signal → §3.4.1 fast inhibit, **direct peer-to-peer** (§4.5) | Operator input, priority requests | Commands to arbiter, priority signal |
| 3.15 | **Network discovery & diagnostics** | Be the **protocol-aware network tool so the operator never opens Wireshark**. Passively enumerate live nodes from the multicast WIMS already joins (WSJT-X instances by id/host/group/port/version, N1MM sources, GridTracker); **register N1MM presence from *any* broadcast** (`<RadioInfo>`/`<AppInfo>` beacons, not just `<contactinfo>`, so the link is verifiable at setup with no QSO — capturing StationName + `mycall` + last-seen). Optional active probes (host ping, N1MM:12060, rotator/CAT reachability). **Diff observed vs the declared Instance Profiles (§3.14)** and name every discrepancy. Feeds the §2.5 topology map / health / Wireshark-lite views and the readiness gate | All UDP, profiles, probe results | Live topology, health, discrepancy list |

### 3.3.1 Seat agent — per-station local process

**One agent runs on each radio station PC** (Trailer 50/144 seat, Roy 222, Roy 432, Chip µwave,
SSB/CW seats as equipped). The **site server** is central (roster, scoring, claims, N1MM log
copy); the **agent** owns everything that must be **local to the host** — hardware I/O, 10 ms
safety path, app config on that disk, and anything that should keep working if the console or
server is briefly unreachable.

**Today (coded):** config/setup audit + report to server + local UI + site-server discovery.
**Designed, not coded:** interlock mute, rotator, thumbnails, process control — see matrix.

| Function | Why on the agent (not only the server) | Status |
|----------|----------------------------------------|--------|
| **Setup / config test** | Read WSJT-X `.ini` and N1MM install on *this* host; flag blank Outgoing interface, loopback UDP, N1MM broadcast target, process running. Local UI `:8790` + `POST /api/agents/report` to Status/Setup | **Built** (config/monitor slice) |
| **Site-server discovery** | Hear plane-E presence; show clickable Operate/Status/Setup URLs so the seat op need not memorize the server IP | **Built** |
| **Continuous health report** | Heartbeat of seat readiness to the site server (severity, age, plain-language fault) | **Built** (daemon mode) |
| **SSB/CW interlock — sensor** | On SSB/CW seats: sense PTT (USB-serial **CTS** preferred) and announce key-down/up **peer-to-peer** on the LAN (§3.4.1). Server is **not** in this path | Designed |
| **SSB/CW interlock — actuator** | On WSJT-X seats: receive same-band key-down → **fast TX-audio mute** (10 ms path) + cleanup Halt Tx/PTT. Must run on the host that owns the audio device | Designed |
| **Preventive gate assist** | Report local TX/PTT state so the server arbiter can refuse starting a WSJT-X TX while SSB/CW is keyed (non-time-critical) | Designed |
| **Rotator status & control** | Own serial/TCP to **K3NG (Yaesu protocol)** on this seat; poll **Az ant** / moving; execute click-to-point / stop / park from server commands (§2.10 / §3.8). Server never needs the COM port | Designed |
| **Soft az limits enforcement** | Apply Instance Profile limits at the edge before sending GS-232 move | Designed |
| **WSJT-X / N1MM process lifecycle** | Optional seat-pack: start/stop/restart apps, dismiss N1MM warning windows; guided bring-up (networking §12) | Partial (Windows seat scripts); wizard apply TBD |
| **Waterfall / window thumbnail** | Screen-grab WSJT-X window for §2.5 confidence tiles (capture must be local) | Designed |
| **Instance Profile local apply** | Write/verify UDP group, port, Outgoing interface, rig-name from contest profile | Designed (verify exists; apply TBD) |
| **Local readiness 🟢/🔴** | Collapse seat checks to one next action for a tired op (networking §12) | Designed |
| **Unicast multicast fallback** | If a seat cannot join fleet multicast, optional agent relay (rare; not required on plain L2) | Designed fallback |
| **Remote-desktop launch hint** | Expose host RustDesk/AnyDesk id for one-click from console (§2.5) | Designed (profile field) |
| **Watchdog local fail-safe** | On comm loss to server or stuck-TX baseline: mute TX / stop rotator command stream | Designed (§3.9) |

**What the agent does *not* do**

- **Does not** own the multi-band call roster, scoring, or N1MM master log copy (site server).
- **Does not** initiate contest TX unattended — console click-to-work still goes server →
  claim/arbiter → UDP Reply; agent may later host a local command relay but policy stays server-side.
- **Does not** replace N1MM or WSJT-X; it audits and assists them.
- **Does not** put the 10 ms mute path through the site server (agent↔agent only for that loop).

**Split with site server**

```
  Seat PC                              Site server
  ────────                             ───────────
  agent: setup test, mute, rotator  ↔  roster, score, claims, log
  WSJT-X, N1MM, K3NG serial            SSE consoles, multi-op subscribe
```

Operator at the seat uses **local agent UI** for “is *this* PC right?”; operator at the console
uses **WIMS Operate** for the fleet. Same agent binary/roles compose (WSJT-X seat vs SSB/CW seat
enable different modules from the matrix).

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
  group/port** (standardize on multicast, §4.3); **UDP outgoing interface = contest LAN NIC**
  (required — blank/`@Invalid`/loopback is setup **error**, §1.1); **reachability** = LAN vs
  remote-over-tunnel (host-agent relay, §4.3); host **remote-desktop ID/address** (RustDesk, §2.5);
  the instance's **`logger_of_record`** = `local-n1mm` | `wims-n1mm` (which single N1MM logs this
  instance, §4.3 invariant); whether an operator **GridTracker** subscribes (read-only viewer —
  never a TX controller on a managed instance).
- **Operating** — band; mode(s) + submode/**period length** (FT8 15 s, MSK144 15 s, Q65
  15/30/60/120 s — drives interlock windows & fault timeouts); dial freq; **RX-only vs
  TX-capable**; role (run / S&P / monitor); priority weight.
- **Radio / TX path** — rig model; **CAT path** (middleware enum + endpoints — not “COM only”);
  **PTT method** (CAT / VOX / RTS / DTR — affects halt behavior); TX audio device; **fast-mute
  mechanism** (volume API / virtual cable / analog-GPIO pin, §1.1); PA/amp id + power.
  - CAT is **seat-local**, not a WIMS plane: WIMS never opens the radio COM port or speaks CI-V /
    Hamlib to the rig. It only drives WSJT-X over UDP (Reply / Halt). See
    **[wims_networking.md](wims_networking.md) §3.2**.
  - **Preferred Icom USB seat:** **wfview** owns USB COM; WSJT-X = Hamlib NET
    `127.0.0.1:4533` (RigCtld **must** be enabled); N1MM = TCP to wfview for frequency only —
    never N1MM **Load WSJT/JTDX** / DX Lab Suite Commander proxy on managed seats. Full recipe:
    **[wims_networking.md](wims_networking.md) §3.3**.
  - Profile `cat_path` examples: `direct-com` · `wfview-rigctld` · `win4icom` · `win4yaesu` ·
    `lp-bridge` · `flex-smartsdr-cat` · `vspe-pair` · `other-middleware`. Record host endpoints
    (e.g. rigctld port, N1MM TCP port) so clones and readiness checks can verify LISTENING.
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
1. Ingest decodes/status from all instances (§3.1), extracting grid from grid-bearing decodes;
   observe `tx_enabled` / `tx_message` for run-vs-S&P **display** (§2.12).
2. Look up dupe/new-mult status from WIMS's internal log copy (fed by N1MM `contactinfo`, §3.6,
   calibrated by `ismultiplier`); decision engine (§3.5) **ranks** CQ targets and may **advise**
   run vs S&P using that status, the `call→grid` map, and strategy params (§3.11) — it does not
   start CQ.
3. **On human click-to-work (S&P):** engine/console requests TX from the arbiter (§3.4) for a
   CQ/QRZ decode.
4. Arbiter grants **one** transmitter per group, enforcing no overlap / no interleave; controller
   (§3.2) issues **Reply** (or Free Text close / Halt) — never Call CQ.
5. **Run path (parallel, not WIMS-initiated):** local/RDP op enables CQ in WSJT-X; WIMS only
   observes, interlocks, and can Halt.
6. Watchdog (§3.9) supervises everything; can halt all TX.
7. Push state to dashboard (§3.12); accept overrides (§3.13).
8. Log every decision (§3.10).

### 4.2 Operating modes (per instance — always a human operator, never unattended)
- **Local-operated** — a local op drives that band's WSJT-X directly (**including run/CQ +
  autorespond**); WIMS observes + assists (visibility, dupe/mult, calling-us, interlock), and may
  Halt for safety, but does **not** invent CQ over UDP (§2.12).
- **WIMS-operated (S&P + tailend)** — the WIMS **console operator** works the band via the call
  roster + **click-to-work → Reply** on a retained decode (CQ or **73** tailend, GT2-style; covers
  an empty seat); WIMS **ranks/recommends**, the operator **clicks every work**. One console op can
  cover several bands. **Run on an empty seat requires a human in the WSJT-X UI** (local or
  RDP/KVM to that seat) — not a WIMS autodialer.
- **Handoff** — transfer of an instance between operators (local⇄WIMS, and **WIMS console⇄WIMS
  console**) via the **soft control claim (§4.5)**: claiming is implicit (act on the instance) and
  takeover is **instant, no release ceremony** (a one-click confirm only if the current controller
  is mid-cycle); claims auto-expire on inactivity. Invariant: **at most one controller per instance
  at any instant** (server-serialized); nobody steering **and** no local Enable Tx → instance is
  RX-only (fail-safe). Local run with Enable Tx still has a human operator at the seat UI.
- *No automated/unattended TX.* WIMS is a remote operating position, not an autobot. Local CQ with
  Enable Tx is attended by the seat/RDP operator, not by WIMS automation.

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
  - *Mechanism:* segregate WSJT-X UDP streams (**multicast group/port per band** — see
    [wims_networking.md](wims_networking.md)) so each N1MM ingests only its assigned instances;
    WIMS subscribes to **all** (it reads, never logs, so cannot double-log). N1MM supports two
    independent WSJT-X readers (`WSJTJTDXUDPIP/IP2`, `…Port/Port2`,
    `EnableWSJTJTDXUDPReader/Reader2`) for source-specific addressing; many instances may share
    one reader if they share a stream and have distinct UDP ids. All N1MMs network into one
    merged log; WIMS reads any designated networked N1MM's `DXLOG` plus live `<contactinfo>`.
    Declared per-instance in the Instance Profile (§3.14, `logger_of_record`), enforced by
    exactly-one-logger setup validation.
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
  vendors sit behind normalized backend interfaces (`LogSource` §3.6, `Rotator` §3.8 — Yaesu/K3NG
  first, rig CAT via hamlib) so new ones plug in without touching the engine.
- **Standardize WSJT-X on multicast** — on the LAN, every consumer (N1MM, GridTracker, WIMS)
  **joins the group as a parallel subscriber**; nobody relays. This removes the GridTracker relay
  loop and its §1.2 forward/grid-drop quirks entirely. *GridTracker stays a read-only band viewer;
  it must NOT be used to initiate TX on a WIMS-managed instance — that bypasses the arbiter (§3.4).
  WIMS's own call roster (§Goals/§3.12) provides click-to-work through the interlock, so GridTracker
  is optional, not in the control path.*
- Config-driven so a contest can be set up without code changes.
- Screen-share path to manage the remote station.

> **Milestones** (M1–M7) and per-module build status live in
> **[wims_status.md](wims_status.md)**. Fleet UDP/N1MM/GridTracker networking map:
> **[wims_networking.md](wims_networking.md)**.

---

## 4.5 Client/server architecture & control claims

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

**Claims scope control, not view.** Every console *views* all instances (open monitoring); the
control claim only decides **who may TX which instance** — so two consoles can split the fleet (A
claims instances 1–3, B claims 4–6), or one takes all, or they rebalance live. Per-instance
granularity is what enables the split.

**Remote operation without forwarding multicast.** The server is the only multicast subscriber; a
remote console receives *normalized* state + thumbnails and sends *commands* — all unicast over a
TLS WebSocket / Tailscale link. So **Tailscale being unicast-only is a non-issue** — multicast
never crosses the internet. Latency is irrelevant for digital (15 s FT8 cycles ≫ 50–100 ms RTT),
and the safety-critical **10 ms SSB/CW mute stays in the host agent at the site**, never on the
remote operator's path.

**Control model — soft claims, not hard locks (RESOLVED).** The mechanism is a per-**instance** (or
resource group) **operator claim** the single authoritative server holds — but its *policy* is
built for a **known, cooperative fleet** (§2.7, "assume good will"), not for defending against
hostile takeover. The §3.4 arbiter already makes **TX overlap impossible by construction**, so the
claim governs only *operator* conflict (two people steering one instance), never RF safety — and is
therefore tuned for **minimum friction**:
- **Claiming is implicit and instant.** Acting on an instance (click-to-work) makes you its
  **current controller**, shown fleet-wide (console + operator-status widget, §2.7) with your
  callsign and last-action time. No explicit "acquire" step, no release ceremony.
- **Any operator can take over any instance, immediately** — this is the good-will model from the
  operator notes. No cooperation from the previous controller needed and **no countdown**. Guard
  rail: if the current controller acted **within the last TX cycle**, the taker gets a one-click
  *"‹call› is actively working this — take over?"* confirm so mid-QSO snatching is deliberate;
  otherwise takeover is silent. This removes the "operator took a break and forgot to release" lock
  a hard lease would risk.
- **Claims auto-expire on inactivity.** A controller idle past a TTL (heartbeat lost, sleep, link
  drop) silently stops being shown as controller; the instance is then **unclaimed** and any
  console picks it up with no prompt.
- **Server serializes all commands** → **no split-brain.** Control flows only through the one
  server, applied in arrival order, so even simultaneous clicks resolve to a single well-defined TX
  and a zombie console's stale commands can't produce a second transmitter.

**Fail-safe to RX (unchanged).** TX only ever happens on an explicit human click, so an instance
**nobody is steering simply does not transmit (drops to RX)** — "operator vanished, nobody grabbed
control" is *safe*, not dangerous. The safety guarantee lives in **"no automated TX" + the §3.4
arbiter**, independent of who holds the (soft) claim; the claim is only ever about **continuity and
clarity**, never overlap — overlap/runaway are impossible by construction (no operator → no TX).

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
  one per band/mode. Contest profile loaded (expected fleet — [wims_networking.md §12](wims_networking.md#12-resilience--guided-setup-tired-operators-restarts)).
- **Trigger:** Operator requests "bring up / arm" (or seat shortcut after reboot).
- **Walkthrough:** WIMS confirms each **expected** instance's heartbeat, checks N1MM presence
  (plane B), GridTracker optional, and the rotator are reachable, and verifies station readiness
  (PA, 120 V line power, SDR up). Each **seat** turns 🟢/🟡/🔴 on the dashboard with a
  **named fix** when not green; wrangler board shows the same state.
- **Expected behavior:** TX/click-to-work stays blocked for seats that fail *required* checks;
  every failing item is named in plain language, not just flagged. Dress rehearsal: cold-start
  time-to-green with a non-author operator (networking §12.12).
- **Drives / exercises:** §3.3 multi-instance manager, §3.9 safety/watchdog, §2.2 readiness panel,
  §3.15 expected-vs-actual, networking §12; go/no-go gate for M1 and M5.
- **Open questions raised:** Which checks are mandatory vs. advisory? How is "PA ready" actually
  sensed? Hard-block TX when N1MM missing but WSJT-X alive?
- **Mode:** setup.

### Setup / installation scenarios (per-role onboarding)

WIMS installs from **one package** and is told its **role** for that PC (§4.5 packaging). The
install/setup wizard (§3.3) collects role + bands, **reads and verifies the existing WSJT-X / N1MM
config files** against what the operator declared, and configures the interlock interfaces
(§3.4.1). These run before any operating scenario and feed the readiness gate (S1).

#### I1 — Install on a WSJT-X station
- **Context / preconditions:** A radio-host PC already running **N1MM + one or more WSJT-X
  instances** (and maybe SDR software) for one or more digital bands. Each WSJT-X launches with an
  informative **rig-name** (`6M-TVStation`, `2M-WEST`, …), one per band.
- **Trigger:** Operator installs WIMS and runs setup; selects role = **WSJT-X station** (a §4.5
  *agent*, optionally + console).
- **Walkthrough:** WIMS asks which **bands** this station covers. It **reads the WSJT-X and N1MM
  config files** (`wsjtx_config` + N1MM settings), enumerates the WSJT-X instances by rig-name, maps
  **rig-name → band**, and **verifies the config matches** what the operator declared
  (rig-name↔band, UDP multicast group/port, **Outgoing interface = contest LAN NIC**, unique `id`,
  N1MM WSJT-X-reader settings) — flagging mismatches. Blank/`@Invalid`/loopback interface or
  `UDPServer=127.0.0.1` in fleet mode is a **hard fail** with a plain-language fix (networking §4 /
  §12). It then **configures the audio-path actuator** (§3.4.1): the OS-specific interface that
  ramps TX audio to 0 on an interlock trigger, confirming a fast-mute mechanism exists for every
  TX-capable instance.
- **Expected behavior:** Every declared band has a matching, validated WSJT-X instance + N1MM
  reader; **UDP iface + server pass `wsjtx_config` fleet rules**; the audio-path mute is wired and
  **test-fires**; every discrepancy (missing band, rig-name/band mismatch, port/id collision,
  **unset LAN interface**, no fast-mute path) is **named**, not just flagged. Station shows green
  only when all required checks pass.
- **Drives / exercises:** §3.3 setup wizard, §3.14 Instance Profile, §3.4.1 actuator config,
  `integrations/wsjtx_config` + §3.6 N1MM, §3.15 discovery.
- **Open questions:** config-file locations across WSJT-X versions / per-instance config dirs; how
  the audio-path actuator is chosen (volume API vs analog) per host.
- **Mode:** setup.

#### I2 — Install on an SSB/CW station
- **Context / preconditions:** A PC running **N1MM** (and maybe SDR) for an **SSB/CW** operating
  position on one or more bands. No WSJT-X TX here.
- **Trigger:** Operator installs WIMS and runs setup; selects role = **SSB/CW station** (a §4.5
  *agent* + console).
- **Walkthrough:** WIMS reads which **band(s)** this SSB/CW position operates (from N1MM /
  operator) so it knows which WSJT-X it must interlock — **same band** (§3.4.1). It configures the
  **TX-state sensor** (PTT read as the **USB-serial CTS** line) and the **announcement** of
  key-down / key-up (with band) on the LAN, so WIMS on the WSJT-X PCs can gate/halt. A lightweight
  console shows WIMS activity on this band so the op can wait for an in-progress digital QSO to
  finish.
- **Expected behavior:** Keying the SSB/CW rig is sensed (CTS edge) and announced within budget;
  same-band WSJT-X stations receive it and gate/halt (§3.4.1). The sensor **test-fires during setup
  without requiring an on-air transmission** (keying/loopback test).
- **Drives / exercises:** §3.4.1 sensor + announcement, §3.13 override interface, §3.3 setup, §2.2
  SSB/CW band-activity console.
- **Open questions:** CTS wiring per rig/interface; announcement datagram format + multicast group.
- **Mode:** setup.

#### I3 — Install on the control PC (WIMS server)
- **Context / preconditions:** The PC that will run the **WIMS server** (§4.5) — the single
  multicast consumer, state authority, and only sender of control to WSJT-X. May be a **dedicated**
  box or **stacked** on a PC that is also a WSJT-X or SSB/CW station (roles compose: server + agent
  + console).
- **Trigger:** Operator installs WIMS and runs setup; selects role = **server** (control).
- **Walkthrough:** WIMS comes up as the server, **discovers the fleet** from the multicast (§3.15),
  **seeds the log copy** from a designated N1MM `.s3db` (§3.6), and serves the console (Operate /
  Status). If stacked with a station role on the same PC, it also runs that PC's agent
  (sensor/actuator) locally. It **verifies connectivity** to every declared WSJT-X and N1MM
  instance across the fleet and reports loss of comms.
- **Expected behavior:** One server per site; it sees every expected instance (expected-vs-actual,
  §3.15) and **names** any missing/dead/quiet node; the log seed succeeds; stacked roles run
  side-by-side **without the server entering the §3.4.1 10 ms safety path**.
- **Drives / exercises:** §4.5 server role + role stacking, §3.15 discovery, §3.6 seed, §3.12
  server/console, §3.3 fleet connectivity verification.
- **Open questions:** which N1MM the server reads when stacked vs dedicated; multi-server is out of
  scope (single authoritative server, §4.5).
- **Mode:** setup.

### Scenario backlog (to write)
Candidate situations worth covering — rename, add, or cut freely:
- S1 — Cold start & station readiness check *(example above)*
- S2 — **S&P on an open band** (click CQ targets, work needed, skip dupes) — primary WIMS path
- S2a — **Tailend on 73**: needed mult finishes with someone else (`… 73`); click roster → Reply
  echoes that decode (GT2-equivalent); WSJT-X enables TX toward that call; decode still in Band
  Activity required (§2.12)
- S2b — **Run on an open band (WSJT-X UI)**: seat/RDP Enable Tx + CQ + Call 1st; WIMS shows
  `run_local`, calling-us, interlock; **no** WIMS Call CQ; autorespond stays in WSJT-X (§2.12)
- S3 — Interlock contention: two instances want to TX in the same window
- S4 — Meteor scatter (MSK144): patience and the give-up decision
- S4b — EME: az/el moon-tracking, long periods, scheduling around moonrise/set
- S5 — Rare grid / multiplier appears: priority + **click-to-point** (roster Az → K3NG)
- S5b — **Rover in a new grid**: same call worked earlier reappears from a different grid → WIMS
  self-computes "not a dupe, new mult" from the log copy (§3.6) → ranked high; operator may
  re-point via roster Az; stale-grid handling for grid-less decodes
- S5c — **Rotator status / Yaesu-K3NG**: Az ant + Az DX on roster; Az ant **font changes while
  rotating**; settle restores normal font; soft-limit reject; lost link
- S5d — **Band subscribe → roster**: operator subscribes to 222 only → roster shows 222 decodes;
  subscribe 432 adds those rows; unsubscribe removes them; Status still shows fleet gaps
- S6 — **Run ↔ S&P handoff** as conditions change: local Disable Tx / Halt → console S&P; later
  seat re-enables CQ in WSJT-X; advisory engine may suggest the switch (§2.12 / §3.5) but does not
  actuate CQ
- S6b — **Closing QSY free text**: complete a QSO with operator-chosen `QSY 432` via Free Text
  (§2.8); confirm log still records; other seat sees the station
- S6c — **Cross-band opportunity assess-then-decide**: station needed on 6m; evidence shows
  prior/other-band activity on 432 not yet worked → roster boost + **visible evidence panel**;
  operator assesses ability and **chooses** QSY 432 / other / skip (C7 / §2.9) — not auto-applied
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
- **Control model — leases vs. open good-will control — RESOLVED (hybrid soft claim, §4.5).** The
  hard-lease policy (exclusive lock + forced-takeover countdown) and the operator notes' open model
  (any operator controls any station, no release) conflicted. Resolution: **keep the per-instance
  claim as the mechanism** (single server, TX-gated, fail-safe-to-RX) but make its **policy soft** —
  claiming is implicit on action, any operator takes over instantly (one-click confirm only if the
  current controller is mid-cycle), and claims auto-expire on inactivity. This gives the good-will
  model's zero-friction takeover *and* kills both failure modes: "forgot to release" (auto-expire +
  instant takeover, no lock) and silent double-steering (current controller always shown; server
  serializes commands). RF safety is unaffected — the §3.4 arbiter enforces zero TX overlap
  regardless, so the claim only governs *operator* conflict. Reversible if the team later wants
  stricter locks.
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
- **EME pointing hardware** *(open)* — primary path is Yaesu/K3NG az; elevation + moon-tracking
  only if K3NG build + hardware support el, else separate path (§1.4, §3.8). Resolve before EME
  scenarios.
- **K3NG / Yaesu dialect** — lock the exact command set and serial settings for the **site’s K3NG
  version** (GS-232A vs B, C vs C2, degree formatting). Live verify on Setup before trusting
  click-to-point.
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
- **Free Text closing / QSY mechanics** — exact WSJT-X behavior for Free Text as a substitute or
  companion to final 73/RR73 (character limit, free-text mode sticky?, QSO Logged still fires?).
  Verify against protocol header + live instance before building §2.8 UI (see §1.1).
- **Trigger CQ / run via UDP — RESOLVED (§1.1 / §2.12).** No usable Call CQ or run-autorespond over
  UDP; **click-to-work = Reply** on retained decodes (CQ **and** **73** tailend — GT2 pattern;
  NetworkMessage.hpp CQ-only prose is incomplete vs WSJT-X 3.0.1). Run = WSJT-X UI (local or RDP).
  FreeText one-shot CQ is lab-only, not product.
- **Tailend edge cases** — RR73 vs 73; mid-exchange lines without Hold Tx Freq; decode cleared from
  Band Activity before click; which retained line to prefer when a call has both a fresh CQ and an
  older 73. Live-verify against WSJT-X + GT2 and lock defaults.
- **Run interrupt → S&P** — when instance is `run_local` and console clicks a high-value CQ, exact
  sequence (Halt then Reply same cycle vs next cycle only)? Measure live; keep claim + arbiter
  gates. Prefer fail-safe (no double TX) over winning the current period.
- **Cross-band history source (C7 / §2.9)** — which prior contests/logs feed station band-history
  (only our N1MM multi-contest `.s3db`? ADIF exports? how many years / which contest names)? How
  to keep history from polluting this-contest dupe/mult (strict separation: history → evidence +
  scoring only). Weight of “worked last year on 432” vs “heard this weekend on 432 but not
  worked”. How much detail on the roster row vs expand/work-dialog so assessment is fast under
  contest pace.
