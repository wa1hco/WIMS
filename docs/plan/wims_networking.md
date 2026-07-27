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

**Invariant:** one **N1MM per band** is the **logger-of-record** for that band’s WSJT-X stream(s).
WSJT-X hosts may sit **on a different PC or site** than their N1MM as long as they share the
**contest LAN** (plane A multicast). N1MM does **not** need to co-reside with every radio.

```
50 MHz (band port 2237) — one common N1MM-50
├── Host(s) at TRAILER (and/or other on-site PCs)
│   ├── WSJT-X  TRAILER-50-A   FT8   (e.g. fixed beam az₁)
│   └── WSJT-X  TRAILER-50-B   FT8   (e.g. fixed beam az₂)   … count may vary
│
└── Host at REMOTE SITE (e.g. TV station tower / separate building)
    └── WSJT-X  TV-50-C        FT8   (own PC + radio; same band stream)
        → still logged only by N1MM-50 (not a second N1MM)

144 MHz (band port 2238) — one common N1MM-144
├── PC + radio  WSJT-X  TRAILER-144-FT8    FT8
└── PC + radio  WSJT-X  TRAILER-144-MSK    MSK144  (or EME / Q65)
    → separate hosts/radios OK; both join 2238; only N1MM-144 ingests

222 MHz (band port 2239) — one N1MM-222 + one seat PC (e.g. Roy)
└── Same PC may run SSB/CW (N1MM voice/CW) and/or WSJT-X FT8 when digital
    (not always FT8; mode is operator choice for the period)

432 MHz (band port 2240) — one N1MM-432 + one seat PC (e.g. Roy)
└── Same pattern as 222: one PC, SSB and/or FT8 as equipped
```

| | Typical count (contest-dependent) |
|--|------:|
| Digital bands with N1MM | **6** possible (50, 144, 222, 432, 902, 1296) — sparse OK |
| N1MM (one per band) | **1 per active digital band** |
| WSJT-X on 50 | **1–N** (trailer beams + optional remote site e.g. TV station) |
| WSJT-X on 144 | **1–N** (e.g. FT8 PC + MSK/EME PC) |
| WSJT-X on 222 / 432 / 902 / 1296 | **0 or 1** each (SSB-only periods have N1MM only) |

**TX resource groups (one radiated signal per band, multi-multi):**

| Band | Instances / radios | Resource group | Notes |
|------|--------------------|----------------|--------|
| 50 | All 50 MHz WSJT-X (local + remote, any dual-RX FT8+MSK pairs) | `50-signal` | At most one of them TX; **includes TV-station radio** if on the air |
| 144 | FT8 PC + MSK PC (if both live) | `144-signal` | At most one TX even across two PCs |
| 222 | one seat radio | `222-signal` | SSB or FT8 — same physical chain |
| 432 | one seat radio | `432-signal` | SSB or FT8 — same physical chain |

Instance ids are examples; convention is `SITE-BAND[-role]` via WSJT-X `--rig-name`
(unique UDP `id` — required; IP alone is not enough when two instances share a host).

### 1.0 Fleet host seats (typical co-located VMs)

Networking allows split hosts (§1.1); **fleet VMs** are usually named by host/seat and run
N1MM + that seat’s radios together. After clone: set **hostname** + `WIMS_SEAT_ID` to the seat
name, then define every WSJT-X **`--rig-name`** (UDP `id`) for instances on that host.

```
TRAILER-50  (host / N1MM-50)          4 radios
├── Radio SSB/CW                      (no WSJT-X; later: agent mute peer)
├── Radio A  fixed az₁  dual-RX       WSJT instance(s) — see dual-RX note
├── Radio B  fixed az₂  dual-RX       …
└── Radio C  fixed az₃  dual-RX       …

TRAILER-144 (host / N1MM-144)         3 radios
├── Radio SSB/CW
├── Radio WSJT FT8                    one WSJT-X (FT8)
└── Radio WSJT MSK                    one WSJT-X (MSK144 dedicated)

ROY-222     (host / N1MM-222)         1 radio
└── Radio shared                      switches SSB/CW ↔ WSJT-X (one instance when digital)

ROY-432     (host / N1MM-432)         1 radio
└── Radio shared                      switches SSB/CW ↔ WSJT-X (one instance when digital)
```

#### Recommended `--rig-name` (UDP id) table

Convention: `HOST-ROLE` or `HOST-AZ-MODE` — unique fleet-wide; no spaces.

| Host (VM / seat id) | Physical radios | WSJT-X `--rig-name` (UDP id) | Mode(s) | Notes |
|---------------------|-----------------|------------------------------|---------|--------|
| **TRAILER-50** | 1× SSB/CW | — | SSB/CW | Not a WSJT instance; interlock peer later |
| | 3× WSJT, fixed az, dual-RX | **`TRAILER-50-A`**, **`TRAILER-50-B`**, **`TRAILER-50-C`** | FT8 primary | One instance per radio if single mode |
| | same 3 radios, dual-RX FT8+MSK | **`TRAILER-50-A-FT8`**, **`TRAILER-50-A-MSK`**, … (×3 radios) | FT8 + MSK144 | Two instances **per radio** if both modes live at once |
| **TRAILER-144** | 1× SSB/CW | — | SSB/CW | |
| | 1× WSJT FT8 | **`TRAILER-144-FT8`** | FT8 | |
| | 1× WSJT MSK | **`TRAILER-144-MSK`** | MSK144 | Dedicated MSK radio |
| **ROY-222** | 1× shared | **`ROY-222-FT8`** (or `ROY-222`) | FT8 when digital | Same radio as SSB/CW — op/mode switch |
| **ROY-432** | 1× shared | **`ROY-432-FT8`** (or `ROY-432`) | FT8 when digital | Same radio as SSB/CW |
| **TV / remote 50** | remote radio | **`TV-50-C`** (example) | FT8 | WSJT only; still logged by **N1MM-50** (§1.1) |

**Dual-RX (50):** if a radio runs FT8 and MSK144 **at the same time**, that is **two WSJT-X processes**
(two rig-names) sharing one TX resource (one PA/antenna) — arbiter must treat them as one
resource group for TX (`50-signal`). If the op only ever runs one mode at a time, a **single**
rig-name per radio is enough and mode is changed inside WSJT-X.

Baseline **instance count** if 50 runs three radios FT8-only + 144 has FT8+MSK + 222 + 432:

| | Count |
|--|------:|
| Hosts / N1MM seats (co-located model) | 4 (+ optional remote WSJT-only hosts) |
| SSB/CW radios | 4 (one per host; 222/432 share the box with digital) |
| WSJT-X instances (min) | **3 + 2 + 1 + 1 = 7** |
| WSJT-X if 50 dual-RX both modes live | **6 + 2 + 1 + 1 = 10** |

SSB/CW on 50/144 is a **separate radio** (not in the WSJT instance list) but same-band priority
still applies for the 10 ms mute path (design §3.4.1). On 222/432, SSB/CW and WSJT share one radio.

#### After cloning a template VM

1. Set **Windows hostname** = seat name (`TRAILER-50`, …).  
2. Set **`WIMS_SEAT_ID`** in `seat-local.cmd` to the same string.  
3. Create **desktop/startup shortcuts** (or seat apply later) for each WSJT-X with the
   **`--rig-name=`** values above — **do this before** relying on the dashboard.  
4. Each instance: UDP `224.0.0.73`, **band port** (§4), Outgoing interface = LAN.  
5. N1MM on that host: Station/computer name unique; WSJT reader joins **only that band’s port**.

### 1.1 Split site: remote WSJT-X, common N1MM (50 MHz TV station, etc.)

```
  TV-station PC                    Trailer / central site
  ┌─────────────────┐              ┌──────────────────────┐
  │ WSJT-X TV-50-C  │──mcast:2237──│ N1MM-50 (reader)     │
  │ own radio/PA    │              │ only logger for 50   │
  └─────────────────┘              │ WIMS joins 2237 too  │
         ▲                         └──────────────────────┘
         │ contest LAN (same L2 as trailer)
         └──── must NOT use a second N1MM on the TV PC for this band
```

| Rule | Why |
|------|-----|
| Remote PC runs **WSJT-X only** for that band (optional local agent / GT viewer) | Avoids double-log |
| **N1MM-50** (one machine) enables the WSJT UDP reader on **2237** | Sole logger-of-record |
| Both PCs: UDP Server = fleet multicast, **Outgoing interface = contest LAN NIC** | Silent-failure trap §4.1 |
| Same **Contest LAN** (wired L2 or equivalent) between TV site and N1MM/WIMS | Multicast does not cross the public internet |
| Unique `--rig-name` (e.g. `TV-50-C`) | WIMS and N1MM distinguish instances |

If the remote site **cannot** join the contest L2, it is **out of scope for plane A** until a
relay is designed (not default). Unicast-to-N1MM-only without WIMS is a manual exception, not the
fleet map.

### 1.2 Dual PC on one band (144 FT8 + MSK144)

```
  PC-144-FT8 ──WSJT-X──┐
                       ├── 224.0.0.73:2238 ──► N1MM-144 (only reader)
  PC-144-MSK ──WSJT-X──┘                    ──► WIMS (observer)
```

- Separate **radio + PC** per mode is expected; **one N1MM-144** still owns the log.  
- Interlock / resource group `144-signal` still means at most one radiated TX on 144.  
- Do **not** run a second N1MM WSJT reader on either 144 PC.

### 1.3 Single-PC seats (222 / 432)

- One host runs **N1MM** for that band and, when digital, **one WSJT-X**.  
- Periods of **SSB/CW only** are normal: N1MM up, no WSJT-X instance (WIMS shows logger via
  plane B RadioInfo; no digital instance until FT8 starts).  
- When FT8 is active, same rules as any other band (multicast + unique id + iface).

**Microwave / UHF extend the same pattern:** 902 and 1296 use the same dual-consumer stream model
as VHF (§4). Seats may be sparse (0–1 WSJT-X) until wired; the stream still exists in the
registry so WIMS and N1MM config stay uniform.

---

## 2. Physical / roles

```
                    ┌──────────────────────────────────────────┐
                    │   Contest LAN (one L2 domain)            │
                    │   wired across trailer, Roy, remote 50…  │
                    └──────────────────────────────────────────┘
         │              │              │              │              │
    TRAILER 50       TRAILER 144    TV / remote 50   222 seat      432 seat
    (N1MM-50 +       (N1MM-144 +    (WSJT-X only     (N1MM-222 +   (N1MM-432 +
     local WSJT-X)    FT8 PC +       for 50; no        one PC,       one PC,
                      MSK PC)        second N1MM)      SSB and/or    SSB and/or
                                                       FT8)          FT8)

              ┌──────────────────────────┐
              │  WIMS SERVER (site)      │
              │  joins ALL radio UDP     │
              │  serves browser consoles │
              └──────────────────────────┘
                         │
              HTTP/SSE (unicast) → operator browsers
              (LAN or Tailscale; no multicast over WAN)
```

| Role | Where it runs | Notes |
|------|---------------|--------|
| **N1MM-50** | Central/trailer (typical) | Logger for **all** 50 MHz WSJT-X, including TV station |
| **WSJT-X 50** | Trailer PC(s) and/or TV-station PC | Radio lives with the WSJT-X host |
| **N1MM-144** | Trailer (typical) | Logger for both 144 FT8 and MSK PCs |
| **WSJT-X 144** | One PC per radio/mode | May be two hosts |
| **N1MM+WSJT 222/432** | Same seat PC | SSB and/or FT8 on that radio |

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
- **Radio CAT / PTT / USB audio** are **not** WIMS planes. They are **seat-local** under the
  radio host (see **§3.2** / **§3.3**). WIMS never opens the radio’s COM port and never speaks
  CI-V or Hamlib to the rig; it talks only to **WSJT-X over plane A** (and N1MM over plane B).

### 3.1 Plane E — site-server presence (zero-memory discovery)

**Problem:** two `wims.server` processes = two divergent log/roster brains; operators must not
memorize or type the server IP.

**Announce (site server, ~1 Hz, same JSON body on every path):**

| Path | Target | Why |
|------|--------|-----|
| Multicast | `224.0.0.73:8788` on **each** non-loopback IPv4 NIC | Same LAN story as WSJT-X |
| Limited broadcast | `255.255.255.255:8788` | Often reaches Windows VMs when mcast is broken |
| Directed broadcast | e.g. `192.168.1.255:8788` per NIC /24 | Subnet-local flood |

TTL 3. Prefer `--iface <contest-LAN-IP>` for radio UDP; presence is multi-homed regardless.

**Payload (schema 1):** `kind=wims-server`, `role=wims-site-server`, `instance_id`, `hostname`,
`lan_ips`, `http_port`, `console_base`, `urls.{operate,status,setup,healthz}`, `started_ts`, `seq`.

**HTTP assist:** `GET /healthz` returns the same identity (`role`, `console_base`, `urls`) so agents
can find the server even when **all** UDP presence is blocked.

**Server dual-primary:**

1. Listen ~2.5 s for a live peer beacon (UDP).
2. Peer heard → **refuse** start (exit 2) with peer URL (unless `--force-server`).
3. Else become primary and announce on all paths.
4. Keep listening; second primary → **demote** (exit 2).

**Agent discover cascade (no operator IP knowledge):**

1. UDP listen (multicast join per NIC + broadcast) ~2.5 s.
2. If none: HTTP probe local /24s on TCP **:8787** `/healthz` (likely hosts first, then full /24).
3. Print Operate/Status/Setup URLs; local UI `:8790` shows clickable buttons.
4. `WIMS_SERVER` is an **escape hatch only**, not the normal path.

**Not solved:** internet discovery without a LAN path; automatic HA failover; auth.

**Code:** `src/wims/discovery/presence.py` · server `--presence-*` / `--no-presence` /
`--force-server` · agent `--no-discover`.

### 3.2 Seat-local radio control (CAT / PTT / audio) — not a WIMS plane

WIMS treats **WSJT-X as the radio adapter** for digital:

| Direction | Mechanism | Who owns it |
|-----------|-----------|-------------|
| **Ingest** | Heartbeat / Status / Decode / QSO Logged (plane A) | WSJT-X → WIMS / N1MM / optional GT |
| **Control** | Reply / Halt Tx (plane A UDP) | WIMS → WSJT-X only |
| **CAT / PTT / dial QRG** | Serial, TCP, Hamlib, rigctld, manufacturer middleware | **Seat only** — outside WIMS |
| **TX audio** | Sound device / radio USB codec | Seat WSJT-X host |
| **Fast 10 ms mute** (fleet later) | Host-agent audio gain / hardware gate | Seat agent — **not** CAT round-trip |

**Invariant:** one process (or one deliberate middleware stack) **owns** the radio’s exclusive
COM/USB CI-V path. A second logger or second digital app must **not** open the same COM port
directly. Sharing is done via **middleware** (wfview, Win4Icom, virtual ports, etc.), not by
pointing two apps at the same Windows COM device.

**Do not** use N1MM’s built-in **Window → Load WSJT/JTDX** / “DX Lab Suite Commander” rig-proxy
path on WIMS-managed seats. That path makes N1MM the CAT master for WSJT-X and fights the
model below (WSJT-X owns digital TX; N1MM owns the log; WIMS owns fleet UDP + arbiter).

**PTT timing vs design §1.1 / §3.4.1:**

- **Slow path (always):** WIMS **Halt Tx** → WSJT-X stops feeding the audio buffer → PTT drops
  via whatever path WSJT-X uses (CAT through middleware is fine). Dominated by audio drain +
  PTT release (tens–hundreds of ms), not LAN RTT.
- **Fast path (SSB/CW priority):** mute **TX audio on the WSJT-X host** (agent), independent of
  CAT middleware. CTS-based SSB/CW sense is also outside the CAT stack.

**Frequency truth for digital roster:** WIMS uses dial frequency primarily from **WSJT-X Status
UDP** (plane A). N1MM RadioInfo (plane B) is for logger presence / SSB seats. CAT through
middleware must keep WSJT-X Status accurate; N1MM poll lag is secondary for FT8 S&P.

### 3.3 Preferred Icom USB seat: wfview

For Icom radios that present dual Silicon Labs COM ports over USB (e.g. **IC-9700**, IC-7300,
IC-705/7610 family patterns), the preferred seat stack is:

```
IC-9700 (or other Icom USB)
   ↑ USB CI-V + USB Audio
wfview  (only process on real radio COM / LAN control)
   ├── RigCtld (Hamlib)  127.0.0.1:4533  ──► WSJT-X   (freq + PTT + mode)
   └── TCP CI-V server   127.0.0.1:<port> ──► N1MM    (frequency / mode poll)
WSJT-X
   └── Plane A multicast 224.0.0.73:<band-port> ──► WIMS + N1MM WSJT reader + optional GT
N1MM
   └── Plane B XML 224.0.0.73:12060 ──► WIMS
```

**Roles:**

| Component | Owns | Does not own |
|-----------|------|----------------|
| **wfview** | Real USB COM (or radio LAN); optional scope/waterfall | Contest log; Reply/Halt fleet control |
| **WSJT-X** | Digital TX, Fake It / split, plane A UDP, USB audio codec | Exclusive COM if wfview is in use |
| **N1MM** | Contest log; plane B; optional CAT **freq** via wfview TCP | Digital TX; plane A Reply; dual COM open |
| **WIMS** | Plane A join + Reply/Halt; plane B log copy; console | Any direct radio CAT / COM |

This is **consistent** with WIMS design: middleware is a **seat implementation detail** of the
instance profile “CAT path” (design §3.14), not a WIMS server feature.

#### 3.3.1 Radio menus (IC-9700 pattern; adapt model names)

USB CI-V is **not** the same as the rear **[REMOTE]** jack baud.

| Menu (SET → Connectors → CI-V) | Value | Why |
|--------------------------------|-------|-----|
| **CI-V USB Port** | **Unlink from [REMOTE]** | If linked, USB is capped at REMOTE max (often **19200**) |
| **CI-V USB Baud Rate** | **115200** or **Auto** | Match wfview serial baud |
| **CI-V Baud Rate** (REMOTE jack) | 19200 OK | Irrelevant to USB CAT when unlinked |
| **CI-V Transceive** | **ON** | Required for many middleware / polling clients |
| **CI-V Address** | Default (9700 = **A2h**) | Leave unless fleet-standardized |

Device Manager shows **two** COM ports (A/B). Use **port A** (usually the **lower** number) for
CAT. Port B is not the primary CI-V path.

#### 3.3.2 wfview

1. Connect to the radio (**Serial/USB** or LAN). Confirm VFO tracks. **Save Settings**.
2. **Settings → External Control** (wording may vary by version):
   - **Enable RigCtld** → **ON**, port **4533** (default). **Connection refused** from WSJT-X
     means this box is off — radio connect alone does **not** start the TCP server.
   - **Enable TCP server** (raw CI-V for N1MM) → **ON**, port e.g. **1025** or **4537**
     (**not** 4533; not radio LAN 50001–50003).
3. Save; restart wfview if the TCP/rigctld options were just enabled; reconnect radio.
4. Confirm with `netstat` (or equivalent) that **4533** (and the N1MM TCP port) are **LISTENING**.

Only **wfview** may open the radio’s real COM ports. No WSJT-X, N1MM, HRD, or OmniRig on COM3/4
while wfview is connected.

#### 3.3.3 WSJT-X (digital + plane A)

**Radio tab**

| Setting | Value |
|---------|--------|
| Rig | **Hamlib NET rigctl** |
| Network Server | **`127.0.0.1:4533`** (match RigCtld port) |
| PTT Method | **CAT** |
| Mode | **Data/Pkt** (or USB if radio has no data mode) |
| Split Operation | **Fake It** first; try **Rig** if needed |

Do **not** set Rig to the Icom model + real COM while wfview owns the port.  
Do **not** set Rig to **DX Lab Suite Commander** (N1MM integration path).  
Do **not** point Network Server at radio LAN ports (**50001 / 50002 / 50003**).

**Audio:** radio **USB Audio CODEC** (when on USB); DATA MOD = USB on the radio as usual.

**Reporting tab (plane A — band port from §4)**

| Setting | Value |
|---------|--------|
| UDP Server | **`224.0.0.73`** |
| UDP Server port | **Band stream port** (§4.3): 50→**2237** … 1296→**2242** (or registry) |
| Accept UDP requests | **ON** (WIMS Reply / Halt) |
| Outgoing interface | Contest LAN NIC (§4.8) — mandatory on multi-homed / fleet seats |
| Secondary UDP / N1MM Logger+ Broadcasts | **OFF** if N1MM already reads this band’s multicast stream (avoids double-log) |

**`--rig-name`:** unique fleet-wide UDP `id` (e.g. `TRAILER-144-FT8`).

#### 3.3.4 N1MM (logger + optional freq)

| Concern | Setting |
|---------|---------|
| **CAT / frequency** | Port type **TCP**, address **`127.0.0.1:<wfview-tcp-port>`**, radio model = actual rig (e.g. IC-9700). Not COM3/4. |
| **WSJT UDP reader** | **Only this band’s** `224.0.0.73:<band-port>` (e.g. N1MM-144 → **2238**) |
| **Broadcast Data** | Contacts + Radio → **`224.0.0.73:12060`** (plane B for WIMS) |
| **Load WSJT/JTDX** | **Do not use** on WIMS-managed digital seats |

Leave CW/PTT on N1MM’s radio port off when WSJT-X owns digi TX via CAT.

#### 3.3.5 WIMS and GridTracker on a wfview seat

| App | Join | Notes |
|-----|------|--------|
| **WIMS server** | `--group 224.0.0.73 --port <band-port>` | Solo 2 m example: **`--port 2238`**. Default CLI port is 2237 — wrong for 144 if left unchanged. Multi-port join (2237–2240) is design intent; until implemented, match the seat’s band port or run one process per port. |
| **GridTracker** | Same group:port as the band being watched | **Viewer only** on managed instances — no click-to-work (bypasses TX arbiter, design §1.2 / §4.3) |

#### 3.3.6 Start order

1. **wfview** — connected; RigCtld ON; TCP server ON  
2. **WSJT-X** — Test CAT green; decoding; plane A settings applied  
3. **N1MM** — freq tracks; WSJT reader on band port  
4. **WIMS** — roster fills; `--port` matches WSJT-X  
5. **GridTracker** (optional) — view-only  

#### 3.3.7 Instance profile fields (CAT stack — design §3.14)

Record middleware explicitly so seat clones and readiness checks do not assume “direct COM”:

| Profile field | Example (IC-9700 + wfview) |
|---------------|----------------------------|
| Rig model | IC-9700 |
| CAT middleware | **wfview** (owns USB COM A) |
| WSJT-X CAT | Hamlib NET `127.0.0.1:4533` (RigCtld enabled) |
| N1MM CAT | TCP `127.0.0.1:<tcp>` (freq only) |
| PTT method | CAT (via wfview) |
| Forbidden | Second app on real COM; N1MM Load WSJT rig proxy |

Other valid CAT path enums for profiles: `direct-com` · `wfview-rigctld` · `win4icom` ·
`win4yaesu` · `lp-bridge` · `flex-smartsdr-cat` · `vspe-pair` · `other-middleware`.

#### 3.3.8 Quick faults (wfview seats)

| Symptom | Likely cause |
|---------|----------------|
| WSJT-X Test CAT “connection refused” | RigCtld not enabled / not LISTENING on 4533 |
| Test CAT fails; using `:50002` | Radio LAN port — use **`127.0.0.1:4533`** only |
| Radio “only offers 19200 baud” | Looking at REMOTE **CI-V Baud Rate**; set **Unlink** + **CI-V USB Baud Rate** |
| N1MM cannot open radio | Pointed at COM while wfview holds it — use wfview **TCP** |
| WIMS roster empty; waterfall full | Plane A port mismatch (e.g. WSJT-X **2238**, WIMS still **2237**) or §4.1 outgoing iface |
| Double QSOs in N1MM | Multicast reader **and** Secondary UDP 2333 both logging |

---

## 4. Plane A — dual-consumer band streams (WSJT-X → N1MM-band + WIMS)

This section is the **normative design** for multi-band digital: *N* WSJT-X instances on a band
log only through **that band’s N1MM**, while **all** instances still feed **one** WIMS site server
for decode lists / roster / Reply.

### 4.0 Problem statement

| Need | Constraint |
|------|------------|
| **N WSJT-X per band** (beams, dual-RX modes, remote site) | Distinct radios / PCs / modes |
| **Log only to that band’s N1MM** | Exactly **one** logger-of-record per instance (no double-log) |
| **All decodes → common WIMS** | One site roster / arbiter / console |
| **Bands 50 → 1296 MHz** | Same rules for sparse microwave seats |
| **Minimal one-band setup looks familiar** | Defaults should feel like “just turn on FT8” |
| **Ports are hard to remember** | If WIMS guides or applies config, ports need not be sequential |

### 4.1 Dual consumers of one band stream (invariant)

For each **band B** there is exactly one **band stream** \(S_B\):

```
  WSJT-X_B1  ──┐
  WSJT-X_B2  ──┼──►  Stream S_B  (multicast group + UDP port)
  WSJT-X_BN  ──┘         │
                         ├──►  N1MM-B   (logger-of-record only for B)
                         └──►  WIMS    (read-only join for roster / Reply)
                              optional GT (viewer only)
```

| Consumer | Joins | Writes contest log? | Notes |
|----------|-------|---------------------|--------|
| **N1MM-B** | **Only** \(S_B\) | **Yes** (QSO Logged / digi path) | One N1MM process per band (may co-reside with seats or sit central) |
| **WIMS site server** | **All** \(S_{50}, S_{144}, …\) | **No** | Ingest Decode/Status; Reply/Halt by UDP `id` |
| **GridTracker** (optional) | 1+ streams | No | Never click-to-work on WIMS-managed instances |
| **Other N1MM-*** | Must **not** join \(S_B\) | — | Prevents double-log |

**Logging path (digital QSO):**  
WSJT-X (any host on band B) → stream \(S_B\) → **N1MM-B only** → plane C peer merge → WIMS sees
log via plane B `<contactinfo>` / `.s3db` seed (design §3.6).  
WIMS does **not** become a second logger.

**Decode path (roster):**  
WSJT-X → stream \(S_B\) → WIMS (all bands) → SSE consoles.  
N1MM Decode List may also show the same stream for the local op; that is optional UX, not a
second log path if Secondary UDP 2333 stays off when the multicast reader is on.

Many WSJT-X instances may share one stream; disambiguate with unique **`--rig-name` → UDP `id`**.
N1MM’s two UDP reader slots are for **two streams** (e.g. two bands on one PC), **not** a limit
of two WSJT-X instances total.

### 4.2 Why segregate by band (not by host)

If all WSJT-X shared **one** group:port and **every** N1MM enabled the WSJT UDP reader on that
stream, several N1MMs could try to log the same QSO → **double-log** (no shared QSO id across
N1MMs). Segregation is by **band stream**, not by physical PC:

- Remote TV-station WSJT-X on 50 still uses \(S_{50}\); only **N1MM-50** logs.  
- Two 144 PCs (FT8 + MSK) both use \(S_{144}\); only **N1MM-144** logs.

### 4.3 Default band → stream map (human-minimal)

**Scheme A (recommended default):** same multicast group, **one UDP port per band**.

Ports are **arbitrary identifiers**. The default numbering is **sequential from 2237** only so a
**single-band / first seat** matches common WSJT-X + N1MM docs (minimal cognitive load). It is
**not** a protocol requirement that ports stay sequential if WIMS assigns or guides them (§4.4).

| Band (MHz) | Multicast group | Default port | Typical N1MM | Example WSJT-X ids |
|------------|-----------------|-------------:|--------------|--------------------|
| **50** | `224.0.0.73` | **2237** | N1MM-50 | TRAILER-50-A/B/C, TV-50-C |
| **144** | `224.0.0.73` | **2238** | N1MM-144 | TRAILER-144-FT8, TRAILER-144-MSK |
| **222** | `224.0.0.73` | **2239** | N1MM-222 | ROY-222-FT8 |
| **432** | `224.0.0.73` | **2240** | N1MM-432 | ROY-432-FT8 |
| **902** | `224.0.0.73` | **2241** | N1MM-902 | CHIP-902-FT8 (when wired) |
| **1296** | `224.0.0.73` | **2242** | N1MM-1296 | CHIP-1296-FT8 (when wired) |

**Reserve / extend:** further microwave bands append **2243+** (or registry-assigned free ports).
Document the live map in contest Instance Profiles; do not invent a second scheme mid-contest.

**Scheme B (alternate):** fixed port `2237`, group per band (`224.0.0.50`, `.144`, …). Same dual-
consumer rules. **Do not mix A and B** in one contest.

**TTL:** design baseline **3** (fleet L2). **Outgoing interface** on every WSJT-X: contest LAN
NIC — **§4.1** (below; most common silent failure).

### 4.4 Band Stream Registry (ports need not stay sequential)

**Problem:** operators must remember “144 = 2238”; N1MM may bind unexpected UDP ports; WIMS must
join exactly the streams that exist.

**Design:** the **site server** (Setup) owns a **Band Stream Registry** — the single source of
truth for \(S_B\):

| Field | Example |
|-------|---------|
| `band_mhz` | `144` |
| `group` | `224.0.0.73` |
| `port` | `2238` (default) or any free UDP port |
| `n1mm_logger` | seat / host id of N1MM-144 |
| `wsjt_instances[]` | rig-names assigned to this stream |
| `scheme` | `group+port` (A) or `group-per-band` (B) |

**Default fill:** on empty registry, seed Scheme A table (§4.3) for 50–1296.  
**Guided / automatic assignment:**

1. Operator adds a band seat or WSJT instance in Setup (or agent reports a new host).  
2. WIMS proposes **default port** from §4.3, or **next free port** if default is taken / blocked
   (e.g. OS exclusion, another app already bound — observed: N1MM may hold extra UDP ports that
   are **not** labeled “SO2R 2240” in Configurer).  
3. **Agent apply** (future / partial today): write WSJT-X `.ini` (`UDPServer`, `UDPServerPort`,
   `UDPInterface`, Accept UDP); print N1MM reader checklist (IP/group + **this stream’s port
   only**).  
4. **Readiness gate:** every declared WSJT-X id appears on exactly one stream; each stream has
   exactly one N1MM reader; WIMS joins all declared streams; no two N1MMs join the same stream.

**Implication:** if the registry is authoritative and agents apply config, **operators do not need
sequential ports** — only a consistent map. Sequential 2237+ remains the **documented default**
for hand-configured and single-band bring-up.

**WIMS server join policy:**

| Mode | Behavior |
|------|----------|
| **Fleet default** | Join **all ports listed in the registry** (not a hard-coded 2237–2240 only) |
| **Solo / one band** | Join **one** stream (`wims.solo` / `--ports` for lab) |
| **Bind failure** | Skip failed port with loud Status warning; do not silent-fail the whole server if ≥1 stream binds |

### 4.5 Diagram (Scheme A defaults)

```
                         224.0.0.73
    :2237   :2238   :2239   :2240   :2241   :2242
     (50)   (144)   (222)   (432)   (902)  (1296)
       ▲      ▲       ▲       ▲       ▲       ▲
       │      │       │       │       │       │
    N×WSJT N×WSJT  0–1 WSJT 0–1 …  0–1 …   0–1 …
       │      │       │       │       │       │
       ▼      ▼       ▼       ▼       ▼       ▼
    N1MM-50 N1MM-144 N1MM-222 N1MM-432 N1MM-902 N1MM-1296
    (only     (only    (only …)  — each N1MM joins ONE stream
     this      this
     port)     port)

    ┌─────────────────────────────────────────────────────┐
    │  WIMS SERVER  joins ALL registry streams            │
    │  → roster / arbiter / Reply by UDP id               │
    │  → log copy via plane B (not by dual N1MM digi)     │
    └─────────────────────────────────────────────────────┘
```

Control path: WIMS → Reply/Halt on the instance’s stream, keyed by UDP `id`. Only the **lease
holder’s** console commands are honored (design §4.5).

### 4.6 WSJT-X settings (every instance)

These are **required**, not optional tips. Details for the interface field: **§4.8**.

| Setting (Settings → Reporting) | Required value |
|--------------------------------|----------------|
| UDP Server | Stream **group** from registry / §4.3 (e.g. `224.0.0.73`) — **not** `127.0.0.1` for fleet |
| UDP Server port number | Stream **port** for **this instance’s band** (registry / §4.3) |
| **Outgoing interface** | **Contest LAN NIC** — **§4.8** (never blank / `@Invalid()` / loopback) |
| TTL | Sufficient for the LAN (design baseline: **3**) |
| Accept UDP requests | **Yes** when WIMS will drive Reply/Halt |
| Secondary UDP / “Broadcast to N1MM Logger+” (2333) | **OFF** if N1MM already reads this band’s multicast stream (avoids double-log) |

Also: unique `--rig-name` → unique UDP `id`; do **not** use GridTracker as a relay for logging.

### 4.7 N1MM settings (per band logger)

| Setting | Required |
|---------|----------|
| WSJT/JTDX UDP reader | **Enabled** for **this band only** |
| Reader IP / group | Match stream group (e.g. `224.0.0.73`) |
| Reader **port** | **Exactly** \(S_B\).port — not “all digi ports”, not other bands |
| Second reader (Port2) | Only if this **same PC** also logs a **second band** stream; otherwise off |
| Load WSJT/JTDX (CAT proxy) | **Do not use** on WIMS-managed digital seats (§3.3) |
| Broadcast contacts (plane B) | On → WIMS log copy (`224.0.0.73:12060` or site standard) |

**Note:** N1MM may open **extra UDP sockets** that do not appear as labeled “SO2R port” fields in
Configurer (runtime bind ≠ UI label). WIMS readiness should detect **port owners** (process
name) when a stream bind fails, not only the SO2R page.

### 4.8 Contest LAN interface (WSJT-X “Outgoing interface”)

This is the **most common silent networking failure** for multi-instance and multi-host WIMS.
(Cross-refs in this doc that said “§4.1” for the NIC field mean **this subsection**.)

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

Repeat for **every** instance on the host (multi-instance hosts, remote TV-station 50 PC,
and the second 144 PC each need their own Reporting setup).

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
- IP/port = **that band only** (e.g. N1MM-50 → `224.0.0.73:2237` only)  
- **One reader for the whole band** — including remote WSJT-X (TV station 50, second 144 PC)  
- Second reader **off** on every other machine (remote 50 PC must **not** run N1MM as a second logger)  
- Multiple instances on one port are distinguished by UDP `id` (`--rig-name`)  

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

| Instance id (example) | Host / site | Band | Mode | TX group | Multicast | Logger |
|-----------------------|-------------|------|------|----------|-----------|--------|
| TRAILER-50-A (or `-A-FT8` / `-A-MSK`) | TRAILER-50 VM | 50 | FT8 (±MSK dual-RX) | `50-signal` | `:2237` | **N1MM-50** |
| TRAILER-50-B / TRAILER-50-C | TRAILER-50 VM | 50 | FT8 (±MSK dual-RX) | `50-signal` | `:2237` | **N1MM-50** |
| TV-50-C | **TV station PC** (remote) | 50 | FT8 | `50-signal` | `:2237` | **N1MM-50** (not on TV PC) |
| TRAILER-144-FT8 | **144 FT8 PC** + radio | 144 | FT8 | `144-signal` | `:2238` | **N1MM-144** |
| TRAILER-144-MSK | **144 MSK PC** + radio | 144 | MSK/EME | `144-signal` | `:2238` | **N1MM-144** |
| ROY-222-FT8 (or `ROY-222`) | Roy seat PC | 222 | SSB and/or FT8 | `222-signal` | `:2239` when FT8 | **N1MM-222** |
| ROY-432-FT8 (or `ROY-432`) | Roy seat PC | 432 | SSB and/or FT8 | `432-signal` | `:2240` when FT8 | **N1MM-432** |

Multicast group for all: `224.0.0.73` (port per band as above).

---

## 9. Per-machine checklist

### Each WSJT-X instance (including remote TV-station 50 and second 144 PC)
- [ ] Unique `--rig-name` / UDP id  
- [ ] Multicast group + **band port** from §4  
- [ ] **§4.1:** Outgoing interface = contest LAN NIC (not blank / `@Invalid` / loopback)  
- [ ] **§4.1:** UDP Server is fleet multicast, not `127.0.0.1`  
- [ ] On **same contest L2** as the band’s N1MM and WIMS  
- [ ] `wsjtx_config.py --all` reports **0 errors** on this host  
- [ ] WIMS sees this instance’s heartbeat (LAN source IP, not only local decode window)  
- [ ] Exactly **one** N1MM (the band’s) is the logger — **no** N1MM WSJT reader on remote/extra PCs  
- [ ] **§3.2 / §3.3:** CAT path documented (e.g. `wfview-rigctld`); Test CAT green; not dual-open on radio COM  

### Each Icom USB seat using wfview (§3.3)
- [ ] Radio: **CI-V USB Port = Unlink from [REMOTE]**; USB baud matches wfview  
- [ ] wfview owns real COM; **Enable RigCtld** (4533 LISTENING); TCP server ON for N1MM  
- [ ] WSJT-X: Hamlib NET **`127.0.0.1:4533`** — not Icom+COM, not `:50002`  
- [ ] N1MM: **TCP** to wfview — not COM3/4; no **Load WSJT/JTDX**  
- [ ] Plane A port = band table (e.g. 144 → **2238**); Secondary UDP 2333 off if N1MM reads multicast  

### Each N1MM (50 / 144 / 222 / 432)
- [ ] WSJT UDP reader → **only that band’s** group:port (covers **all** remote instances on that port)  
- [ ] External broadcast → `224.0.0.73:12060` (or WIMS LAN IP:12060)  
- [ ] Networked into the **same** contest with the other three N1MMs  
- [ ] Station name unique and stable (WIMS logger id)  
- [ ] 222/432: OK if no WSJT-X this hour (SSB-only); reader can stay enabled for when FT8 starts  
- [ ] If CAT used: seat middleware path only (§3.2) — not competing with wfview for COM  

### WIMS server
- [ ] Join all WSJT-X ports (2237–2240) on the LAN iface (or match seat band port until multi-port join is wired)  
- [ ] Solo/lab: `--port` matches the seat’s plane A port (e.g. **2238** for 144)  
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
| One stream (band port, often `2237` or `2238` for 2 m) + emulator or few WSJT-X | Multi-host WSJT-X (trailer + remote 50 + dual 144) on four ports |
| Optional wfview + Hamlib NET on the radio PC (§3.3) | Same seat pattern per Icom USB radio |
| Optional GridTracker on the WIMS PC | Optional GT per seat / remote PC |
| WIMS with LAN `--iface` + `--n1mm-group 224.0.0.73` | Same server role; join all band ports |
| All processes on one machine | N1MM and WSJT-X **may be different machines/sites** on one LAN |

Scale path: start with one group:port and one N1MM; **add a port (or group) per band** when a
second logger comes online so double-log never becomes possible. Remote 50 / second 144 PC =
**same port**, extra hosts, **still one N1MM**.

---

## 11. Design invariants (summary)

1. **Open monitoring** — any number of subscribers on a stream (WIMS, N1MM, GridTracker).  
2. **Singular control** — one logger-of-record per WSJT-X; one TX controller (lease) per managed instance; one rotator controller per rotator.  
3. **WIMS never logs** — path is WSJT-X → N1MM; WIMS reads.  
4. **No unattended TX** — human click + valid lease; else RX-only.  
5. **One signal per band** — multi-instance same band share one resource group.  
6. **Server is site-local for radio UDP** — remote consoles are unicast only.  
7. **CAT is seat-local** — WIMS never owns radio COM/CI-V/Hamlib; middleware (e.g. wfview) is allowed; one owner of the wire (§3.2–§3.3).  
8. **Band stream port match** — WSJT-X, N1MM WSJT reader, and WIMS `--port` use the same §4 port (e.g. 144 → 2238).  

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

| | 222 / 432 (simple) | 50 / 144 (complex) |
|--|--------------------|---------------------|
| Profile | One PC, one N1MM, SSB and/or FT8 | Multi-host, shared resource group, remote 50 possible |
| Bring-up | “One band, one radio” wizard | Band captain + multi-instance + remote-site checks |
| Training | ~2 minutes + wall card | Experienced digital op; remote 50: no second N1MM |
| Same engine? | Yes — readiness + faults | Yes — more expected rows / hosts |

**Ship guided setup for simple seats first** — highest ROI for operators who do not know WIMS
internals. Complex bands use the same lights and fault language so the site has one diagnostic culture.

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
