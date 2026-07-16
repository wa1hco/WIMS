# WIMS — Fleet networking map (WSJT-X / N1MM / GridTracker)

Companion to **[wims_design.md](wims_design.md)** (requirements / design). This document is the
**authoritative networking layout** for the contest digital fleet: who multicasts what, who
joins which streams, and how loggers stay single-owner. When the *layout* changes, edit here
and keep §Deployment / §4.3 in the design doc in sync at a summary level.

Related: **[wims_status.md](wims_status.md)** for what the server currently binds/joins in code.

**Critical ops note:** every WSJT-X instance must set **Outgoing interface = contest LAN NIC**
(§4.1). Multicast address alone is not enough — blank / `@Invalid()` interface is a silent
failure (decodes work, WIMS never sees UDP).

---

## 1. Station layout (digital)

```
TRAILER
├── N1MM-50
│   ├── WSJT-X  TRAILER-50-A   FT8   (fixed beam az₁)
│   ├── WSJT-X  TRAILER-50-B   FT8   (fixed beam az₂)
│   └── WSJT-X  TRAILER-50-C   FT8   (fixed beam az₃)
│
└── N1MM-144
    ├── WSJT-X  TRAILER-144-FT8     FT8
    └── WSJT-X  TRAILER-144-MSK     MSK144  (or EME / Q65)

222 seat (e.g. Roy)
└── N1MM-222
    └── WSJT-X  ROY-222-FT8         FT8

432 seat (e.g. Roy)
└── N1MM-432
    └── WSJT-X  ROY-432-FT8         FT8
```

| | Count |
|--|------:|
| Digital bands | 4 (50, 144, 222, 432) |
| N1MM (one per band) | 4 |
| WSJT-X instances | 7 (3 + 2 + 1 + 1) |

**TX resource groups (one radiated signal per band, multi-multi):**

| Band | Instances | Resource group | Concurrent with other bands? |
|------|-----------|----------------|------------------------------|
| 50 | A/B/C | `50-signal` — at most one of A/B/C TX | yes |
| 144 | FT8 + MSK/EME | `144-signal` — at most one TX | yes |
| 222 | one FT8 | `222-signal` | yes |
| 432 | one FT8 | `432-signal` | yes |

Instance ids above are examples; convention is `VEHICLE-BAND[-role]` via WSJT-X `--rig-name`
(unique UDP `id` — required; IP alone is not enough when two instances share a host).

Microwave (Chip 903+) is out of scope for this map until those seats are wired the same way.

---

## 2. Physical / roles

```
                    ┌─────────────────────────────────────┐
                    │     Contest LAN (one L2 domain)     │
                    │   e.g. 192.168.10.0/24  wired       │
                    └─────────────────────────────────────┘
           │              │              │              │
      TRAILER          TRAILER         222 seat       432 seat
      (50 hosts)       (144 hosts)     (e.g. Roy)     (e.g. Roy)
           │              │              │              │
    ┌──────┴──────┐ ┌─────┴─────┐   ┌────┴────┐    ┌────┴────┐
    │ N1MM-50     │ │ N1MM-144  │   │N1MM-222 │    │N1MM-432 │
    │ 3× WSJT-X   │ │ 2× WSJT-X │   │1× WSJT-X│    │1× WSJT-X│
    │ (+ GT?)     │ │ (+ GT?)   │   │ (+ GT?) │    │ (+ GT?) │
    └─────────────┘ └───────────┘   └─────────┘    └─────────┘

              ┌──────────────────────────┐
              │  WIMS SERVER (site)      │
              │  joins ALL radio UDP     │
              │  serves browser consoles │
              └──────────────────────────┘
                         │
              HTTP/SSE (unicast) → operator browsers
              (LAN or Tailscale; no multicast over WAN)
```

Optional **GridTracker**: any operator PC that wants a map/viewer; **never** click-to-work on
WIMS-managed instances (that bypasses the TX arbiter — design §1.2 / §4.3).

---

## 3. Planes (do not conflate)

| Plane | What | Purpose |
|-------|------|---------|
| **A. Radio UDP (multicast)** | WSJT-X Heartbeat / Status / Decode / QSO Logged | Decodes, status, N1MM logging of digital QSOs |
| **B. Logger UDP (N1MM external)** | `<contactinfo>`, `<RadioInfo>`, … on **:12060** | WIMS log copy, presence, roster dupe/mult |
| **C. N1MM peer network (TCP)** | N1MM “Networked Computer” | One **merged** contest log among the four N1MMs |
| **D. Console unicast** | HTTP/SSE (later TLS/WS) to WIMS | Operators; never the RF data path over the internet |
| **E. Site-server presence** | WIMS JSON beacon ~1 Hz multicast | Single-primary lockout + zero-memory console discovery |

- WIMS uses **A + B + D + E**.
- **C** is N1MM↔N1MM only (WIMS does not speak that protocol; it inherits the merge via
  `.s3db` seed / resync and live `<contactinfo>`).
- SSB/CW **10 ms** mute is **not** plane B; it is host-agent peer UDP / CTS (design §3.4.1).

### 3.1 Plane E — site-server presence (MVP)

**Problem:** two `wims.server` processes = two divergent log/roster brains; operators should not
memorize the server IP.

**Mechanism:**

| | |
|--|--|
| Group | `224.0.0.73` (same contest LAN multicast story as WSJT-X) |
| Port | **8788 UDP** (8787 remains **TCP HTTP** only) |
| Rate | ~1 Hz JSON beacon while primary |
| TTL | 3 (contest LAN) |
| Outgoing iface | `--iface` (contest LAN NIC — same silent-failure rule as WSJT-X) |

**Payload (schema 1):** `kind=wims-server`, `instance_id`, `hostname`, `lan_ips`, `http_port`,
`console_base`, `urls.{operate,status,setup,healthz}`, `started_ts`, `seq`.

**Server:**

1. On start, **listen ~2 s** for a live peer beacon.
2. If another `instance_id` is heard → **refuse** to start (exit 2) with a plain-language message
   naming the peer URL (unless `--force-server` lab override).
3. If clear → become primary, **announce ~1 Hz**.
4. Keep listening; if a second primary appears → **demote** (exit 2) with the same diagnostic.

**Agent:**

1. Listen briefly (and periodically in `--daemon`) for presence.
2. Local UI `http://127.0.0.1:8790/` shows **clickable** Operate / Status / Setup links
   (zero-memory path: open agent → click).
3. If `--server` / `WIMS_SERVER` is unset, use discovered `console_base` for export.
4. If configured URL ≠ discovery, show a warn; export prefers configured, links prefer discovery.

**Not solved by plane E:** internet/Tailscale discovery (still explicit URL); automatic HA
failover (human stops the wrong host); auth.

**Code:** `src/wims/discovery/presence.py` · server flags `--presence-group/port`, `--no-presence`,
`--force-server` · agent `--no-discover`, **Find site server** button.

---

## 4. Plane A — WSJT-X multicast (segregated by band)

### Why segregate

Each band has its own N1MM. If all seven WSJT-X share **one** group:port and every N1MM enables
the WSJT UDP reader on that stream, more than one N1MM can try to log the same QSO →
**double-log** (no shared QSO id across N1MMs). Design invariant: **exactly one logger-of-record
per WSJT-X instance**.

**Rule:** each N1MM joins **only its band’s** stream; **WIMS joins every stream**.

### Recommended scheme — same group, port per band

| Band | Multicast group | Port | WSJT-X instances (unique `--rig-name`) | Logger (only) | Read-only joiners |
|------|-----------------|-----:|----------------------------------------|---------------|-------------------|
| 50 | `224.0.0.73` | **2237** | TRAILER-50-A/B/C | **N1MM-50** | WIMS; optional GT |
| 144 | `224.0.0.73` | **2238** | TRAILER-144-FT8, TRAILER-144-MSK (or EME) | **N1MM-144** | WIMS; optional GT |
| 222 | `224.0.0.73` | **2239** | ROY-222-FT8 | **N1MM-222** | WIMS; optional GT |
| 432 | `224.0.0.73` | **2240** | ROY-432-FT8 | **N1MM-432** | WIMS; optional GT |

**Alternate:** port always `2237`, groups `224.0.0.50` / `.144` / `.222` / `.432`. Pick one scheme
and declare it in Instance Profiles (§3.14); do not mix schemes mid-contest.

Many instances may share one group:port; N1MM and WIMS disambiguate by UDP **`id`**. N1MM’s two
UDP readers are for **two streams** (e.g. two bands on one PC), not a limit of two WSJT-X total.

### Diagram

```
                    224.0.0.73
         ┌──────────┬──────────┬──────────┬──────────┐
         :2237      :2238      :2239      :2240
         (50)       (144)      (222)      (432)
           ▲          ▲          ▲          ▲
           │          │          │          │
    ┌──────┴───┐ ┌────┴────┐ ┌───┴───┐ ┌───┴───┐
    │ 50-A/B/C │ │144-FT8  │ │222-FT8│ │432-FT8│
    │  WSJT-X  │ │144-MSK  │ │WSJT-X │ │WSJT-X │
    └────┬─────┘ └────┬────┘ └───┬───┘ └───┬───┘
         │            │          │         │
         ▼            ▼          ▼         ▼
    ┌─────────┐  ┌─────────┐ ┌────────┐ ┌────────┐
    │ N1MM-50 │  │N1MM-144 │ │N1MM-222│ │N1MM-432│  ← each joins ONE port
    │ (log)   │  │ (log)   │ │ (log)  │ │ (log)  │
    └─────────┘  └─────────┘ └────────┘ └────────┘

    ┌──────────────────────────────────────────────┐
    │  WIMS SERVER  joins ALL four ports           │
    │  (optional GT: join 1+ ports for viewing)    │
    └──────────────────────────────────────────────┘
```

Control path (when command path lands): WIMS → Reply/Halt on the instance’s stream, addressed by
UDP `id`. Only the **lease holder’s** console commands are honored (design §4.5).

### WSJT-X settings (every instance)

These are **required**, not optional tips. Details and verification for the interface field:
**§4.1**.

| Setting (Settings → Reporting) | Required value |
|--------------------------------|----------------|
| UDP Server | Multicast group from table (e.g. `224.0.0.73`) — **not** `127.0.0.1` for fleet |
| UDP Server port number | Band port from table |
| **Outgoing interface** | **Contest LAN NIC** — see **§4.1** (never blank / `@Invalid()` / loopback) |
| TTL | Sufficient for the LAN (design baseline: **3**) |
| Accept UDP requests | **Yes** when WIMS will drive Reply/Halt |

Also: unique `--rig-name` → unique UDP `id`; do **not** use GridTracker as a relay.

### 4.1 Contest LAN interface (WSJT-X “Outgoing interface”)

This is the **most common silent networking failure** for multi-instance and multi-host WIMS.

#### What it is

In WSJT-X: **File → Settings → Reporting** (or **Preferences → Reporting**).

| Field | Meaning |
|-------|---------|
| **UDP Server** | Destination address for Heartbeat / Status / Decode / QSO Logged (use fleet multicast) |
| **UDP Server port number** | Destination port (band stream from §4 table) |
| **Outgoing interface** | **Which local NIC** WSJT-X uses to send that UDP |

`.ini` key: `UDPInterface=...` (per instance file, e.g. `~/.config/WSJT-X - flex.ini` or Windows
`WSJT-X.ini` configuration block).

WIMS and N1MM **join** a multicast group on a chosen interface. If WSJT-X **sends** on a different
interface (or none / loopback), receivers on the contest LAN never see the traffic — even when the
waterfall is full of decodes.

#### Required vs forbidden values

| Outgoing interface value | Fleet status | Notes |
|--------------------------|--------------|--------|
| Contest LAN NIC by name (e.g. `enp13s0f1`, `Ethernet`, `eth0`) | **Required** | Must be the wired L2 segment shared with WIMS / other vehicles |
| Blank / empty | **Error** | Treated as unset |
| `@Invalid()` (Qt placeholder in `.ini`) | **Error** | Common after install or never-touched Reporting tab |
| Loopback / `127.0.0.1` / `lo` | **Error** | Traffic never leaves this PC |
| Wi‑Fi / Starlink / VPN / Tailscale NIC | **Wrong for fleet** | May work intermittently; not the contest LAN map |
| “Default” / unspecified | **Error** | Multi-homed hosts pick the wrong path |

| UDP Server value | Fleet status | Notes |
|------------------|--------------|--------|
| `224.0.0.73` (or band group from map) | **Required** | Open monitoring: WIMS + N1MM + optional GT |
| `127.0.0.1` / `localhost` | **Error** (fleet) | Only this PC; lab-only with `--lab` on the checker |
| Unicast to one app IP | **Warn** | Single consumer; breaks multi-subscriber model |

**Both** must be right: multicast **and** LAN interface. Multicast with `@Invalid()` interface is
still broken.

#### Silent failure (observed)

| Symptom | Cause |
|---------|--------|
| WSJT-X Band Activity full of calls | Decode path is local — **does not prove UDP is correct** |
| WIMS Operate roster missing that instance | No Heartbeat/Status/Decode arrived on WIMS’s join |
| One instance on same PC shows in WIMS, another does not | Often: one is `127.0.0.1` (local unicast reaches WIMS bind) while the other is `224.0.0.73` + unset iface (multicast never lands) |
| GridTracker sees traffic, WIMS does not (or reverse) | Different join interface / port / process; not a substitute for fixing WSJT-X Reporting |

**Lab case (same host):** 6m instance `UDPServer=127.0.0.1` → visible to WIMS; 2m instance
`UDPServer=224.0.0.73` + `UDPInterface=@Invalid()` → decoding on 144 but **zero** UDP to local
listeners. Fix: both instances → `224.0.0.73:2237` (or band ports) **and** Outgoing interface =
LAN NIC (e.g. `enp13s0f1` / `192.168.1.x` segment).

#### How to set it (operator steps)

1. Open the **correct** WSJT-X window (each `--rig-name` has its own settings).  
2. **Settings → Reporting**.  
3. **UDP Server** = `224.0.0.73` (or the group for that band’s stream).  
4. **Port** = band port from §4 table.  
5. **Outgoing interface** = dropdown → **contest LAN Ethernet** (not loopback, not Wi‑Fi).  
6. **Accept UDP requests** = checked if WIMS will control TX later.  
7. OK → **restart that WSJT-X instance** if the UI does not apply UDP changes live.  
8. Confirm on WIMS Status / roster within ~15–30 s (heartbeat period).

Repeat for **every** instance on the host (Trailer 50×3 means three Reporting setups).

#### Multi-homed hosts

Radio PCs often have several addresses (LAN, lab switch, Tailscale, virbr, Wi‑Fi). Rules:

- **WSJT-X Outgoing interface** = contest LAN only (`192.168.10.0/24` in design deployment, or the
  site’s wired digital segment).  
- **WIMS server `--iface`** = same segment’s IP when joining multicast (e.g.
  `--iface 192.168.1.119`), **not** `127.0.0.1` for real hosts.  
- Label the NIC **CONTEST LAN** where possible; disable Wi‑Fi on radio seats during the event.  
- Do not send WSJT-X UDP out Tailscale/Starlink — remote ops use console unicast to the server
  (plane D), not plane A multicast over the internet.

#### Config verification (setup gate)

Run **on each WSJT-X host** (reads all `WSJT-X*.ini` / `WSJT-X - <rig>.ini`):

```bash
python src/wims/integrations/wsjtx_config.py --all
# desk lab only (loopback unicast allowed as warning, not hard error):
python src/wims/integrations/wsjtx_config.py --all --lab
```

| Severity | Condition (fleet mode) |
|----------|-------------------------|
| **error** | `UDPServer` is loopback (`127.0.0.1`) |
| **error** | `UDPInterface` empty, `@Invalid()`, or loopback |
| **warn** | Unicast non-loopback server (single consumer) |
| **warn** | Accept UDP requests off |
| **info** | Interface set — still confirm it is contest LAN, not Wi‑Fi/VPN |

Exit status ≠ 0 if any **error** remains. Setup wizard / seat bring-up (§12) **must not** show 🟢
until this passes (or the same rules embedded in the agent/UI).

Implementation: `src/wims/integrations/wsjtx_config.py` (`validate`, `discover_ini_paths`,
`report`). Unit tests: `tests/unit/test_wsjtx_config.py`.

#### Live monitoring (runtime)

Config file audit is not enough after restarts — also watch the wire:

| Observation | Operator-facing fix |
|-------------|---------------------|
| Expected instance missing on WIMS; host/process up | “Check Settings → Reporting: Outgoing interface = LAN NIC; re-run `wsjtx_config.py --all`” |
| Packets only from `127.0.0.1` | “UDP Server is localhost and/or interface is loopback — set multicast + LAN NIC” |
| Instance ALIVE on WIMS with LAN source IP | Interface path OK for that instance |
| Decodes in WSJT-X, no Status/Heartbeat in WIMS | Almost always Reporting UDP/interface — not RF |

Status / readiness (§12.5) should keep a **Config** strip per seat: last `.ini` audit + live
source-IP class (LAN vs loopback). Wrangler board shows the same string so ops do not need to
understand multicast.

#### Same requirement for WIMS and N1MM (related)

| Component | Interface rule |
|-----------|----------------|
| WSJT-X | Outgoing interface = contest LAN (§4.1) |
| WIMS server | `--iface <LAN-IP>` for multicast join; not `127.0.0.1` for multi-host |
| N1MM External Broadcast dest | Multicast `224.0.0.73:12060` or unicast **WIMS LAN IP**:12060 — not `127.0.0.1` if WIMS is another machine |
| N1MM WSJT reader | Join the band stream on a NIC that receives that multicast (same LAN) |

### N1MM WSJT-X reader (per band)

- Enable WSJT/JTDX UDP reader  
- IP/port = **that band only**  
- Second reader off unless this host also logs another stream  
- Three 6m instances share one port — distinguished by instance id  

### WIMS server

- Join `224.0.0.73` on **2237–2240** (or all four groups if using the alternate scheme)  
- `--iface` = site LAN address (not loopback) for real hosts  
- Observes only; never double-logs  

### GridTracker (optional)

- Join only the band(s) that operator wants to view  
- Viewer only — no Reply/TX on WIMS-managed instances  

---

## 5. Plane B — N1MM external broadcast → WIMS

All four N1MMs publish activity so WIMS can show logger presence and keep the live log copy:

| Setting | Value |
|---------|--------|
| Broadcast Data | Contacts **on**; Radio **on** (presence without a QSO); Spots/Lookup optional |
| Destination | **`224.0.0.73:12060`** (multicast, multi-consumer) **or** unicast `WIMS_LAN_IP:12060` |
| Listener | WIMS (`--n1mm-group 224.0.0.73` when using multicast); optional `integrations/n1mm/listener.py` for capture |

```
  N1MM-50 ──┐
  N1MM-144 ─┼── UDP XML ──►  224.0.0.73:12060  ──►  WIMS
  N1MM-222 ─┤                 (or WIMS_IP:12060)
  N1MM-432 ─┘

  <contactinfo>  → log copy / dupe-mult
  <RadioInfo>    → logger alive (radio not required for presence)
```

Default N1MM destination is often `127.0.0.1:12060` (local only) — change it for multi-host.

---

## 6. Plane C — N1MM networked contest log

```
  N1MM-50  ◄──TCP network──►  N1MM-144
      ▲                          ▲
      └──────────┬───────────────┘
                 │
            N1MM-222 ◄──► N1MM-432

  One contest, one merged DXLOG (unique QSO IDs).
  WIMS: seed/resync from any one networked N1MM .s3db
        + live <contactinfo> from all (plane B).
```

Each N1MM still **only UDP-ingests its band’s WSJT-X** (plane A). Networking merges logs after
local log; it does not replace logger-of-record segregation.

---

## 7. Plane D — operator consoles

```
  [WIMS server]
       │  HTTP :8787  /  SSE /events
       ├──────────► Browser: 6m wrangler   (filter band=50)
       ├──────────► Browser: 2m wrangler   (filter band=144)
       ├──────────► Browser: 222 / 432 ops
       └──────────► Browser: multi-band console (leases)

  GridTracker (optional, per seat):
       joins that seat’s WSJT-X multicast only
       does NOT replace WIMS roster for click-to-work
```

**View is open** (every console can see the fleet). **Control is leased** per instance
(design §4.5): only the lease holder may initiate TX for that instance; no holder → RX-only.

Remote operators: unicast to the **site server** only. Multicast never crosses the internet
(Tailscale is fine because it never carries plane A/B).

---

## 8. Instance ↔ network quick reference

| Instance id (example) | Band | Mode | TX resource group | Multicast | Logger |
|-----------------------|------|------|-------------------|-----------|--------|
| TRAILER-50-A | 50 | FT8 | `50-signal` | `224.0.0.73:2237` | N1MM-50 |
| TRAILER-50-B | 50 | FT8 | `50-signal` | `224.0.0.73:2237` | N1MM-50 |
| TRAILER-50-C | 50 | FT8 | `50-signal` | `224.0.0.73:2237` | N1MM-50 |
| TRAILER-144-FT8 | 144 | FT8 | `144-signal` | `224.0.0.73:2238` | N1MM-144 |
| TRAILER-144-MSK | 144 | MSK/EME | `144-signal` | `224.0.0.73:2238` | N1MM-144 |
| ROY-222-FT8 | 222 | FT8 | `222-signal` | `224.0.0.73:2239` | N1MM-222 |
| ROY-432-FT8 | 432 | FT8 | `432-signal` | `224.0.0.73:2240` | N1MM-432 |

---

## 9. Per-machine checklist

### Each WSJT-X instance
- [ ] Unique `--rig-name` / UDP id  
- [ ] Multicast group + **band port** from §4  
- [ ] **§4.1:** Outgoing interface = contest LAN NIC (not blank / `@Invalid` / loopback)  
- [ ] **§4.1:** UDP Server is fleet multicast, not `127.0.0.1`  
- [ ] `wsjtx_config.py --all` reports **0 errors** on this host  
- [ ] WIMS sees this instance’s heartbeat (LAN source IP, not only local decode window)  
- [ ] Exactly **one** N1MM configured as logger for its stream  

### Each N1MM (50 / 144 / 222 / 432)
- [ ] WSJT UDP reader → **only that band’s** group:port  
- [ ] External broadcast → `224.0.0.73:12060` (or WIMS LAN IP:12060)  
- [ ] Networked into the **same** contest with the other three N1MMs  
- [ ] Station name unique and stable (WIMS logger id)  

### WIMS server
- [ ] Join all WSJT-X ports (2237–2240) on the LAN iface  
- [ ] N1MM XML on :12060 (multicast group if used)  
- [ ] No second app sending Reply on managed instances  

### GridTracker (if used)
- [ ] Same multicast as the band being watched  
- [ ] No TX / “work this call” that bypasses WIMS  

### Host agents (later)
- [ ] One agent per radio / SSB-CW host for 10 ms mute and thumbnails (design §3.3 / §3.4.1)  

---

## 10. Lab vs full contest

| Lab (dev / single host) | Full contest |
|-------------------------|--------------|
| One N1MM (e.g. Windows VM) | Four N1MMs, networked (plane C) |
| One stream (`2237`) + emulator or few WSJT-X | Seven instances, four ports (plane A) |
| Optional GridTracker on the WIMS PC | Optional GT per seat |
| WIMS with LAN `--iface` + `--n1mm-group 224.0.0.73` | Same server role; join all band ports |

Scale path: start with one group:port and one N1MM; **add a port (or group) per band** when a
second logger comes online so double-log never becomes possible.

---

## 11. Design invariants (summary)

1. **Open monitoring** — any number of subscribers on a stream (WIMS, N1MM, GridTracker).  
2. **Singular control** — one logger-of-record per WSJT-X; one TX controller (lease) per managed instance; one rotator controller per rotator.  
3. **WIMS never logs** — path is WSJT-X → N1MM; WIMS reads.  
4. **No unattended TX** — human click + valid lease; else RX-only.  
5. **One signal per band** — multi-instance same band share one resource group.  
6. **Server is site-local for radio UDP** — remote consoles are unicast only.  

Core idea in one line:

> **WSJT-X fans out by band (ports) → one N1MM logs each fan-in → all N1MMs network the log → WIMS joins every fan-in + every N1MM XML → browsers only talk to WIMS.**  
> GridTracker is an optional extra subscriber on a fan-in, never the control path.

---

## 12. Resilience & guided setup (tired operators, restarts)

The networking map in §§1–11 is **correct but brittle** if humans must remember ports, interfaces,
and “don’t enable the wrong N1MM reader.” Seats such as **222 and 432** are often run by operators
who are **not steeped in WIMS design**; people get tired; PCs and radios get restarted mid-contest.
This section is how WIMS stays **safe and diagnosable** under those conditions.

Cross-refs: design §2.5 (network health), §3.3 (setup wizard), §3.14 (profiles), §3.15
(discovery), scenarios S1 / I1–I3.

### 12.1 Problem

| Failure | Typical cause after restart / fatigue |
|---------|--------------------------------------|
| WSJT-X on `127.0.0.1` | Default / “it worked on this PC” |
| **UDP Outgoing interface blank / `@Invalid()`** | Never set after install; **decodes work, WIMS sees nothing** |
| Wrong UDP port (2237 vs 2239) | Config copied from another band |
| N1MM external broadcast still `127.0.0.1:12060` | N1MM factory default |
| N1MM WSJT reader on the **wrong** stream | Both readers on, or trailer ports |
| Two N1MMs logging one instance | Reader “on everything” + networked loggers |
| Duplicate `--rig-name` | Cloned desktop shortcut |
| WSJT-X up, N1MM down (or reverse) | Partial restart |
| WIMS never sees the seat | Server `--iface`, IGMP, wrong port join |
| “Fine locally, dead on console” | Loopback server, unset outgoing iface, or host firewall |

**Principle:** operators never configure multicast arithmetic under stress. They pick a **seat
role** (e.g. `ROY-222`). WIMS applies the profile, verifies the wire, and **names the fix in
plain language**.

Bulletproof here means two things:

1. **Wrong is hard** — defaults, shortcuts, and profiles encode §§4–8 so a reboot does not require
   remembering the map.
2. **Broken is obvious and fixable** — one red light, one sentence, one action (or “call the
   wrangler,” who sees the same sentence).

Quietly wrong (double-log, dual-TX, silent loopback) is worse than loudly red.

### 12.2 How it works (end-to-end)

```
  ┌─────────────────────────────────────────────────────────────┐
  │  Contest profile (server) — expected fleet, once per event  │
  │  seat ROY-222 → id, band, group:port, logger, resource group│
  └───────────────────────────┬─────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
  Seat bring-up          Continuous              Fail-soft
  wizard / Start         readiness               controls
  script applies         (expected vs            (no lease /
  profile to apps        actual on wire)         seat 🔴 → RX only;
         │                    │                  double-log → block)
         ▼                    ▼
  WSJT-X + N1MM  ──UDP──►  WIMS server  ──SSE──►  Status / seat pill
  (plane A/B)            diagnoses              🟢🟡🔴 + fix text
```

**Flow in plain language:**

1. **Before the contest**, someone who understands WIMS writes (or loads) a **contest profile**:
   the seven WSJT-X ids, four N1MM station names, multicast ports, logger-of-record, resource
   groups. That file *is* the networking map in machine-readable form. Operators do not edit it
   mid-event.
2. **At a seat** (especially simple 222/432), the op runs **Bring up ROY-222** (wizard or desktop
   shortcut) — not “configure UDP.” Optionally WIMS/agent **writes or verifies** WSJT-X `.ini` and
   N1MM reader/broadcast settings against the profile.
3. **Apps start** and emit the usual multicast (plane A) and N1MM XML (plane B).
4. **WIMS server** — already joining every stream — **passively compares wire traffic to the
   profile** (design §3.15). No Wireshark; no op-interpreted packet counters as the primary UX.
5. **Seat readiness** collapses that comparison into a traffic light plus **one named fault and
   one next step** (e.g. “N1MM-222 not heard — External Broadcast is probably still 127.0.0.1”).
6. **Operate path** only trusts seats that are safe: no valid lease / seat not READY → **RX only**;
   suspected double-logger or id collision → **do not command TX** until cleared.
7. **After any reboot**, the same comparison re-runs within about a heartbeat or two (~30 s). The
   op does not re-run a mental checklist; they look for **green**.

Simple seats (1 N1MM + 1 WSJT-X) are the **first** path to productize. Trailer multi-instance
remains band-captain territory but uses the **same** readiness engine and fault vocabulary.

### 12.3 Contest profile (source of truth)

Declared once on the server (YAML/JSON or setup UI). Example shape:

```text
seat ROY-222:
  band: 222
  wsjtx_id: ROY-222-FT8
  multicast: 224.0.0.73:2239
  logger_station_name: N1MM-222    # N1MM StationName as seen on plane B
  resource_group: 222-signal
  host_hint: optional IP/MAC

seat ROY-432:
  band: 432
  wsjtx_id: ROY-432-FT8
  multicast: 224.0.0.73:2240
  logger_station_name: N1MM-432
  resource_group: 432-signal
```

Trailer seats add multiple `wsjtx_id`s sharing one `resource_group` and one logger. The profile
feeds:

| Consumer | Use |
|----------|-----|
| Expected-vs-actual board | Which rows *must* appear |
| Seat wizard | What to apply/verify on that PC |
| Logger invariant checks | Exactly one logger per id |
| Arbiter | Resource group membership |
| Watchdog baselines | Later: quiet/dead thresholds per mode |

Instance Profiles (§3.14) are the rich form of the same data; the contest profile is the
**fleet-level** package for one event.

### 12.4 Guided seat bring-up (how setup works)

Target UX for 222/432 — **at most four steps**:

| Step | What happens |
|------|----------------|
| 1. Who am I? | Op picks seat from the profile list (`ROY-222`), not free-text ports |
| 2. Apply / verify | Write or check WSJT-X config (**group, port, Outgoing interface = LAN NIC**, rig-name) and N1MM (WSJT reader → that stream only; External Broadcast → `224.0.0.73:12060` or WIMS IP). **Refuse green** if `UDPInterface` is empty/`@Invalid`/loopback or `UDPServer` is `127.0.0.1` in fleet mode |
| 3. Live prove (30–60 s) | WIMS must see: (a) heartbeat for expected `wsjtx_id` from a **non-loopback** source IP when seat is multi-host, (b) any N1MM XML from expected StationName, (c) no second logger claiming that id, (d) no id collision |
| 4. Result | 🟢 READY or 🔴 + **one sentence + one action** |

**Mandatory WSJT-X checks in step 2** (same rules as `wsjtx_config.validate`, fleet mode):

| Check | Error text (operator-facing) |
|-------|------------------------------|
| No UDP Server | “WSJT-X is not reporting over UDP” |
| UDP Server = `127.0.0.1` | “Set UDP Server to 224.0.0.73 (fleet multicast), not localhost” |
| Outgoing interface blank / `@Invalid()` | “Select the contest LAN network interface under Settings → Reporting” |
| Outgoing interface = loopback | “Interface is loopback — pick the Ethernet/LAN NIC so WIMS can see this radio” |
| Accept UDP requests off | Warning: “WIMS cannot Reply/Halt until Accept UDP requests is on” |

Implementation paths (progressively stronger):

1. **Read-only validate** — `integrations/wsjtx_config.py` (`.ini` parse + severity); host agent or
   setup page runs `--all` / embeds the same rules.
2. **Apply config** — write known-good UDP Server / port / **interface** / AcceptUDP, then prompt
   restart of WSJT-X/N1MM.
3. **Seat shortcuts** — desktop `Start ROY-222` launches WSJT-X with `--rig-name=ROY-222-FT8` and
   the correct config directory so the op never opens a generic WSJT-X.
4. **Start script order** — N1MM → wait → WSJT-X → open seat status URL (reduces partial-start
   confusion).

Design scenarios I1–I3 are the full role installers (agent + mute + server). **Seat bring-up** is
the shorter, contest-day path those installers should leave behind.

### 12.5 Continuous readiness (how diagnosis works)

Readiness is **not** install-only. The server always maintains, per seat / expected instance:

| Light | Meaning |
|-------|---------|
| 🟢 READY | Expected WSJT-X ALIVE; expected N1MM heard; logger-of-record matches; no double-logger; no id collision |
| 🟡 DEGRADED | Alive but QUIET (no decodes); N1MM idle; advisory only; or within post-reboot grace |
| 🔴 BROKEN | Missing, STALE/DEAD, loopback-only source, wrong stream, id collision, double-log risk |
| ⚪ OFF | Seat disabled / not in this contest profile |

**Fault messages must be operator-facing**, not expert-only, for example:

- `ROY-222-FT8 missing — last seen 12m ago from 192.168.10.42`
- `N1MM-222 not heard on :12060 — is External Broadcast still 127.0.0.1?`
- `WSJT-X id ROY-222-FT8 also from 192.168.10.99 — duplicate rig-name`
- `N1MM-50 appears to be logging ROY-222-FT8 — disable that reader on N1MM-50`
- `WSJT-X only seen from 127.0.0.1 — set UDP Server to multicast and Outgoing interface to the contest LAN NIC`
- `Expected ROY-222-FT8 absent but host is up — run config check: Outgoing interface may be blank/@Invalid`

**Evaluation inputs** (all passive unless a self-test is requested):

| Signal | Source | Proves |
|--------|--------|--------|
| Heartbeat / Status | Plane A, parsed by WIMS | Instance up, id, host, band/freq |
| Packet **source IP** | Plane A recvfrom | LAN vs loopback — `127.0.0.1` ⇒ iface/server misconfig |
| Decode stream | Plane A | Not QUIET (RF path alive) |
| Host `.ini` audit | `wsjtx_config` on agent / setup | UDP Server + **Outgoing interface** before/while live |
| `<RadioInfo>` / any N1MM XML | Plane B | Logger process up (no QSO needed) |
| `<contactinfo>` | Plane B | Logging path works when QSOs happen |
| Profile row | Contest profile | What *should* be true |
| Id from ≥2 hosts | Discovery | Collision |
| Unexpected logger | contactinfo/station vs profile | Double-log risk |

**Config monitor (not only live UDP):** the Status / readiness UI should expose a **Config**
strip per seat — last `.ini` audit result (pass/fail + first error). Agents re-scan on a slow
timer or on “Retest seat”; wrangler can see “IC9700: iface @Invalid” even when the operator
insists the waterfall looks fine.

**Wrangler console:** one board of all seats 🟢🟡🔴; click seat → same fix text the local op sees.
Fatigue-friendly coordination: op says “222 is red”; wrangler already knows why.

**Post-reboot grace:** ~60 s of 🟡 “coming up” after a host reappears, so generator blips do not
page the site with false 🔴 storms.

**Quiet vs dead:** heartbeats but no decodes → RF/antenna/band problem; no heartbeats →
app/network/config problem. Wording must distinguish these so people do not reboot the PC for a
dead band opening.

### 12.6 Fail-soft (how safety works when setup is wrong)

| Condition | Behavior |
|-----------|----------|
| No control lease | Instance **RX only** (design §4.5) — no unattended TX |
| Seat 🔴 BROKEN (missing instance, collision, double-log) | Do not honor click-to-work; banner explains why |
| N1MM missing, WSJT-X ok | Policy: roster may still show decodes; 🟡 “log may not record”; optional hard-block TX if contest requires logging |
| WIMS server restart | Re-join multicast, re-seed/resync log, rediscover fleet in seconds; consoles reconnect; **SSB/CW mute path stays on host agents** (not via server) |
| Zombie console | Stale lease → another console can take over; old commands rejected |

Safety does not depend on every seat staying green forever; it depends on **never silently TX or
double-log while red**.

### 12.7 Simple seats vs complex seats

| | 222 / 432 (simple) | Trailer 50 / 144 (complex) |
|--|--------------------|----------------------------|
| Profile | One id, one logger, one port | Multiple ids, shared resource group, geometry |
| Bring-up | “One band, one radio” wizard | Band captain + multi-instance checks |
| Training | ~2 minutes + wall card | Experienced digital op |
| Same engine? | Yes — readiness + faults | Yes — more expected rows |

**Ship guided setup for simple seats first** — highest ROI for operators who do not know WIMS
internals. Trailer uses the same lights and fault language so the site has one diagnostic culture.

### 12.8 Make misconfig hard (defaults & packaging)

| Measure | Effect |
|---------|--------|
| Seat desktop shortcuts with fixed `--rig-name` + config dir | Reboot does not invent a new UDP id |
| Pre-baked contest image / USB per role | Ports and iface already correct |
| N1MM settings export documented per seat | Broadcast + reader restored as a blob |
| Refuse “looks local only” for multi-host seats | 🔴 if traffic only from 127.0.0.1 when profile expects LAN |
| Physical wall card | `1 Start ROY-222  2 Wait for green  3 If red, open URL / call wrangler` |
| Optional golden NIC label | “CONTEST LAN” only; Wi‑Fi off on radio PCs |
| Unmanaged L2 on digital segment | Avoid IGMP snooping pruning multicast |

Software readiness still catches failures; packaging reduces how often the light goes red.

### 12.9 Self-test (optional active check)

When passive wait is not enough (or at end of wizard step 3):

1. Operator clicks **Test seat** (no RF required for network proof).  
2. WIMS waits up to N seconds for heartbeat + N1MM presence matching the profile.  
3. If agent present: optional deeper checks later (mute test-fire, process up).  
4. Result written as the current readiness state + fix text.

Active probes (ping host, etc.) are secondary; **protocol-aware passive proof** is primary because
it tests the real path WIMS uses in the contest.

### 12.10 What the tired operator should experience

```text
Reboot PC → double-click "ROY-222" → wait for green pill on
http://<wims>/status (seat ROY-222) → work the band.

If red: read one sentence. Do one thing.
Or say "222 is red" — wrangler sees the same sentence.
```

They never need to know that 222 is `224.0.0.73:2239`. That knowledge lives in the profile and in
the fix text when something drifts.

### 12.11 Build order (minimum viable resilience)

Aligns with design modules; prefer server-side value before perfect agents:

| Priority | Deliverable | Depends on |
|----------|-------------|------------|
| 1 | Contest profile (even hand-edited) listing all expected instances + loggers | Config §3.11 / §3.14 |
| 2 | Expected-vs-actual board on Status with **plain-language** discrepancies | Discovery §3.15 (partially built) |
| 3 | Per-seat readiness 🟢🟡🔴 + one fix string (API + UI) | Profile + discovery |
| 4 | **WSJT-X config validator** as gate: multicast + **LAN Outgoing interface** + not loopback (`wsjtx_config`; **tool exists**); surface on Status | I1 |
| 5 | N1MM broadcast/reader vs profile (read-only) | N1MM settings |
| 6 | Simple-seat wizard (222/432): pick seat → **ini check** → prove wire → green | 3 + 4 |
| 7 | Start scripts / rig-name shortcuts per seat | Packaging |
| 8 | Auto-apply config (including interface name from profile), topology map, agent re-scan | Agent §3.3 |

Until multi-port join exists in code (status tracker), lab readiness can still validate a
**subset** profile (one port); full four-port expected fleet lights up when the server joins
2237–2240.

### 12.12 Dress rehearsal

Treat S1 (cold start readiness) as a **drill**, not only a design scenario:

1. Full power-down of a simple seat (and later Trailer).  
2. Cold start with only seat shortcuts + WIMS status.  
3. Measure **time-to-green** and whether a non-author op can clear reds from fix text alone.  
4. File every failure that required expert folklore back into profile defaults or fix strings.

---

**Resilience one-liner:**

> **Encode the networking map in a contest profile; give each seat a start action and a continuous
> green light; make WIMS name the fix; refuse to TX or double-log while red.**
