# WIMS Switchboard — concept paper for review

**Status: adopted design direction (2026-07-30) — not yet the current build; still open for
review.** This document describes the re-partitioning of WIMS (WSJT-X Instance Management
System) that the project is now building toward, and is written to stand alone, for review by
experienced multi-multi VHF operators who have **not** read the rest of the WIMS design tree.
Comments, objections, and "that will break because…" war stories are exactly what we want —
the open questions in §11 are live.

The current, implemented WIMS design lives in [wims_design.md](wims_design.md) and
[wims_networking.md](wims_networking.md); differences from it are called out in §8.

---

## 1. The operating problem

A fixed, unlimited multi-multi VHF entry (ARRL June/September VHF pattern): several vehicles and
sites on one wired contest LAN, digital on 50 / 144 / 222 / 432 (+ 902 / 1296 as equipped).

- **Many WSJT-X instances per band** — fixed beams in different azimuths, FT8 + MSK144
  simultaneously, a remote receive/TX site on the same band.
- **N1MM instances, roughly one per band** — but not rigidly: several N1MMs could serve one
  band's seats, or one N1MM could log several bands. N1MMs merge into one contest log over
  their normal TCP "Networked Computer" mechanism.
- **GridTracker roughly one per N1MM** — because an operator sits in front of both: GridTracker
  is the map / call-roster / click-to-work surface; N1MM is the log.
- **Operators float.** Several operators per band when it's open; several bands per operator
  when it's not. The band↔operator mapping changes hour to hour.
- **SSB/CW stations have priority.** Contest rules allow one transmitted signal per band; when
  the SSB/CW op on a band keys up, any WSJT-X transmission on that band must stop during each SSB/CW transmission.

Today each of these tools is wired point-to-point with per-seat UDP settings. Re-mapping an
operator to a different band means re-configuring ports and addresses at the seat, mid-contest, by a tired human. That is the specific pain this concept attacks.

## 2. The concept in one paragraph

The operator needs a **call roster**: a list of stations that are needed for the bands the
operator is using. The key feature of the call roster is that clicking on a line in the list
of stations enables the WSJT-X source of that line to begin a contact.

GridTracker2 is one program that provides a mature call roster. WIMS also has a call roster
that works but probably needs testing and improvement. This **switchboard** concept focuses on
GridTracker as the UI for making contacts and WIMS as the UI for managing the system.

**GridTracker is the UI for operating a band; WIMS is the UI for operating the station.** All
WSJT-X instances multicast to one well-known address; WIMS receives everything and becomes the
**switchboard** (application-layer router) for the *operating* flows between WSJT-X, N1MM, and
GridTracker. Operators **subscribe** to bands from a WIMS dashboard, and WIMS routes each
band's decode stream to that operator's GridTracker, routes GridTracker's click-to-work replies
back to the right WSJT-X instance (through the transmit interlock), and keeps every
GridTracker's worked-before state in sync with the merged N1MM log — something GridTracker
cannot do on its own. Moving an operator to another band is a subscription change on the WIMS
dashboard, not a re-configuration at the seat.

One flow is deliberately **not** switched: **logging.** Each WSJT-X logs to its N1MM over a
direct leg that keeps working if WIMS dies (§F4); WIMS watches that leg from both ends and
alarms when a QSO fails to reach the log, but is never in its path. Rule of thumb for the whole
design: *lose WIMS and you lose convenience (GridTracker feeds, click-to-work, dashboards) —
never QSOs, never the log.*

Working name: **WIMS Switchboard** (the earlier variant, where WIMS itself provided the call
roster, is retroactively the **WIMS Console** concept — see §8 and §10).

## 3. Who does what

| Component | Owns | Explicitly does not own |
|-----------|------|--------------------------|
| **WSJT-X** | The radio: decode, TX sequencing, CAT/PTT/audio (per seat) | Knowing who is logging it or watching it |
| **N1MM** | Contest log of record; N1MM↔N1MM merge (their native TCP network); dupe/mult authority | Driving WSJT-X (no CAT proxy, no "Load WSJT" path) |
| **GridTracker** | Per-operator operating UI: call roster, map, click-to-work | Knowing the station topology; talking to N1MM directly |
| **WIMS** | Routing of the *operating* flows (decodes → GridTracker, click-to-work → WSJT-X, log sync → GridTracker); subscription registry (who covers what); TX interlock incl. SSB/CW priority; mirrored copy of the merged log + logging audit; station + operations dashboards | The logging path (F4 is direct WSJT-X→N1MM; WIMS only audits it); logging itself (never the logger of record); transmitting on its own (a human initiates every TX); radio CAT |

The design bet: WSJT-X, N1MM, and GridTracker each keep doing exactly what their authors
intended, with **factory-default-looking network settings identical on every seat** — and all
the topology knowledge concentrates in WIMS, where one person can see and change it.

## 4. Packet flows

Flows are numbered F1–F7 for reference in review comments.

```
                     one multicast group:port, fleet-wide
  WSJT-X (any band, any PC) ──F1──►  224.0.0.73:2237  ──►  WIMS
        │                                                   │
        │ F4 logging leg — DIRECT to the band's N1MM,       ▼ F2 decode/status stream
        │    never through WIMS (survives a WIMS crash)     │    (unicast, filtered per
        ▼                                                   │     subscription)
  N1MM (band logger)                                  GridTracker (operator PC)
        │                                                   │
        ├──F5 <contactinfo> XML ──► WIMS (log mirror        └──F3 Reply (click-to-work)
        │     + logging audit vs F1's QSO-logged)                ──► WIMS ──► WSJT-X
        └──TCP merge with other N1MMs                            (interlock + lease checked,
             (their native mechanism)                             routed by instance id)

  WIMS ──F6 logged-QSO sync ──► every subscribed GridTracker (worked-before state)
  SSB/CW seat agent ──F7 band-busy ──► WIMS (blocks F3, halts TX; 10 ms mute stays seat-local)
```

### F1 — WSJT-X → WIMS (multicast, one address for the whole fleet)

Every WSJT-X instance on every PC uses the **same** UDP server setting: one multicast group and
one port (e.g. `224.0.0.73:2237`). Instances are distinguished by their WSJT-X UDP `id` (set
with `--rig-name`, e.g. `TRAILER-144-FT8`), which is carried in **every** datagram of the
WSJT-X UDP protocol — heartbeat, status, decode, QSO-logged. WIMS joins the group and learns
the fleet passively: each instance announces itself by heartbeating.

Under F4 Option 1 this is the only multicast leg in the whole system — everything else is
unicast, which sidesteps the usual multicast-on-Windows / IGMP-snooping folklore for the
consumers. (F4 Option 2 instead keeps today's per-band multicast streams, and F1 becomes
"WIMS joins all of them" exactly as WIMS does now.)

### F2 — WIMS → GridTracker (decodes, status, heartbeats)

For each operator subscription (§6), WIMS forwards the subscribed band's WSJT-X traffic to that
operator's GridTracker as ordinary unicast WSJT-X-protocol datagrams, to one well-known port on
the operator's PC. GridTracker believes it is listening to WSJT-X directly — no GridTracker
feature development is assumed.

WIMS must forward heartbeat/status as well as decodes (otherwise GridTracker declares the
"instance" dead). The decode stream is **filtered per subscription**, and the filter is a
first-class, extensible property of the subscription (§6), not a fixed behavior. Filter
criteria, composable:

- **Subscription scope** — only the subscribed band(s)/instance(s), always.
- **Contest rules** — needed vs not-needed, computed against the mirrored merged log (F5) and
  the contest configuration. This is judgment GridTracker cannot make on its own: it knows
  awards (DXCC/WAS), not VHF contest scoring (grid×band mults, rover re-works); WIMS is the
  dupe/mult authority.
- **Operator preferences** — and whatever else proves useful (minimum SNR, CQ-only, distance/
  bearing windows, "calling us" priority…); the filter set is expected to grow with use.
- **Pass-through** — a valid filter choice too (let GridTracker's own coloring do the work,
  since F6 keeps its log state correct); useful when an operator wants to see the whole band.

*Prototype status:* an experimental bridge already exists in the WIMS code
(`src/wims/udp/gt_bridge.py`): it forwards every WSJT-X datagram WIMS receives, verbatim, to
one GridTracker endpoint (default port **22370**, chosen to stay clear of the 2237–2243 band
range). What it lacks versus this concept is exactly the subscription layer: it serves one
hard-configured endpoint (`--gt-forward HOST:PORT`) with the whole fleet merged, no per-band
scoping, no discovery.

### F3 — GridTracker → WIMS → WSJT-X (click-to-work)

When the operator clicks a call in GridTracker's roster, GridTracker emits a standard WSJT-X
**Reply** datagram — addressed, as far as it knows, to its WSJT-X. It actually lands on WIMS,
which:

1. checks the operator's subscription grants **control** (not just view) of that instance;
2. checks the TX interlock — one radiated signal per band, and no SSB/CW priority lockout (F7);
3. if clear, forwards the Reply to the real WSJT-X instance (matched by the `id` carried in the
   Reply), which starts the QSO in the normal WSJT-X way.

This resolves a standing prohibition: in the current WIMS design GridTracker click-to-work is
**banned** because it would bypass the transmit interlock. With WIMS in the path, the interlock
is enforced on the only route the Reply can take — GridTracker becomes safe to promote from
"viewer only" to the primary operating UI.

**The return port does not need to be a well-known number.** GridTracker, like every WSJT-X
UDP "server"-role app, replies to the *source address:port of the datagrams it received* —
the same symmetric-UDP pattern WSJT-X itself uses (it sends from an ephemeral port and accepts
control back on that socket; the source checks are nonexistent — verified in
`MessageClient.cpp`). So GridTracker's Reply naturally lands on whatever socket WIMS forwarded
F2 from, fixed or ephemeral. The design exploits this: **one forwarding socket per
subscription**, so the return path itself identifies which subscriber clicked — free
attribution for the lease check in step 1, no port bookkeeping. A fixed number is only a
debugging/firewall-rule convenience. The one port that must be well-known is GridTracker's
*receive* port (where F2 arrives), because GridTracker has to be configured with it.

*Prototype status:* the experimental bridge already implements the return path — it binds a
fixed port (**22371**, a prototype convenience per the paragraph above), accepts GridTracker's
Reply / Halt-TX / Free-Text / etc., reads the instance `id` out of the datagram, and unicasts
it to that instance's control address. Today it is deliberately pass-through ("decide later
how strict to make it" — no interlock/lease check); under this concept, gating step 1–2 above
becomes mandatory, using the TX arbiter that already exists in the code.

Calling CQ / running a pile stays in the WSJT-X UI at the seat (the UDP API cannot run that
mode); the interlock still governs it via halt/mute (F7).

### F4 — WSJT-X → N1MM logging: direct, never through WIMS

An earlier draft of this concept routed logging through WIMS like everything else. That was
rejected: **logging is the one function the station cannot lose, so it must not depend on any
single box that isn't the logger itself.** The rule: the switchboard carries operating flows;
the log path never crosses it. Two candidate wirings for the direct leg:

**Option 1 — direct unicast logger leg (preferred, pending bench verification, Q3).** WSJT-X
has two independent UDP outputs, and this option uses each for exactly what it was built for:

| WSJT-X output | Born purpose | Switchboard use |
|---------------|--------------|-----------------|
| **Primary UDP server** (Reporting tab) — the full protocol: heartbeat, status, decodes, QSO-logged; the only channel that also *accepts* Reply/Halt | Feed the monitoring/control application | Fleet multicast `224.0.0.73:2237` → WIMS (F1) |
| **"Broadcast logged QSO to N1MM"** (the one labeled *deprecated* 😦) — sends the QSO's ADIF record, per contact, send-only; default `127.0.0.1:2333` | Log directly into N1MM | Unicast to the band's N1MM PC (the address visible in N1MM's Network Status window), port 2333 |

So each well-known port keeps one meaning: **2237 = the WSJT-X full-protocol stream** (here,
the fleet multicast), **2333 = N1MM's ADIF log ingest**, no port doing double duty. N1MM's
WSJT-X UDP reader stays off entirely.

A note on that *deprecated* label: it has been on the setting since WSJT-X 2.1.0 (2019),
removal has never actually been attempted, and N1MM+'s documentation still directs users to
it. The feature's provenance is fitting: it was requested on wsjt-devel in June 2017 by Roger,
W3SZ — for real-time contest logging into N1MM+, from this same station organization. Should
upstream ever remove it, Option 2 below remains the fallback, and a fleet that builds its own
WSJT-X controls the risk entirely.

Why not the other assignment (primary → unicast N1MM:2237, secondary → multicast to WIMS)?
The WSJT-X source rules it out: the N1MM broadcast transmits *only* `ADIF + " <eor>"` per
logged QSO on a one-shot socket (`widgets/mainwindow.cpp`, "Log to N1MM Logger") — no decodes,
no status, no heartbeat, and it cannot receive. Fed only by that, WIMS would be blind and
click-to-work impossible; the full bidirectional stream must be the leg that reaches WIMS.
(N1MM's familiar `:2237` reader is the *full-protocol* consumer — under Option 1 that role is
simply not used; under Option 2 it is, on per-band streams.)

Properties of Option 1:

- Logging is a two-box path: the WSJT-X that made the QSO and the N1MM that logs it. Nothing
  else can break it — not WIMS, not multicast, not IGMP snooping (it's plain unicast).
- Seat config stays nearly uniform: everything identical everywhere except **one**
  human-meaningful field — "your logger's address." And that field changes only when the
  band↔logger assignment changes (rare), never when *operators* move (the whole point of the
  subscription model is that operator moves touch nothing at the seats).
- Exactly-one-logger falls out of the wiring: each WSJT-X names exactly one logger; no port
  arithmetic, no reader discipline across four N1MMs.

**Option 2 — keep today's per-band multicast streams (proven fallback).** WSJT-X uses a
per-band port (50→2237, 144→2238, …) and each N1MM's reader joins exactly its band's stream —
i.e. plane A stays exactly as in the current WIMS fleet map, WIMS joins all streams, and only
the GridTracker/N1MM-mirror flows change. This is the conservative choice: the logging path is
the one already proven in the lab, at the cost of keeping the per-band port table at WSJT-X
seats (F1's "one address everywhere" simplification is lost; N1MM reader discipline returns).

Either way, **WIMS's logging role inverts from conduit to auditor.** WIMS hears every QSO twice
— WSJT-X's QSO-logged on F1, and N1MM's `<contactinfo>` on F5 — so it can cross-check the two
within seconds and raise a loud, named alarm on the operations dashboard when a QSO reported
by WSJT-X never lands in the merged log ("K1ABC 144 QSO not in N1MM after 30 s — check
N1MM-144"). A watchdog can fail without losing data; a router cannot.

Backstops behind all of this, worth stating for reviewers: every WSJT-X keeps its own
`wsjtx_log.adi` regardless (post-outage recovery by ADIF import is always possible), and the
N1MMs' own TCP merge already tolerates individual N1MM restarts.

### F5 — N1MM → WIMS (log mirror)

All N1MMs broadcast their contact/radio XML (`<contactinfo>`, `<RadioInfo>`, …) to WIMS on
N1MM's standard external-broadcast port. Combined with a read-only seed from an N1MM `.s3db`
database file, WIMS maintains a live mirrored copy of the **merged** contest log (the N1MMs
merge among themselves over their own TCP network; WIMS inherits the result). The mirror
powers F2 filtering, F6 sync, and the dashboards' dupe/needed/score views. WIMS never writes
the log.

### F6 — WIMS → GridTracker (log sync)

GridTracker cannot subscribe to N1MM's log on its own — so its worked-before coloring goes
stale the moment someone else works a station, and goes blind whenever an operator re-maps to
a band they haven't been logging. WIMS closes the loop: from the log mirror (F5), it feeds each
subscribed GridTracker the QSOs relevant to its subscription (as WSJT-X logged-QSO/ADIF
messages, or whatever ingest GridTracker proves to accept — open question Q6). Result: any
operator subscribing to any band instantly sees correct worked/needed state for that band,
reflecting QSOs made by every operator and mode, including SSB/CW QSOs logged directly into
N1MM.

### F7 — SSB/CW priority (carried over from the current WIMS design)

A small agent at each SSB/CW position senses transmit intent (e.g. CTS/footswitch sense) and
tells WIMS the band is claimed. WIMS then (a) refuses to route any F3 Reply for that band,
(b) sends Halt-TX to any WSJT-X currently transmitting on the band, and (c) — because halting
WSJT-X mid-cycle can exceed the time budget — the seat-local agent mutes WSJT-X's TX audio
within ~10 ms, independent of the network round trip. The fast mute is deliberately **not**
routed through the switchboard; it must work even if WIMS is down.

*Build status:* the per-band TX arbiter (one grant per resource group, overlap detector) is
implemented and live; the SSB/CW sense (CTS) and 10 ms audio-mute layers are designed in
detail but not yet built. The Switchboard changes nothing in that design.

## 5. WIMS as a NAT box — and why it's routing by `id`, not IP

The mental model "WIMS is a NAT box for WSJT-X/N1MM/GridTracker flows" is useful: many private
conversations, one smart middle, endpoints unaware. But the implementation is simpler than IP
NAT, because the WSJT-X UDP protocol carries an application-layer address in every datagram:
the instance `id`.

- **Upstream (F1):** WIMS learns `id → (source IP:port)` for every WSJT-X instance from its
  heartbeats. That table is self-maintaining; instances can move PCs and nothing breaks. (One
  subtlety, already handled in the current code: WSJT-X listens for control messages on the
  ephemeral source port it sends from, not on the configured server port — so the table must
  record the observed `recvfrom` address, and does.)
- **Downstream (F2/F4):** WIMS forwards datagrams with the original `id` intact, so consumers
  can tell instances apart (N1MM already distinguishes multiple WSJT-X on one stream by `id`).
- **Return path (F3):** GridTracker's Reply echoes the `id` of the instance whose decode was
  clicked, so WIMS routes it with a table lookup — no address rewriting, no NAT-style flow
  state or timeouts. The only per-subscriber state is deliberate: one forwarding socket per
  subscription, so the reply's arrival socket identifies the operator (§F3). (Verify: Q2.)

So: a **switchboard keyed on instance id**, with a subscription table deciding which flows are
patched to which endpoints. The NAT framing survives as intuition; the mechanism is cleaner.

## 6. The subscription model

Every flow out of WIMS exists because someone subscribed to it. A subscription is a row in a
WIMS-owned table, created and torn down from the operations dashboard (§7), never by touching a
seat config:

| Field | Meaning |
|-------|---------|
| Subscriber | Operator (callsign + name) and their endpoint (GridTracker at PC IP, well-known port) |
| Scope | A band (typical), or specific instances |
| Level | **view** — receive F2/F6 only; or **control** — also allowed to originate F3 |
| Lease | For control: exactly one control subscription per instance at a time |
| Filter | The F2 filter stack for this subscriber: contest needed/not-needed, operator preferences, or pass-through (§F2) |

Consequences that fall out naturally:

- **Multiple viewers, one controller.** Any number of operators can watch a hot band; exactly
  one holds control of each instance. This is the existing WIMS lease rule (design §4.5)
  expressed in routing.
- **Handoff = lease transfer.** Operator A releases (or B takes over, with A notified); decode
  flow continues to both throughout — nothing at any seat changes. Band coverage changes in
  seconds.
- **Coverage is visible.** A band with decodes flowing and no control subscriber is an empty
  seat — the operations dashboard highlights it (today that gap is discovered by chat).
- **Logger assignments are registered, not routed.** The band↔logger map lives in the same
  WIMS table so the dashboards can display and audit it (exactly one logger per instance), but
  the logging packets themselves take the direct F4 leg — WIMS checks that reality matches the
  registration; it does not carry the traffic.

## 7. Two dashboards

Phase-1 UI intent only; both are browser pages served by WIMS (plain HTML/SSE, as today).

**Station dashboard (setup & health)** — for whoever owns the plumbing:

- Discovered inventory: WSJT-X instances (live, from F1 heartbeats), N1MM instances (from F5
  presence), GridTracker endpoints (from the subscribe action, §9).
- Routing table: every active flow, with per-flow liveness (age of last datagram) so "decodes
  stopped reaching Roy's GridTracker" is a red cell, not a mystery.
- Band↔logger assignments; log-mirror status (seed age, QSO count vs N1MM).
- Readiness checks carried over from current WIMS: config audits, duplicate-`id` detection,
  the WSJT-X "Outgoing interface" trap (§9), port-ownership conflicts.

**Operations dashboard (band management)** — for the operators:

- The band × operator subscription matrix: who views, who controls, what's uncovered; one-click
  subscribe / handoff / release.
- Per-band interlock state: TX in progress, SSB/CW lockout active, last blocked action ("Reply
  to K1ABC blocked — 144 claimed by SSB").
- Logging-audit alarms (§F4): any QSO seen from WSJT-X that has not appeared in the merged
  N1MM log within the alarm window, named by instance and band.
- Activity summary per band (decode rate, unique calls, needed count from the log mirror) — the
  "which band deserves an operator" view, deliberately **not** a call roster (that is
  GridTracker's job now).
- Operator chat (replaces cross-vehicle text chat for coordination).

One honest UI gap: GridTracker has no channel for WIMS to say "your click was rejected" —
a blocked F3 just doesn't transmit. The rejection surfaces on the operations dashboard (and
possibly as an audio cue on the operator PC), so an operator working from GridTracker alone can
be briefly confused. Reviewers: is a second screen with the ops dashboard an acceptable answer,
or does this need more (Q8)?

## 8. Is this a new WIMS, or a re-partition of the old one?

Mostly a **re-partition** — the safety and logging invariants are unchanged, and most built
code carries over:

| Invariant | Console WIMS (current) | Switchboard WIMS |
|-----------|------------------------|-------------------|
| One logger of record per QSO | Per-band UDP ports; each N1MM reads one | Direct WSJT-X→N1MM leg (F4, never via WIMS); WIMS audits it |
| Logging survives a WIMS crash | Yes (WIMS is a passive observer) | **Yes — preserved by design** (F4 stays direct; only operating flows route through WIMS) |
| One radiated signal per band | WIMS TX arbiter (leases + resource groups) | Same arbiter — now also the F3 gatekeeper |
| SSB/CW priority, ≤10 ms | Seat agent mute + WIMS Halt | Identical (F7); mute never routed through WIMS |
| No unattended TX | Human clicks the WIMS roster | Human clicks the GridTracker roster |
| WIMS never logs | Log mirror is read-only | Same |

What genuinely changes:

1. **WIMS moves into the data path — for operating flows only.** Today it is a passive extra
   subscriber on multicast streams; here, all GridTracker traffic flows *through* it (logging
   deliberately does not — §F4). Losing WIMS now costs the GridTracker UIs and click-to-work,
   which is real but recoverable; see §10.
2. **GridTracker is promoted** from banned-viewer to primary operating UI; the WIMS-built call
   roster demotes to (at most) a fallback and the source of the ops-dashboard summaries.
3. **Per-band port arithmetic disappears from the seats.** Every WSJT-X, every N1MM, every
   GridTracker gets the *same* network settings everywhere; identity comes from `--rig-name`
   and the PC's IP. Seat setup approaches "install, paste standard settings, done" (§9).
4. **A new explicit goal:** the *setup* of WSJT-X/N1MM/GridTracker should be as close to their
   single-op defaults as possible, with all multi-op complexity absorbed by WIMS. The previous
   design accepted per-band port tables as the price of robustness; this concept treats that
   price as too high for real crews at 3 AM.

How much is already built (i.e. how far this is from vapor):

- **Exists and live:** multicast ingest of all band streams; instance tracking by `id`
  including the control-address table; the TX arbiter (one grant per resource group) and
  overlap detector; the N1MM log mirror (live `<contactinfo>` + `.s3db` seed/resync); passive
  N1MM presence discovery; server presence/dual-primary detection; the setup/status readiness
  tooling (config audits, the Outgoing-interface trap detector).
- **Exists as an experimental prototype:** F2 forward and F3 return (the GridTracker bridge —
  single endpoint, no subscriptions, no interlock gating yet).
- **Design only:** SSB/CW sense + 10 ms mute agents (F7 fast path).
- **New work specific to this concept:** the subscription registry and per-subscription
  routing/filtering; the F4 logging audit (cross-check QSO-logged vs `<contactinfo>`); F6 (log
  sync into GridTracker); the two dashboards' switchboard-specific views; GridTracker
  discovery; bench verification of the Option-1 direct logger leg (Q3).

## 9. Configuration & discovery story

Per-seat configuration collapses to constants that are identical on every PC:

| App | Setting, same on every seat | Per-seat exceptions | Identity comes from |
|-----|------------------------------|---------------------|---------------------|
| WSJT-X | UDP server = one fleet group:port; accept UDP requests on; **outgoing interface = contest-LAN NIC** | Logger address (F4 Option 1): "my N1MM is at «IP»" — one field, changes only when logger assignments change | `--rig-name` (UDP `id`) |
| N1MM | External broadcast → WIMS standard port; WSJT-X multicast reader **off** (Option 1) | — (Option 2 instead keeps the per-band reader config) | N1MM station name |
| GridTracker | Listen on one well-known UDP port | — | The PC's IP address |

(The one un-defaultable seat setting is WSJT-X's *Outgoing interface* on multi-NIC PCs — the
long-standing silent-failure champion. It survives every architecture that involves a network;
the station dashboard keeps auditing for it.)

Discovery, per component:

- **WSJT-X:** self-announcing — heartbeats on the fleet multicast group (F1). Nothing to probe.
- **N1MM:** by N1MM's own mechanisms — its external broadcasts reveal station name and PC as
  soon as broadcast is enabled, and WIMS can seed/verify from the `.s3db` log database. The
  band assignment can be *proposed* automatically from the radio frequency in `<RadioInfo>` and
  confirmed by a human on the station dashboard.
- **GridTracker: needs analysis (Q5).** GridTracker is a pure listener; it doesn't announce
  itself. Candidate mechanisms, in rough order of appeal:
  1. **Subscribe-from-the-same-PC:** the operator opens the WIMS operations dashboard *on the
     PC that runs their GridTracker* and clicks subscribe; WIMS learns the PC's IP from the
     HTTP request and sends F2 to `that-IP:well-known-port`. Zero configuration, and the
     subscription action doubles as discovery.
  2. Liveness after first contact: once WIMS transmits to it, GridTracker (as a WSJT-X-protocol
     client) may heartbeat back — usable as an "endpoint alive" check (verify: Q5).
  3. Fallback: the subscription form takes a hostname/IP (this is all the experimental bridge
     offers today — a `--gt-forward HOST:PORT` flag at server start).

## 10. Costs and risks (please attack these)

- **WIMS is a single point of failure for the operating flows (not for logging).** Logging was
  deliberately kept off the switchboard (§F4) precisely so a WIMS failure can never lose QSOs
  or stop the log. What a dead WIMS *does* stop: decodes-to-GridTracker, click-to-work, log
  sync, dashboards, and the *preventive* SSB/CW gate (the 10 ms fast mute is agent-to-agent
  and survives; but with click-to-work down, digital TX initiation falls back to the seats
  anyway). The degraded mode is well-defined and workable: every seat still has its full local
  WSJT-X UI and its logger, i.e. the station degrades to how multi-multis operate today —
  losing the force-multiplier, not the contest. Recovery is fast because the switchboard is
  nearly stateless: the routing table rebuilds from heartbeats within one WSJT-X heartbeat
  interval (~15 s), subscriptions persist on disk, and the log mirror reseeds from `.s3db` +
  live `<contactinfo>`. The existing presence/dual-primary mechanism could later grow into a
  warm standby, but that is an optimization, not a safety requirement once logging is out of
  the path. Reviewers: Q9 asks what outage duration is actually tolerable for the *operating*
  flows.
- **GridTracker multi-instance behavior is unproven (Q1).** One subscription may carry several
  WSJT-X instances (three 6 m beams). All datagrams arrive on one socket with different `id`s
  and possibly different dial frequencies. If GridTracker mishandles that, options: one
  GridTracker (window) per instance, WIMS presenting a synthetic merged instance per band, or
  scoping subscriptions to single instances.
- **Silent rejection UX** (§7, Q8).
- **Unicast fan-out load** is a non-issue at FT8 rates (a busy band is tens of datagrams per
  15 s cycle; even ×10 subscribers is nothing on a wired LAN) — listed only so reviewers see it
  was considered.
- **Protocol assumptions to verify on the bench** — collected in §11.

## 11. Open questions (numbered for review replies)

- **Q1.** How does GridTracker actually behave when one UDP socket carries interleaved traffic
  from several WSJT-X `id`s? (Roster mixing, status flapping, band display?)
- **Q2.** Does GridTracker's Reply datagram carry the originating instance `id` verbatim in all
  click paths (roster click, map click, alerts)? F3 routing depends on it. (The WIMS-side
  plumbing — route inbound control datagrams by their `id` field — already exists in the
  experimental bridge; what needs live confirmation is GridTracker's side.)
- **Q3.** F4 Option 1 bench verification — narrowed by source inspection: the WSJT-X side is
  now known (the N1MM broadcast sends the QSO's full ADIF record, so band/mode/grid ride
  along; default `127.0.0.1:2333`). Remaining to prove on a real N1MM: does it accept the
  ADIF broadcast from a **non-local source IP**; does it log correctly under a VHF contest
  config; behavior across WSJT-X and N1MM restarts. If it falls short, F4 Option 2 (per-band
  multicast streams, today's proven path) is the fallback.
- **Q4.** With all WSJT-X on one group:port (F1), the standing rule becomes "no N1MM WSJT-X
  reader may join the fleet multicast" (Option 1) — otherwise that N1MM logs every band. Is
  that discipline enforceable across guest PCs and old configs? (WIMS can detect and alarm on
  it — an N1MM logging QSOs for instances outside its registered assignment is visible in the
  F5 stream — but detection is not prevention.)
- **Q5.** GridTracker discovery and liveness: does GT heartbeat back to the sender as a WSJT-X
  protocol client? Is the subscribe-from-the-same-PC flow (§9) sufficient for real crews?
- **Q6.** What is the most reliable way to push fleet-wide logged QSOs *into* GridTracker so
  its worked-before state stays correct: WSJT-X logged-ADIF UDP messages, GT's N1MM ingest (it
  has none today — confirm), a watched ADIF file, or something else?
- **Q7.** Two operators (two GridTrackers) on one PC: worth supporting, or is "one operator UI
  per PC" an acceptable rule? (Two GridTrackers cannot share one unicast *receive* port — the
  bridge work already established the exclusive-bind requirement — so supporting this would
  mean assigning the second GridTracker a different receive port. The reply direction is
  already solved by per-subscription forwarding sockets, §F3.)
- **Q8.** Is "rejections and lockouts surface on the WIMS ops dashboard, not in GridTracker"
  acceptable in practice, or does the operator need in-your-face feedback at the point of
  click?
- **Q9.** Failure drill: with logging safe by construction (§F4), how long an outage of the
  *operating* flows (GridTracker feeds, click-to-work, dashboards) is tolerable before crews
  would want a warm-standby WIMS — is "seats fall back to their local WSJT-X UIs for a few
  minutes" acceptable?
- **Q10.** Naming (see below) — better ideas welcome.

## 12. Naming

Working name **WIMS Switchboard** — the telephone-switchboard metaphor carries all three ideas:
flows patched through one point, subscribers, and a human at the board managing who talks to
whom. ("Exchange" was rejected: in contesting, *exchange* already means something.) The
call-roster-centric variant already designed and partially built is the **WIMS Console**. Other
candidates considered: WIMS Hub, WIMS Fabric, WIMS Patch Panel.
