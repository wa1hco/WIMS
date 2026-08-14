# WIMS Key Agent — standalone design

**Status:** design for implementation (standalone program).  
**Audience:** implementers moving this into the WIMS tree (or a sibling package).  
**Companions:**

| Doc | Role |
|-----|------|
| [wims_tx_inhibit.md](wims_tx_inhibit.md) | TX Inhibit **gate** inside WSJT-X; wire protocol; hang semantics |
| [wims_design.md](wims_design.md) § functions #5–#7, §2.14, §3.4.1 | Fleet partitioning; interlock vs coordinated policy |
| `src/wims/interlock/inhibit.py` | Pure-logic `KeyAgentScheduler` + `InhibitGate` (no I/O) — reuse |

This document specifies the **Key agent** as a **standalone process** that can run with
**minimal WIMS** (simple single-band dual-radio station) and later join a full multi-multi
fleet without changing the safety path.

---

## 1. Purpose

Give **SSB/CW priority over WSJT-X on the same band** by watching the SSB/CW **KEY/PTT line**
and sending **TX Inhibit** datagrams to the digital radio’s WSJT-X (patched gate), **without**
routing that path through the WIMS site server.

**WIMS server is optional for the critical path.** The agent must keep working if the server is
down, unconfigured, or never installed (simple station).

---

## 2. Station model — simple dual-radio band (primary scenario)

One band, two radios, shared antenna plant (as used at multi-multi sites and suitable for a
two-op or one-op home/club station):

```
                    ┌─────────────────┐
   Antenna ──split──┤ RX path (always)├──► SSB/CW radio (RX)
            │       │                 ├──► WSJT-X radio (RX)  ← listening always
            │       └─────────────────┘
            │
            │  TX path (mutually exclusive RF out)
            │       ┌─────────────────┐
            └──────►│ TX/Rx relays    │◄── KEY/PTT from either radio
                    │ + SO2R / first- │
                    │   keyed wins    │──► amp / antenna
                    └─────────────────┘
```

### 2.1 RF and control facts (requirements)

1. **Receive:** antenna energy is **split** (or multicoupled) so **both** radios receive
   whenever neither is transmitting (or per station RF rules). WSJT-X **listens continuously**
   during SSB/CW receive and during many SSB/CW overs.
2. **Transmit:** either radio **can** drive the antenna or amplifier. Hardware **TX/Rx
   relays** and an **SO2R-class interlock** (or equivalent) ensure **one RF source** at a
   time — typically **first KEY wins** for the TX path switch.
3. **Contest rule residual:** even with first-KEY SO2R hardware, **WSJT-X must not radiate
   while SSB/CW is keyed** if the digital path can still assert PTT (software TX, VOX, etc.).
   The Key agent + WSJT-X inhibit gate close that software/RF gap: **SSB/CW KEY → inhibit
   digital PTT**.
4. **Decode tolerance (operational finding, W2SZ):** FT8 over a 15 s period still decodes
   usefully when several seconds of audio are lost to SSB/CW TX, unless the signal is
   extremely weak. Therefore **continuous RX of FT8 during SSB CQ / run is valuable** —
   watch for needed mults without stopping voice operation.

### 2.2 Operating modes the Key agent enables

| Mode | Ops | What happens |
|------|-----|----------------|
| **A. Single operator, manual handoff** | One human | Watches FT8 (GridTracker and/or WIMS roster). When they want digital, they stop SSB TX and use WSJT-X. Hardware SO2R still protects RF. Key agent still inhibits WSJT if they key SSB while WSJT Enable Tx is on. |
| **B. Two operators, concurrent intent** | SSB op + FT8 op | FT8 op runs CQ / S&P on WSJT-X; SSB op has **priority** and may key at any time. Key agent **inhibits** WSJT-X PTT on SSB KEY so digital RF cannot fight voice even if WSJT thinks it is transmitting. |
| **C. Fleet / multi-beam** (later) | Multi-multi | Same agent binary; **target list** may include several WSJT-X inhibit endpoints on the band (South/West/East). Assignment may come from WIMS or a local config file. |

Modes A/B are the **MVP**. Mode C reuses the same protocol and process.

### 2.3 What the Key agent is *not*

- Not the SO2R RF switch (hardware).
- Not N1MM, not the WIMS site server, not the seat setup agent (`wims.agent`).
- Not a substitute for patched WSJT-X **TX Inhibit** (gate) on the digital PC — without the
  gate, the agent can only log or use weaker fallbacks (UDP Halt — too slow / incomplete).
- Not multi-SSB arbitration among several voice stations (OR KEY lines in hardware or one
  combined sense line — [wims_tx_inhibit.md](wims_tx_inhibit.md) §4.3).

---

## 3. Program identity

| Item | Spec |
|------|------|
| **Name** | **WIMS Key Agent** (CLI / package entry e.g. `python -m wims.key_agent` or `wims-key-agent`) |
| **Form** | **Standalone long-running process** (Windows service-capable later; day-one = console + optional tray) |
| **Host** | **SSB/CW radio PC** (where KEY/PTT can be sensed) |
| **Count** | One process per SSB/CW radio (or per combined KEY sense line) |
| **Language** | Python 3.10+, stdlib-first (align with WIMS); pure scheduling logic already in `inhibit.py` |
| **Dependencies** | Zero required for core path; serial via OS COM / `/dev/tty*` |

### 3.1 Relationship to other WIMS pieces

```
  SSB/CW KEY ──► [ Key agent ] ──UDP hold/release──► [ WSJT-X PttGate ] ──► radio PTT
                      │                                      ▲
                      │ optional status                      │ local CTS optional
                      ▼                                      │
                 WIMS server (inventory, assignment UI)      │
                      │                                      │
                 Seat agent (setup audit)  — separate process on WSJT PC
```

| Piece | Required for simple station? |
|-------|------------------------------|
| Key agent | **Yes** (for software priority) |
| WSJT-X with inhibit gate ([wsjtx-wims](https://github.com/wa1hco/wsjtx-wims) or equiv.) | **Yes** |
| Hardware SO2R / first-KEY | **Strongly recommended** (RF truth) |
| WIMS server | **No** for inhibit path; **Yes** for fleet roster / assignment UI |
| GridTracker | Optional roster for mode A |
| Seat `wims.agent` | Optional setup audit |

---

## 4. Responsibilities (MVP)

### 4.1 Must do

1. **Sense KEY/PTT** of the SSB/CW radio as a **level** (asserted / not), not a one-shot edge
   only — continuous sample or OS edge + state.
2. **Primary sense method:** USB-serial **CTS** (or DSR/DCD if wired) on a dedicated or
   Keyline-style port ([wims_tx_inhibit.md](wims_tx_inhibit.md) §4.1 / Keyline board).
3. On **key-down:** immediately schedule **inhibit hold** datagrams to all configured
   **targets** (`ttl_ms` > 0).
4. While **keyed:** send **keepalives** (default every **200 ms**) so the gate deadman does
   not expire.
5. On **key-up:** apply **hang** (adaptive or fixed — reuse `KeyAgentScheduler` in
   `inhibit.py`), then send **release** (`ttl_ms: 0`).
6. **Persist target list** locally so a WIMS outage does not disarm the interlock.
7. **Fail-safe direction:** agent crash / stop → stop sending holds → gate **self-clears** by
   TTL (band returns to digital TX allowed). Never “stick on forever” from a dead agent.
8. **Local status:** console and/or tiny HTTP page: KEY state, hang mode, last send errors,
   target list, packet counters.

### 4.2 Should do (simple station UX)

1. **Config file** for targets without WIMS (see §6).
2. **Keyboard / dry-run mode** for lab without serial (SPACE = KEY) — already proven in
   `testbed/inhibit_spike.py`.
3. **Discovery of Keyline USB** by VID/PID or serial description when present.
4. Optional **heartbeat status** to WIMS server (`POST` or UDP) for fleet inventory
   (“SSB keyed”, agent health) — **not** on the inhibit critical path.

### 4.3 Must not do

1. Route inhibit traffic **through** the WIMS server.
2. Implement SO2R RF switching in software.
3. Require operator login or multi-tenant security (cooperative LAN).
4. Block FT8 **decode** — inhibit is **TX/PTT only**; RX continues (split antenna).

---

## 5. Wire protocol (to WSJT-X gate)

**Authoritative detail:** [wims_tx_inhibit.md](wims_tx_inhibit.md) §11.3. Summary for the agent:

| Field | Meaning |
|-------|---------|
| `tx_inhibit` | Magic / version (protocol v1) |
| `band` | Band label or id (informational / multi-agent debug) |
| `station` | Key-agent / SSB station id (last holder wins on gate) |
| `ttl_ms` | Hold duration; **`0` = release** |
| `seq` | Monotonic sequence for diagnostics |

- **Transport:** UDP **unicast** to each target `ip:port` (default gate port **22372**, with
  documented fallback if WSJT-X bound ephemeral — gate docs).
- **One message type** only: “inhibit for `ttl_ms`.”
- **Gate behavior:** single hold; last hold wins; release opens; deadman expiry if no
  keepalive; **no hang inside WSJT-X** — hang is **agent-side** only.

**Implementation:** call `KeyAgentScheduler` + `encode_datagram` from `wims.interlock.inhibit`;
agent owns threads, serial I/O, and `sendto`.

---

## 6. Configuration

### 6.1 Minimal config (no WIMS) — simple station

File example: `%APPDATA%\WIMS\key_agent.ini` or `./key_agent.toml` next to the binary.

```ini
[agent]
station_id = SSB-144
band = 2m

[sense]
# COM3, /dev/ttyUSB0, or "auto" for Keyline
port = auto
# cts | dsr | dcd | keyboard | script
line = cts
# invert if hardware is active-high vs active-low
invert = false

[inhibit]
# One or more WSJT-X gate endpoints on this band
targets = 127.0.0.1:22372
# For split PCs:
# targets = 192.168.1.50:22372

[timing]
keepalive_s = 0.2
# hang_s = 0.5   # fixed; omit for adaptive hang (default)

[wims]
# optional — status only
# server = http://192.168.1.10:8787
# report_interval_s = 5
```

**Co-located** SSB + WSJT on one PC: `targets = 127.0.0.1:22372`.  
**Split PCs:** unicast to the WSJT-X host’s LAN IP.

### 6.2 With WIMS (fleet)

- Server may **push** target list (function #5): “assign WSJT inhibit inputs to this Key
  agent.”
- Agent **merges**: pushed list overrides file if newer; always **write-through persist**.
- Band policy **`interlock`** vs **`coordinated`** ([wims_design.md](wims_design.md) §2.14):
  - **`interlock`:** send holds as specified here.
  - **`coordinated`:** sense + report KEY for UI; **do not** send inhibit holds (or send
    only if local override `force_inhibit=true` for bench).

Default without server: behave as **interlock** if targets configured; else sense-only with
loud “no targets” warning.

### 6.3 Target list semantics

Each target is an **inhibit UDP destination**, not a WSJT-X “rig name” on plane A.

| Simple station | Typical targets |
|----------------|-----------------|
| One WSJT radio | One `ip:port` |
| 6 m three beams (South/West/East) | Three destinations (or one PC multi-instance → three ports) |

Agent **fans out** every hold/keepalive/release to **all** targets identically.

---

## 7. Process architecture

```
┌─────────────────────────────────────────────┐
│  Key agent process                          │
│  ┌─────────────┐    ┌────────────────────┐  │
│  │ Sense thread│───►│ KeyAgentScheduler  │  │
│  │ (CTS poll / │    │ (pure logic)       │  │
│  │  keyboard)  │    └─────────┬──────────┘  │
│  └─────────────┘              │ datagrams   │
│  ┌─────────────┐              ▼             │
│  │ UDP sender  │◄── encode ── hold/release  │
│  └──────┬──────┘                            │
│         │ unicast fan-out                   │
│  ┌──────┴──────┐  optional                  │
│  │ Status HTTP │  WIMS report thread        │
│  │ :8791       │                            │
│  └─────────────┘                            │
└─────────────────────────────────────────────┘
```

- **Sense loop:** ≤1 ms poll fallback if `TIOCMIWAIT` unavailable (known Digirig/Linux case);
  prefer edge wait where supported.
- **No dependency** on GUI event loops for the send path.
- **Single writer** to UDP socket; counters atomic or locked.

---

## 8. Operator UX (day one)

### 8.1 Launch

```text
Windows:  scripts\windows\Start-WimsKeyAgent.cmd
Linux:    PYTHONPATH=src python3 -m wims.key_agent --config ...
```

Console banner:

```text
WIMS Key Agent  station=SSB-144  band=2m
  sense: COM7 CTS  (Keyline)
  targets: 192.168.1.50:22372
  state: OPEN (idle) | INHIBITING (keyed) | HANG
```

### 8.2 Indicators

| State | Meaning |
|-------|---------|
| **OPEN** | KEY idle; not sending holds (or after release) |
| **INHIBITING** | KEY down; holds/keepalives flowing |
| **HANG** | KEY up; hang timer before release |
| **NO TARGETS** | Misconfig — will not protect digital |
| **SENSE FAULT** | Port open failed / line unknown |

### 8.3 Interaction with human ops (modes A/B)

- **SSB op:** keys normally; no Key-agent UI required after setup.
- **FT8 op:** WSJT-X may show “TX” intent while **inhibited** (gate masks PTT); RF stays off
  until KEY clear + hang. Optional WSJT-X badge from InhibitStatus (gate feature).
- **GridTracker / WIMS roster:** still useful for *who to work*; Key agent does not filter
  decodes.

---

## 9. Failure modes and safety

| Failure | Result | Operator sees |
|---------|--------|----------------|
| Agent crash while keyed | Gate TTL expires → digital TX allowed again | Brief unprotected window; alarm if WIMS watches expiries |
| Agent crash while idle | No change | — |
| Network drop to WSJT PC | Keepalives lost → gate expires → digital may TX during SSB | Bad — prefer co-locate or reliable LAN; Status “interlock degraded” if reported |
| Wrong target IP | SSB keys; WSJT still radiates | Setup test: key SSB, confirm WSJT PTT LED/RF off |
| Unpatched WSJT-X | Datagrams ignored | Setup must verify gate binary |
| Invert sense wrong | Permanent inhibit or never inhibit | Config invert + bench test |

**Principle:** prefer **momentary loss of protection** over **stuck inhibit** (deadman).  
**Principle:** RF SO2R remains the last line for two PA keys; agent protects **software TX**.

---

## 10. Setup / acceptance tests

### 10.1 Lab (no RF)

1. `python testbed/inhibit_spike.py selftest` (existing).
2. Key agent `--line keyboard` → local gate spike or patched WSJT-X on loopback.
3. Assert: key-down → inhibit &lt; few ms after sense; key-up → hang → release.

### 10.2 Dual-radio station (dummy load)

1. Split RX confirmed: FT8 decodes while SSB on receive.
2. WSJT Enable Tx / CQ; SSB keys → **no digital RF** (scope/wattmeter/LED); WSJT UI may still
   show transmitting intent.
3. SSB unkeys → after hang, digital RF can proceed if still enabled.
4. First-KEY SO2R: only one PA keyed (hardware).
5. Kill Key agent mid-SSB key → within ~1 s digital uninhibited (document risk).

### 10.3 Two-operator drill

1. FT8 op runs CQ; SSB op calls CQ or works a station.
2. Confirm FT8 roster still updates across overs (W2SZ-class behavior).
3. Confirm no double RF on band.

---

## 11. Implementation plan (for WIMS tree)

Suggested package layout:

```text
src/wims/key_agent/
  __init__.py
  __main__.py          # python -m wims.key_agent
  app.py               # argparse, main loop
  sense.py             # CTS / keyboard / script
  config.py            # load/save targets
  report.py            # optional WIMS POST
  static/              # optional local status page
scripts/windows/Start-WimsKeyAgent.cmd
docs/plan/wims_key_agent.md   # this file
```

**Reuse:** `wims.interlock.inhibit.KeyAgentScheduler`, `encode_datagram`, adaptive hang.

**Order:**

1. CLI + keyboard sense + unicast fan-out + config file (MVP simple station).  
2. Serial CTS + Keyline auto-detect.  
3. Local status HTTP.  
4. Optional WIMS registration + pushed target list.  
5. Windows installer shortcut next to other seat scripts.

**Non-goals for v1:** full SO2R controller UI; multi-band one agent; authentication.

---

## 12. Open decisions

| Topic | Proposal |
|-------|----------|
| Default gate port if 22372 busy | Document WSJT-X bind; agent config override per target |
| Digirig without CTS | Explicit “unsupported for KEY sense”; Keyline board preferred |
| Same PC WSJT + SSB | `127.0.0.1` target; still run agent (not only local CTS on gate) for one mechanism |
| Coordinated band policy | Agent still useful as KEY telemetry to WIMS without holds |
| Naming | `wims.key_agent` module vs `keyagent` binary — prefer `wims.key_agent` |

---

## 13. Summary

The **Key agent** is a **small, standalone, long-running program on the SSB/CW PC** that:

1. Watches the **KEY line**,  
2. Sends **TX Inhibit** UDP to the band’s WSJT-X gate(s),  
3. Implements **SSB/CW priority** for concurrent voice + digital receive (and two-op digital),  
4. Works **without** the WIMS server,  
5. Scales to multi-beam target lists when WIMS assigns them.

Hardware **SO2R / first-KEY** owns the antenna; the Key agent owns **software PTT discipline**
on the digital radio so FT8 can stay in the chair—and on the roster—while SSB runs, without
radiating over the voice op.
