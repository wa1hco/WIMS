# WIMS — Fleet networking map (WSJT-X / N1MM / GridTracker)

Companion to **[wims_design.md](wims_design.md)** (requirements / design). This document is the
**authoritative networking layout** for the contest digital fleet: who multicasts what, who
joins which streams, and how loggers stay single-owner. When the *layout* changes, edit here
and keep §Deployment / §4.3 in the design doc in sync at a summary level.

Related: **[wims_status.md](wims_status.md)** for what the server currently binds/joins in code.

> **Current fleet (2026-09-05):** plane A is **one stream** — `224.0.0.73:2237` for **all**
> bands. Digi → N1MM is the **N1MM agent** (Log / Broadcast / KEY), **not** N1MM’s built-in
> WSJT/JTDX UDP reader (keep that **OFF**). Decision:
> [2026-09-05-plane-a-single-port-2237.md](../decisions/2026-09-05-plane-a-single-port-2237.md).
> Operator bring-up: [operator_setup.md](../operator_setup.md). Distinguish instances with
> `--rig-name`; band from dial / RadioInfo.
>
> **Historical:** per-band Scheme A ports (2238/2239/2241…), dual-consumer-via-N1MM-reader, and
> Switchboard F4 Option 2 framing below are **lab archaeology only** — not W2SZ bring-up.
> Open follow-ons that may still change other parts of this map: dedicated-RTS PTT seat
> ([wims_tx_inhibit.md](wims_tx_inhibit.md) §5.5) vs `PTT Method = CAT` in §3.3; experimental
> GridTracker bridge (`--gt-forward HOST:22370`, ephemeral reverse port; no arbiter gating —
> lab only; `GET /api/gt-bridge`).

**Critical ops note:** every WSJT-X instance must set **Outgoing interface = contest LAN NIC**
(§4.8). Multicast address alone is not enough — blank / `@Invalid()` interface is a silent
failure (decodes work, WIMS never sees UDP).

---

## 1. Station layout (digital)

**Invariant:** one **N1MM per band** is the **logger-of-record** for that band’s digi QSOs.
Logging is **N1MM agent Log** on the band’s N1MM PC (joins `224.0.0.73:2237`, filters by live
band via RadioInfo, forwards to localhost `:52001` / `:2333`). N1MM’s built-in WSJT/JTDX UDP
**reader stays OFF** everywhere for digi. WSJT-X hosts may sit **on a different PC or site**
than their N1MM as long as they share the **contest LAN** (plane A multicast). N1MM does
**not** need to co-reside with every radio.

**Multiple N1MM processes on one band (clarified 2026-08-12 — design §2.13.4):** a second N1MM
used only for **SSB/CW** (no digi Log path on that PC) may exist for voice logging /
RadioInfo; WIMS may show both. **Two digi log paths into the same N1MM for one QSO is not
supported** (e.g. built-in reader **and** agent Log, or Secondary UDP 2333 **and** agent Log)
and is a readiness **error**. Digital dupe/mult follows the active contest log.

```
All bands share plane A  224.0.0.73:2237  (band from dial / RadioInfo, not port)

50 MHz — one common N1MM-50 (+ agent Log)
├── Host(s) at TRAILER (and/or other on-site PCs)
│   ├── WSJT-X  TRAILER-50-A   FT8   (e.g. fixed beam az₁)   :2237
│   └── WSJT-X  TRAILER-50-B   FT8   (e.g. fixed beam az₂)   :2237   … count may vary
│
└── Host at REMOTE SITE (e.g. TV station tower / separate building)
    └── WSJT-X  TV-50-C        FT8   (own PC + radio; same :2237)
        → still logged only by N1MM-50 agent Log (not a second N1MM)

144 MHz — one common N1MM-144 (+ agent Log)
├── PC + radio  WSJT-X  TRAILER-144-FT8    FT8      :2237
└── PC + radio  WSJT-X  TRAILER-144-MSK    MSK144   :2237  (or EME / Q65)
    → separate hosts/radios OK; both on :2237; only N1MM-144 agent Log filters/logs 144

222 MHz — one N1MM-222 + one seat PC (e.g. Roy)   WSJT-X :2237 when digital
└── Same PC may run SSB/CW (N1MM voice/CW) and/or WSJT-X FT8 when digital
    (not always FT8; mode is operator choice for the period)

432 MHz — one N1MM-432 + one seat PC (e.g. Roy)   WSJT-X :2237 when digital
└── Same pattern as 222: one PC, SSB and/or FT8 as equipped

902 / 1296 — same pattern when wired (still :2237; agent Log filters by live band)
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
4. Each instance: UDP `224.0.0.73`:**`2237`**, Outgoing interface = LAN.  
5. N1MM on that host: Station/computer name unique; **WSJT/JTDX UDP reader OFF**; run **N1MM
   agent** (Log / Broadcast / KEY) with `WIMS_SERVER`.

### 1.1 Split site: remote WSJT-X, common N1MM (50 MHz TV station, etc.)

```
  TV-station PC                    Trailer / central site
  ┌─────────────────┐              ┌──────────────────────────┐
  │ WSJT-X TV-50-C  │──mcast:2237──│ N1MM-50 + agent Log      │
  │ own radio/PA    │              │ (reader OFF; sole logger │
  └─────────────────┘              │  for 50 digi)            │
         ▲                         │ WIMS joins 2237 too      │
         │ contest LAN (same L2)   └──────────────────────────┘
         └──── must NOT use a second N1MM on the TV PC for this band
```

| Rule | Why |
|------|-----|
| Remote PC runs **WSJT-X only** for that band (optional local agent / GT viewer) | Avoids double-log |
| **N1MM-50 agent Log** (one machine) joins **2237** and filters live band = 50 | Sole logger-of-record |
| N1MM built-in WSJT UDP reader **OFF** | Agent Log owns digi → N1MM |
| Both PCs: UDP Server = fleet multicast, **Outgoing interface = contest LAN NIC** | Silent-failure trap §4.8 |
| Same **Contest LAN** (wired L2 or equivalent) between TV site and N1MM/WIMS | Multicast does not cross the public internet |
| Unique `--rig-name` (e.g. `TV-50-C`) | WIMS / agent distinguish instances |

If the remote site **cannot** join the contest L2, it is **out of scope for plane A** until a
relay is designed (not default). Unicast-to-N1MM-only without WIMS is a manual exception, not the
fleet map.

### 1.2 Dual PC on one band (144 FT8 + MSK144)

```
  PC-144-FT8 ──WSJT-X──┐
                       ├── 224.0.0.73:2237 ──► N1MM-144 agent Log (reader OFF)
  PC-144-MSK ──WSJT-X──┘                    ──► WIMS (observer)
```

- Separate **radio + PC** per mode is expected; **one N1MM-144** still owns the log via agent.  
- Interlock / resource group `144-signal` still means at most one radiated TX on 144.  
- Do **not** enable N1MM’s built-in WSJT reader on either 144 PC (or anywhere for digi).

### 1.3 Single-PC seats (222 / 432)

- One host runs **N1MM** for that band and, when digital, **one WSJT-X**.  
- Periods of **SSB/CW only** are normal: N1MM up, no WSJT-X instance (WIMS shows logger via
  plane B RadioInfo; no digital instance until FT8 starts).  
- When FT8 is active, same rules as any other band (multicast + unique id + iface).

**Microwave / UHF extend the same pattern:** 902 and 1296 use the same single plane-A stream
(`:2237`) and per-band N1MM agent Log as VHF (§4). Seats may be sparse (0–1 WSJT-X) until
wired; agent + RadioInfo keep band filtering uniform.

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
              │  joins 224.0.0.73:2237   │
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
| **A. WSJT-X UDP (multicast)** | WSJT-X Heartbeat / Status / Decode / QSO Logged | Decodes, status, N1MM logging of digital QSOs |
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
   └── Plane A multicast 224.0.0.73:2237 ──► WIMS + N1MM agent Log + optional GT
N1MM (reader OFF)
   └── Plane B XML 127.0.0.1:12060 ──► N1MM agent ──HTTP──► WIMS
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

**Reporting tab (plane A — port `2237`, §4.3)**

| Setting | Value |
|---------|--------|
| UDP Server | **`224.0.0.73`** |
| UDP Server port | **`2237`** (all bands — current fleet; §4.3) |
| Accept UDP requests | **ON** (WIMS Reply / Halt) |
| Outgoing interface | Contest LAN NIC (§4.8) — mandatory on multi-homed / fleet seats |
| Secondary UDP / N1MM Logger+ Broadcasts | **OFF** — N1MM agent Log owns digi → N1MM (avoids double-log) |

**`--rig-name`:** unique fleet-wide UDP `id` (e.g. `TRAILER-144-FT8`).

#### 3.3.4 N1MM (logger + optional freq)

| Concern | Setting |
|---------|---------|
| **CAT / frequency** | Port type **TCP**, address **`127.0.0.1:<wfview-tcp-port>`**, radio model = actual rig (e.g. IC-9700). Not COM3/4. |
| **WSJT UDP reader** | **OFF** — digi → N1MM is the **N1MM agent Log** path, not N1MM joining plane A |
| **Broadcast Data** | Contacts + Radio → **`127.0.0.1:12060`** (N1MM agent relays to site; plane B) |
| **Load WSJT/JTDX** | **Do not use** on WIMS-managed digital seats |

Leave CW/PTT on N1MM’s radio port off when WSJT-X owns digi TX via CAT.

#### 3.3.5 WIMS and GridTracker on a wfview seat

| App | Join | Notes |
|-----|------|--------|
| **WIMS server** | `--group 224.0.0.73 --ports 2237` | Fleet default is **2237 only** |
| **GridTracker** | Same group:port as the band being watched | **Viewer only** on managed instances — no click-to-work (bypasses TX arbiter, design §1.2 / §4.3) |

#### 3.3.6 Start order

1. **wfview** — connected; RigCtld ON; TCP server ON  
2. **WSJT-X** — Test CAT green; decoding; plane A `224.0.0.73:2237` applied  
3. **N1MM** — digi WSJT reader **OFF**; Broadcast → `127.0.0.1:12060`; **N1MM agent** up  
4. **WIMS** — roster fills; joins **`2237`**  
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
| WIMS roster empty; waterfall full | WSJT-X not on `224.0.0.73:2237`, or §4.8 outgoing iface |
| Double QSOs in N1MM | Built-in WSJT reader and/or Secondary UDP 2333 **and** agent Log both on |

---

## 4. Plane A — single fleet stream (WSJT-X → WIMS + N1MM agent Log)

**Current model (normative for operators):** *all* WSJT-X instances multicast on **one** plane-A
stream — `224.0.0.73:2237`. Consumers are **WIMS** (roster / Reply), **N1MM agent Log** on each
band’s logger PC (filters by live band → localhost `:52001` / `:2333`), and optional **GT**.
N1MM’s built-in WSJT/JTDX UDP **reader stays OFF**. Band identity comes from dial / RadioInfo,
not from UDP port.

**Historical (lab only):** dual-consumer-via-N1MM-reader and Scheme A multi-port (§4.3 table /
§4.5 diagram) assumed one port per band and N1MM joining plane A as a reader. Do **not** use
that for W2SZ bring-up — see
[decision 2026-09-05](../decisions/2026-09-05-plane-a-single-port-2237.md).

### 4.0 Problem statement

| Need | Constraint |
|------|------------|
| **N WSJT-X per band** (beams, dual-RX modes, remote site) | Distinct radios / PCs / modes |
| **Log only to that band’s N1MM** | Exactly **one** digi log path per QSO (agent Log; reader OFF) |
| **All decodes → common WIMS** | One site roster / arbiter / console |
| **Bands 50 → 1296 MHz** | Same plane-A port; agent filters by live band |
| **Minimal one-band setup looks familiar** | Defaults: `224.0.0.73:2237` + agent |
| **Ports are hard to remember** | Fleet uses **one** port — no per-band arithmetic |

### 4.1 Consumers of the fleet stream (invariant)

There is **one** plane-A stream \(S\) for the fleet:

```
  WSJT-X (any band / host)  ──┐
                              ├──►  224.0.0.73:2237
  WSJT-X …                    ┘         │
                         ├──►  WIMS    (roster / Reply; all bands)
                         ├──►  N1MM agent Log on N1MM-B PC (filter band B → log)
                         └──►  optional GT (viewer only)
```

| Consumer | Joins | Writes contest log? | Notes |
|----------|-------|---------------------|--------|
| **N1MM agent Log** (on N1MM-B PC) | **2237** | **Yes** (forwards QSO Logged → local N1MM) | Filters by RadioInfo live band; built-in reader **OFF** |
| **WIMS site server** | **2237** | **No** | Ingest Decode/Status; Reply/Halt by UDP `id` |
| **GridTracker** (optional) | 2237 (or lab ports) | No | Never click-to-work on WIMS-managed instances |
| **N1MM built-in WSJT reader** | — | **Must stay OFF** | Would double-log with agent Log |

**Logging path (digital QSO):**  
WSJT-X (any host) → `224.0.0.73:2237` → **N1MM agent Log** on the matching band’s N1MM PC →
local N1MM (`:52001` / `:2333`) → plane C peer merge → WIMS sees log via plane B
`<contactinfo>` / `.s3db` seed (design §3.6).  
WIMS does **not** become a second logger.

**Decode path (roster):**  
WSJT-X → `:2237` → WIMS → SSE consoles.  
Keep Secondary UDP / “Broadcast to N1MM Logger+” (**2333**) **OFF** on WSJT-X — agent Log
owns the digi path.

Many WSJT-X instances share one stream; disambiguate with unique **`--rig-name` → UDP `id`**.

### 4.2 Why one port + agent filter (not N1MM reader per band)

**Historical risk:** if every N1MM enabled the built-in WSJT UDP reader on a shared stream,
several N1MMs could try to log the same QSO → **double-log**. Scheme A multi-port segregated
by UDP port so each N1MM joined only “its” band.

**Current practice:** one port (`2237`); **reader OFF**; **agent Log** on each logger PC
filters by live band (RadioInfo). Same segregation outcome without per-band ports:

- Remote TV-station WSJT-X on 50 still uses `:2237`; only **N1MM-50 agent** logs 50 digi.  
- Two 144 PCs (FT8 + MSK) both use `:2237`; only **N1MM-144 agent** logs 144 digi.

### 4.3 Plane A port map

> **Current fleet practice (2026-09-05):** **one port for all bands — `224.0.0.73:2237`.**  
> See [decisions/2026-09-05-plane-a-single-port-2237.md](../decisions/2026-09-05-plane-a-single-port-2237.md).  
> Operator docs and server default `--ports` follow that. Distinguish instances with
> `--rig-name`; band from dial / RadioInfo.

**Historical Scheme A** (one UDP port per band: 2237/2238/…/2243, skip 2240) remains
documented below for lab archaeology only — **do not use it for W2SZ bring-up.**

| Band (MHz) | Multicast group | Historical port | Notes |
|------------|-----------------|----------------:|-------|
| **all (current)** | `224.0.0.73` | **2237** | **Use this** |
| 50 / 144 / … (old map) | `224.0.0.73` | 2238–2243 | Obsolete for operators |

**Fleet server default join list:** `2237` (code: `FLEET_WSJT_PORTS`). Lab escape:
`--ports 2237,2238,…`.

**Scheme B (alternate lab):** fixed port `2237`, group per band (`224.0.0.50`, …). Do not
mix schemes mid-contest.

**TTL:** design baseline **3** (fleet L2). **Outgoing interface** on every WSJT-X: contest LAN
NIC — **§4.8** (most common silent failure).

### 4.4 Band Stream Registry (lab / historical multi-port)

**Fleet default today:** one stream — `224.0.0.73:2237`. A multi-port registry is optional lab
tooling (`--ports 2237,2238,…`), not the contest bring-up recipe.

**Historical problem this registry solved:** operators had to remember “144 = 2238”; N1MM might
bind unexpected UDP ports; WIMS had to join exactly the streams that existed.

**Design (when multi-port lab is used):** the **site server** (Setup) owns a **Band Stream
Registry** — the single source of truth for \(S_B\):

| Field | Example |
|-------|---------|
| `band_mhz` | `144` |
| `group` | `224.0.0.73` |
| `port` | **`2237`** (fleet) or lab override e.g. `2238` |
| `n1mm_logger` | seat / host id of N1MM-144 |
| `wsjt_instances[]` | rig-names assigned to this stream |
| `scheme` | `single-port` (current) / `group+port` (A, historical) / `group-per-band` (B) |

**Default fill:** on empty registry, seed **`2237` for all bands** (current). Historical Scheme A
table (§4.3) is lab archaeology only.  
**Guided / automatic assignment:**

1. Operator adds a band seat or WSJT instance in Setup (or agent reports a new host).  
2. WIMS proposes **`2237`** (fleet), or a free lab port if experimenting with multi-port.  
3. **Agent apply** (future / partial today): write WSJT-X `.ini` (`UDPServer`, `UDPServerPort`,
   `UDPInterface`, Accept UDP); print **N1MM agent** checklist (reader OFF; Log joins 2237;
   Broadcast `127.0.0.1:12060`).  
4. **Readiness gate:** every declared WSJT-X id appears on the fleet stream; each band has
   exactly one N1MM agent Log path; WIMS joins **2237**; built-in readers OFF.

**Implication:** operators do **not** need per-band ports — only `2237` + unique `--rig-name`.

**WIMS server join policy:**

| Mode | Behavior |
|------|----------|
| **Fleet default** | Join **`2237` only** (code: `FLEET_WSJT_PORTS`) |
| **Solo / one band** | Same — `--ports 2237` (or `wims.solo`) |
| **Lab multi-port** | Optional `--ports 2237,2238,…` (not contest default) |
| **Bind failure** | Skip failed port with loud Status warning; do not silent-fail the whole server if ≥1 stream binds |

### 4.5 Diagram

**Current fleet:**

```
                    224.0.0.73:2237
                          ▲
         ┌────────────────┼────────────────┐
      N×WSJT           N×WSJT           0–1 …
      (50, 144, …)     (any band)       (microwave)
         │                │                │
         └────────────────┴────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
        WIMS      N1MM agent Log     optional GT
                  (per band PC;
                   reader OFF)
```

**Historical Scheme A** (lab archaeology — do not use for bring-up):

```
                         224.0.0.73
    :2237   :2238   :2239   (2240 hole)  :2241   :2242   :2243
     (50)   (144)   (222)    unused       (432)   (902)  (1296)
       ▲      ▲       ▲                    ▲       ▲       ▲
    N×WSJT N×WSJT  0–1 WSJT             0–1 …   0–1 …   0–1 …
       ▼      ▼       ▼                    ▼       ▼       ▼
    N1MM-50 N1MM-144 N1MM-222           N1MM-432 …  (each reader ON one port)
    WIMS joined ALL registry streams (skip 2240)
```

Control path: WIMS → Reply/Halt on `:2237`, keyed by UDP `id`. Only the **lease holder’s**
console commands are honored (design §4.5).

### 4.6 WSJT-X settings (every instance)

These are **required**, not optional tips. Details for the interface field: **§4.8**.

| Setting (Settings → Reporting) | Required value |
|--------------------------------|----------------|
| UDP Server | **`224.0.0.73`** — **not** `127.0.0.1` for fleet |
| UDP Server port number | **`2237`** (all bands — §4.3) |
| **Outgoing interface** | **Contest LAN NIC** — **§4.8** (never blank / `@Invalid()` / loopback) |
| TTL | Sufficient for the LAN (design baseline: **3**) |
| Accept UDP requests | **Yes** when WIMS will drive Reply/Halt |
| Secondary UDP / “Broadcast to N1MM Logger+” (2333) | **OFF** — N1MM agent Log owns digi → N1MM |

Also: unique `--rig-name` → unique UDP `id`; do **not** use GridTracker as a relay for logging.

### 4.7 N1MM settings (per band logger)

| Setting | Required |
|---------|----------|
| WSJT/JTDX UDP reader | **OFF** (digi path is N1MM agent Log) |
| N1MM agent **Log** | Joins `224.0.0.73:2237`; filters by live band → `127.0.0.1:52001` / `:2333` |
| N1MM agent **Broadcast** | Relays plane B from `127.0.0.1:12060` → site (`WIMS_SERVER`) |
| N1MM agent **KEY** | As needed for SSB/CW inhibit (§3 / operator_setup) |
| Load WSJT/JTDX (CAT proxy) | **Do not use** on WIMS-managed digital seats (§3.3) |
| Broadcast Data (plane B) | Contacts + Radio → **`127.0.0.1:12060`** (agent relays to site) |

**Note:** N1MM may still open **extra UDP sockets** that do not appear as labeled “SO2R port”
fields in Configurer (runtime bind ≠ UI label) — see **§4.9** (historical multi-port lab).
With reader OFF and fleet on **2237 only**, accidental N1MM binds of old Scheme A ports are
usually harmless noise for WIMS.

### 4.9 Runtime port ownership conflicts (e.g. `:2240` held by N1MM) — historical lab notes

> **Context:** written when Scheme A multi-port was the wired default. **Current fleet joins
> `2237` only**, so accidental N1MM binds of 2238/2239/2240/2241… usually do **not** empty the
> digi roster. Keep this section for lab archaeology and for the case where someone still runs
> `--ports` with those values.

This is **not** the same as “operator forgot SO2R port 2240 in Configurer.” It is a **runtime
socket ownership** problem that a multi-port Band Stream Registry and readiness checks must
handle.

**Historical design decision (2026-07):** Scheme A **no longer used UDP 2240** for any band
stream. **432 → 2241**, **902 → 2242**, **1296 → 2243**. Multi-port WIMS join lists **omitted
2240** so a common Windows/N1MM bind of `:2240` did not steal the 432 stream. §4.9 remains for
lab ports (2237, 2241, …) that may still collide when multi-port is enabled.

#### 4.9.1 Lab observation (W10VM-50 / N1MM+, 2026-07)

| Fact | Detail |
|------|--------|
| **Symptom (old map)** | WIMS server stderr: `WSJT-X port 224.0.0.73:2240 bind failed ([WinError 10013] …); skipping` when 432 was still on 2240 |
| **Owner of UDP :2240** | `N1MMLogger.net.exe` (verified with `Get-NetUDPEndpoint` / `netstat -ano -p udp`) |
| **Also held by same N1MM** | UDP **2237** (primary digi reader) plus multi-computer **12070/12080**, multi-user **130xx**, ephemeral high ports |
| **Configurer UI** | Operator may see **no SO2R / no second-reader / no “2240”** field set |
| **`N1MM Logger.ini`** | Often only `[ExternalProgramInput] EnableWSJTJTDXUDPReader=True` + `WSJTJTDXUDPIP=…` — **port number may be omitted** from that section |
| **Admin DB defaults** | May list default digi ports (e.g. 2237 / 2239) that **do not match** live binds |
| **Conclusion** | **Runtime bind ≠ SO2R page labels.** Treat process→port as ground truth. **Default map avoids 2240.** |

Same class of issue can hit **any** registry port (2237, 2241, …).

#### 4.9.2 Why this breaks (and what it does *not* break)

| Effect | Severity |
|--------|----------|
| WIMS cannot join a stream if its registry port is taken (e.g. 2241) | **That band’s digi roster empty** for WIMS; server should **keep running** |
| Old map used 2240 for 432 | Mitigated by **skipping 2240** in defaults (§4.3) |
| N1MM still logs its own digi path on ports it owns | Logging may be fine for the band N1MM intends |
| Browser “● disconnected” | **Unrelated** — means HTTP/SSE to `:8787` died (process exit, Defender, dual-primary demote) |
| Double-log | Built-in reader ON and/or Secondary 2333 **and** agent Log; or two agents claiming one band — not the same as WIMS failing to bind |

Design rule (already in §4.4): **bind failure → loud Status warning + skip that port; do not kill the server** if at least one stream binds.

#### 4.9.3 Operator diagnosis (no Wireshark)

```text
# Who owns a port? (Windows)
netstat -ano -p udp | findstr ":2240"
Get-NetUDPEndpoint -LocalPort 2240 | Format-List OwningProcess, LocalAddress
# then: Get-Process -Id <pid>

# Free test: fully exit N1MM → recheck port → if free, N1MM was the owner
```

Do **not** require the operator to find “2240” under SO2R before believing the conflict.

#### 4.9.4 Mitigations (design + ops)

| Approach | When | Notes |
|----------|------|--------|
| **A. Skip the port in WIMS** | Band not used / temporary | `--ports` without that port, or registry omit band |
| **B. Reassign stream port in registry** | Lab multi-port only; want band digi while another app holds the port | New free port for \(S_B\); update **all** WSJT-X on B + WIMS `--ports`; keep N1MM reader OFF / agent on 2237 |
| **C. Free the port in N1MM** | N1MM should not need it | Exit N1MM; if port frees, restart N1MM with digi reader **OFF**; re-check live binds |
| **D. Readiness UI** | Always | Status/Setup: “UDP :P owned by N1MMLogger.net — WIMS stream B skipped” with deep link to this section |
| **E. Default map hole** | **2240** | Never assign a band stream to 2240 in Scheme A defaults (already done) |

**WIMS must not** assume Configurer text fields are complete. **Agent / server readiness** should:

1. Attempt bind (or query OS for listeners) on each registry port.  
2. On failure, resolve **owning process name + path**.  
3. Surface band, intended consumer (WIMS join vs N1MM logger), and one-click remedies A–C.  
4. Never require sequential ports after a reassignment (registry is authoritative).

#### 4.9.5 Relation to current consumers (and historical dual-reader)

- **Current:** WIMS + **N1MM agent Log** both join **2237**; N1MM built-in reader **OFF**. Shared multicast bind is expected.  
- **Historical:** N1MM holding 2237 as a built-in reader while WIMS also joined 2237 was often OK with `SO_REUSEADDR` — both were intended consumers of a Scheme A \(S_{50}\).  
- **N1MM holding 2240** when WIMS joins only 2237 is **harmless noise**.  
- If lab multi-port is enabled and N1MM holds a live `--ports` entry without being an intentional consumer, treat as accidental ownership — **registry + readiness**.

### 4.8 Contest LAN interface (WSJT-X “Outgoing interface”)

This is the **most common silent networking failure** for multi-instance and multi-host WIMS.
(Cross-refs in this doc that said “§4.1” for the NIC field mean **this subsection**.)

#### What it is

In WSJT-X: **File → Settings → Reporting** (or **Preferences → Reporting**).

| Field | Meaning |
|-------|---------|
| **UDP Server** | Destination address for Heartbeat / Status / Decode / QSO Logged (use fleet multicast) |
| **UDP Server port number** | Destination port — fleet **`2237`** (§4.3) |
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
listeners. Fix: both instances → `224.0.0.73:2237` **and** Outgoing interface =
LAN NIC (e.g. `enp13s0f1` / `192.168.1.x` segment).

#### How to set it (operator steps)

1. Open the **correct** WSJT-X window (each `--rig-name` has its own settings).  
2. **Settings → Reporting**.  
3. **UDP Server** = `224.0.0.73`.  
4. **Port** = **`2237`** (all bands).  
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
| WSJT-X | Outgoing interface = contest LAN (§4.8) |
| WIMS server | `--iface <LAN-IP>` for multicast join; not `127.0.0.1` for multi-host |
| N1MM External Broadcast dest | **`127.0.0.1:12060`** + N1MM agent with `WIMS_SERVER` (fleet). Lab: multicast/unicast to site still OK. Never Tailscale `100.x`. |
| N1MM agent Log | Joins `224.0.0.73:2237` on a NIC that receives that multicast (same LAN); built-in reader OFF |

### N1MM agent (per band logger)

- **WSJT/JTDX UDP reader → OFF** (Configurer → WSJT/JTDX Setup)  
- **Broadcast Data** → Contacts + Radio → **`127.0.0.1:12060`**  
- **N1MM agent Log** → joins `224.0.0.73:2237`, filters by live band, forwards Logged QSOs →
  `127.0.0.1:52001` then `:2333`  
- **N1MM agent Broadcast** → relays plane B to site (`WIMS_SERVER`)  
- **N1MM agent KEY** → as needed for SSB/CW inhibit  
- One agent Log path **per band’s N1MM PC** — covers remote WSJT-X (TV station 50, second 144 PC)  
- Remote/extra PCs must **not** run a second N1MM digi logger for that band  
- Multiple instances on `:2237` are distinguished by UDP `id` (`--rig-name`)  

### WIMS server

- Join `224.0.0.73` on **`2237` only** by default (`--ports 2237`)  
- `--iface` = site LAN address (not loopback) for real hosts  
- Observes only; never double-logs  

### GridTracker (optional)

- Join `224.0.0.73:2237` (same fleet stream)  
- Viewer only — no Reply/TX on WIMS-managed instances  

---

## 5. Plane B — N1MM external broadcast → WIMS

All four N1MMs publish activity so WIMS can show logger presence and keep the live log copy:

| Setting | Value |
|---------|--------|
| Broadcast Data | Contacts **on**; Radio **on** (presence without a QSO); Spots/Lookup optional |
| Destination | **Fleet: `127.0.0.1:12060`** (identical on every logger; **N1MM agent** relays to site). Lab optional: `224.0.0.73:12060` or unicast `WIMS_LAN_IP:12060`. Never Tailscale `100.x`. |
| Listener | **N1MM agent** on each logger PC → `POST /api/n1mm/broadcast`; site may still join multicast for lab |

```
  N1MM-50 ──┐
  N1MM-144 ─┼── UDP XML ──► 127.0.0.1:12060 ──► N1MM agent ──HTTP──► WIMS site
  N1MM-222 ─┤
  N1MM-432 ─┘

  <contactinfo>  → log copy / dupe-mult (via agent)
  <RadioInfo>    → logger alive + live band (via agent)
```

Fleet default is **`127.0.0.1:12060`** (identical on every N1MM). See [operator_setup.md](../operator_setup.md).

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

Each N1MM’s **agent Log** still filters plane A by **live band** (reader OFF). Networking merges
logs after local log; it does not replace logger-of-record segregation.

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
| TRAILER-50-A (or `-A-FT8` / `-A-MSK`) | TRAILER-50 VM | 50 | FT8 (±MSK dual-RX) | `50-signal` | `:2237` | **N1MM-50** (agent Log) |
| TRAILER-50-B / TRAILER-50-C | TRAILER-50 VM | 50 | FT8 (±MSK dual-RX) | `50-signal` | `:2237` | **N1MM-50** (agent Log) |
| TV-50-C | **TV station PC** (remote) | 50 | FT8 | `50-signal` | `:2237` | **N1MM-50** agent Log (not on TV PC) |
| TRAILER-144-FT8 | **144 FT8 PC** + radio | 144 | FT8 | `144-signal` | `:2237` | **N1MM-144** (agent Log) |
| TRAILER-144-MSK | **144 MSK PC** + radio | 144 | MSK/EME | `144-signal` | `:2237` | **N1MM-144** (agent Log) |
| ROY-222-FT8 (or `ROY-222`) | Roy seat PC | 222 | SSB and/or FT8 | `222-signal` | `:2237` when FT8 | **N1MM-222** (agent Log) |
| ROY-432-FT8 (or `ROY-432`) | Roy seat PC | 432 | SSB and/or FT8 | `432-signal` | `:2237` when FT8 | **N1MM-432** (agent Log) |

Multicast for all: `224.0.0.73:2237`. Band from dial / RadioInfo; logger via **N1MM agent Log**.

---

## 9. Per-machine checklist

### Each WSJT-X instance (including remote TV-station 50 and second 144 PC)
- [ ] Unique `--rig-name` / UDP id  
- [ ] Multicast **`224.0.0.73:2237`** (§4)  
- [ ] **§4.8:** Outgoing interface = contest LAN NIC (not blank / `@Invalid` / loopback)  
- [ ] **§4.8:** UDP Server is fleet multicast, not `127.0.0.1`  
- [ ] Secondary UDP / N1MM Logger+ (**2333**) **OFF**  
- [ ] On **same contest L2** as the band’s N1MM and WIMS  
- [ ] `wsjtx_config.py --all` reports **0 errors** on this host  
- [ ] WIMS sees this instance’s heartbeat (LAN source IP, not only local decode window)  
- [ ] Digi logged by **that band’s N1MM agent Log** — **no** built-in WSJT reader on any PC  
- [ ] **§3.2 / §3.3:** CAT path documented (e.g. `wfview-rigctld`); Test CAT green; not dual-open on radio COM  

### Each Icom USB seat using wfview (§3.3)
- [ ] Radio: **CI-V USB Port = Unlink from [REMOTE]**; USB baud matches wfview  
- [ ] wfview owns real COM; **Enable RigCtld** (4533 LISTENING); TCP server ON for N1MM  
- [ ] WSJT-X: Hamlib NET **`127.0.0.1:4533`** — not Icom+COM, not `:50002`  
- [ ] N1MM: **TCP** to wfview — not COM3/4; no **Load WSJT/JTDX**  
- [ ] Plane A port = **`2237`**; Secondary UDP 2333 **OFF** (agent Log owns digi)  

### Each N1MM (50 / 144 / 222 / 432)
- [ ] WSJT/JTDX UDP reader → **OFF**  
- [ ] Broadcast Data → **`127.0.0.1:12060`**  
- [ ] **N1MM agent** running with `WIMS_SERVER` (Log joins **2237** → `:52001`/`:2333`; Broadcast; KEY as needed)  
- [ ] Networked into the **same** contest with the other three N1MMs  
- [ ] Station name unique and stable (WIMS logger id)  
- [ ] 222/432: OK if no WSJT-X this hour (SSB-only); agent can stay up for when FT8 starts  
- [ ] If CAT used: seat middleware path only (§3.2) — not competing with wfview for COM  

### WIMS server
- [ ] Join **`2237`** on the LAN iface (`--ports 2237`)  
- [ ] Solo/lab: `--port 2237` (same fleet port)  
- [ ] N1MM XML via agents (`127.0.0.1:12060` → site); lab may still join `:12060` multicast  
- [ ] No second app sending Reply on managed instances  

### GridTracker (if used)
- [ ] Same multicast **`224.0.0.73:2237`**  
- [ ] No TX / “work this call” that bypasses WIMS  

### Host agents (later)
- [ ] One agent per radio / SSB-CW host for 10 ms mute and thumbnails (design §3.3 / §3.4.1)  

---

## 10. Lab vs full contest

| Lab (dev / single host) | Full contest |
|-------------------------|--------------|
| One N1MM (e.g. Windows VM) + agent | Four N1MMs + agents, networked (plane C) |
| One stream **`2237`** + emulator or few WSJT-X | Multi-host WSJT-X (trailer + remote 50 + dual 144) — still **`:2237`** |
| Optional wfview + Hamlib NET on the radio PC (§3.3) | Same seat pattern per Icom USB radio |
| Optional GridTracker on the WIMS PC | Optional GT per seat / remote PC |
| WIMS with LAN `--iface` + `--ports 2237` | Same server role; join **2237** |
| All processes on one machine | N1MM and WSJT-X **may be different machines/sites** on one LAN |

Scale path: start with `224.0.0.73:2237`, one N1MM + agent; **add another N1MM + agent** when a
second band logger comes online (reader stays OFF). Remote 50 / second 144 PC =
**same port**, extra hosts, **still one N1MM agent Log** for that band.

---

## 11. Design invariants (summary)

1. **Open monitoring** — any number of subscribers on a stream (WIMS, N1MM, GridTracker).  
2. **Singular control** — one logger-of-record per WSJT-X; one TX controller (lease) per managed instance; one rotator controller per rotator.  
3. **WIMS never logs** — path is WSJT-X → N1MM; WIMS reads.  
4. **No unattended TX** — human click + valid lease; else RX-only.  
5. **One signal per band** — multi-instance same band share one resource group.  
6. **Server is site-local for radio UDP** — remote consoles are unicast only.  
7. **CAT is seat-local** — WIMS never owns radio COM/CI-V/Hamlib; middleware (e.g. wfview) is allowed; one owner of the wire (§3.2–§3.3).  
8. **Plane A port match** — every WSJT-X, WIMS `--ports`, and N1MM agent Log use **`2237`**; N1MM built-in reader **OFF**.  

Core idea in one line:

> **WSJT-X multicasts on `224.0.0.73:2237` → WIMS + per-band N1MM agent Log (filter by dial/RadioInfo) → all N1MMs network the log → browsers only talk to WIMS.**  
> GridTracker is an optional extra subscriber on the same stream, never the control path.

---

## 12. Resilience & guided setup (tired operators, restarts)

The networking map in §§1–11 is **correct but brittle** if humans must remember interfaces,
`2237`, and “keep the N1MM digi reader OFF / run the agent.” Seats such as **222 and 432** are
often run by operators who are **not steeped in WIMS design**; people get tired; PCs and radios
get restarted mid-contest. This section is how WIMS stays **safe and diagnosable** under those
conditions.

Cross-refs: design §2.5 (network health), §3.3 (setup wizard), §3.14 (profiles), §3.15
(discovery), scenarios S1 / I1–I3.

### 12.1 Problem

| Failure | Typical cause after restart / fatigue |
|---------|--------------------------------------|
| WSJT-X on `127.0.0.1` | Default / “it worked on this PC” |
| **UDP Outgoing interface blank / `@Invalid()`** | Never set after install; **decodes work, WIMS sees nothing** |
| Wrong UDP port (not **2237**) | Config copied from old Scheme A band map |
| N1MM external broadcast not `127.0.0.1:12060` | Still pointing at Tailscale / wrong dest |
| N1MM built-in WSJT reader left **ON** | Double-log with agent Log |
| Two digi log paths for one QSO | Reader ON and/or Secondary 2333 **and** agent Log |
| Duplicate `--rig-name` | Cloned desktop shortcut |
| WSJT-X up, N1MM down (or reverse) | Partial restart |
| WIMS never sees the seat | Server `--iface`, IGMP, wrong port join |
| “Fine locally, dead on console” | Loopback server, unset outgoing iface, or host firewall |
| N1MM Network Status sees peers, **Send/Receive** not OK | Windows network is **Public** — gold-image N1MM rules **Allow** on Private and **Block** on Public. TCP **12070** times out (`SYN_SENT`); UDP discovery still works. Fix: `Set-ContestLanPrivate.cmd` on **each** N1MM PC (or Settings → Network profile → Private) |

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
   the seven WSJT-X ids, four N1MM station names, plane A `224.0.0.73:2237`, logger-of-record,
   resource groups. That file *is* the networking map in machine-readable form. Operators do not
   edit it mid-event.
2. **At a seat** (especially simple 222/432), the op runs **Bring up ROY-222** (wizard or desktop
   shortcut) — not “configure UDP.” Optionally WIMS/agent **writes or verifies** WSJT-X `.ini` and
   N1MM agent / Broadcast settings against the profile (reader OFF).
3. **Apps start** and emit the usual multicast (plane A) and N1MM XML (plane B via agent).
4. **WIMS server** — already joining **2237** — **passively compares wire traffic to the
   profile** (design §3.15). No Wireshark; no op-interpreted packet counters as the primary UX.
5. **Seat readiness** collapses that comparison into a traffic light plus **one named fault and
   one next step** (e.g. “N1MM-222 not heard — is the N1MM agent running with WIMS_SERVER?”).
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
  multicast: 224.0.0.73:2237
  logger_station_name: N1MM-222    # N1MM StationName as seen on plane B
  resource_group: 222-signal
  host_hint: optional IP/MAC

seat ROY-432:
  band: 432
  wsjtx_id: ROY-432-FT8
  multicast: 224.0.0.73:2237
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
| 2. Apply / verify | Write or check WSJT-X config (**`224.0.0.73:2237`**, Outgoing interface = LAN NIC, rig-name; Secondary 2333 OFF) and N1MM (digi reader **OFF**; Broadcast Data → `127.0.0.1:12060` + N1MM agent). **Refuse green** if `UDPInterface` is empty/`@Invalid`/loopback or WSJT `UDPServer` is `127.0.0.1` in fleet mode |
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
- `N1MM-222 not heard — Broadcast Data → 127.0.0.1:12060 and N1MM agent → site?`
- `WSJT-X id ROY-222-FT8 also from 192.168.10.99 — duplicate rig-name`
- `N1MM-50 appears to be logging ROY-222-FT8 — digi reader ON or agent Log not filtering by band?`
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
| N1MM settings export documented per seat | Broadcast + reader OFF + agent restored as a blob |
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

They never need to know plane-A arithmetic — every seat is `224.0.0.73:2237`. That knowledge
lives in the profile and in the fix text when something drifts.

### 12.11 Build order (minimum viable resilience)

Aligns with design modules; prefer server-side value before perfect agents:

| Priority | Deliverable | Depends on |
|----------|-------------|------------|
| 1 | Contest profile (even hand-edited) listing all expected instances + loggers | Config §3.11 / §3.14 |
| 2 | Expected-vs-actual board on Status with **plain-language** discrepancies | Discovery §3.15 (partially built) |
| 3 | Per-seat readiness 🟢🟡🔴 + one fix string (API + UI) | Profile + discovery |
| 4 | **WSJT-X config validator** as gate: multicast + **LAN Outgoing interface** + not loopback (`wsjtx_config`; **tool exists**); surface on Status | I1 |
| 5 | N1MM broadcast + reader OFF + agent vs profile (read-only) | N1MM settings / agent |
| 6 | Simple-seat wizard (222/432): pick seat → **ini check** → prove wire → green | 3 + 4 |
| 7 | Start scripts / rig-name shortcuts per seat | Packaging |
| 8 | Auto-apply config (including interface name from profile), topology map, agent re-scan | Agent §3.3 |

Fleet server already joins **`2237` only** by default. Lab readiness can still validate a
**subset** profile (one band / few instances) before full microwave seats are live.

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
