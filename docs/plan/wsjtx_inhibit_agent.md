# inhibit-agent — design (wsjtx-inhibit project)

**Status:** design for implementation in **wsjtx-inhibit** (not WIMS).  
**Audience:** wsjtx-inhibit maintainers and operators who use TX Inhibit **without** WIMS.  
**This document does not depend on WIMS.** WIMS is a separate product with its own multi-station
Key agent; see [wims_key_agent.md](wims_key_agent.md) only if you also run a WIMS fleet.

---

## 0. Three inhibit *generators* (same wire protocol)

The TX Inhibit **gate** lives inside WSJT-X (wsjtx-inhibit). It listens for UDP datagrams and
masks PTT. Anything that *sends* those datagrams is an **inhibit generator**. There are three:

| Program | Ships with | Role |
|---------|------------|------|
| **inhibit-test** | **wsjtx-inhibit** | Existing lab / bench tool: keyboard, script, or serial → holds to a gate (often loopback). Proves the gate and protocol. |
| **inhibit-agent** | **wsjtx-inhibit** | **This document.** Production-simple sense of SSB/CW KEY (CTS) → holds to **localhost** gate. Zero WIMS. |
| **WIMS Key agent** | **WIMS** | Fleet multi-target agent; WIMS configures the WSJT-X station/target list. Different binary and product. |

All three speak the same **tx_inhibit** datagram protocol (see wsjtx-inhibit gate docs /
[wims_tx_inhibit.md](wims_tx_inhibit.md) §11.3 for the field layout already used in the field).

**Inhibit datagrams are never routed through a WIMS server.** They always go generator → UDP →
gate (typically on the same machine as localhost for inhibit-agent).

**History:** wsjtx-inhibit briefly folded “live KEY → inhibit” into the same tree as the gate.
That was pulled back so the **gate** stays simple, reliable, and minimally configured.  
**inhibit-agent** reintroduces KEY sensing as a **separate small program** in the same
*project family*, not as complexity inside the gate.

**Naming:** preferred program name **`inhibit-agent`**. Acceptable alternatives if packaging
needs them: `tx-inhibit-agent`, `keyline-agent`. Avoid “Key agent” / “WIMS Key Agent” in this
project — those names belong to WIMS.

---

## 1. Purpose

Give **SSB/CW KEY priority over WSJT-X transmit** on a dual-radio (or dual-mode) station:

1. Sense the SSB/CW **KEY/PTT line** (USB-serial **CTS**).
2. While KEY is asserted, send **TX Inhibit hold** datagrams to the **local** WSJT-X gate
   (`127.0.0.1`, fixed gate port).
3. On KEY release, apply hang, then send **release** (`ttl_ms: 0`).

No site server, no target list, no fleet discovery. Configuration should feel as simple as
**inhibit-test**.

---

## 2. Station model

One band, two radios (or one shared shack), shared antenna plant:

```
                    ┌─────────────────┐
   Antenna ──split──┤ RX (both always)├──► SSB/CW radio
            │       │                 ├──► WSJT-X radio  (listens continuously)
            │       └─────────────────┘
            │
            │  TX path — SO2R / first-KEY hardware picks one RF source
            └──────► relays / amp / antenna
                     ▲
                     └── KEY/PTT from either radio
```

### 2.1 RF facts

1. **RX split:** both radios can hear when not transmitting; WSJT-X **stays in RX** during
   SSB/CW receive and during many voice overs.
2. **TX hardware:** SO2R-class interlock (or equivalent) so only one radio’s RF keys the
   amp/antenna (often first KEY wins).
3. **Software gap:** WSJT-X can still assert **PTT** while voice is keyed unless something
   masks it. **inhibit-agent + gate** close that gap: **SSB KEY → inhibit digital PTT**.
4. **FT8 still useful under voice TX (W2SZ experience):** losing a few seconds of audio in a
   15 s period rarely kills decodes unless the signal is extremely weak. So continuous FT8
   RX while SSB runs CQ or works stations is operationally valuable.

### 2.2 When inhibit-agent is needed

| Situation | inhibit-agent? |
|-----------|----------------|
| Operator **manually** stops SSB before using WSJT-X; never keys both | **Not required** (hardware SO2R still wise) |
| **Two operators** (or one op who leaves WSJT Enable Tx / CQ on while keying SSB) | **Yes** — SSB KEY must inhibit WSJT PTT |
| Lab / bring-up without a real KEY line | Use **inhibit-test**, not inhibit-agent |

Fleet multi-beam assignment and multi-SSB politics are **out of scope** here (WIMS).

### 2.3 Host placement

**inhibit-agent runs on the WSJT-X PC** and sends UDP to **`127.0.0.1`** (the local gate).

The **KEY line** from the SSB/CW radio must reach that PC’s serial CTS (or the process cannot
sense it). That is fine when:

- SSB/CW and WSJT-X are **the same PC**, or  
- the PCs are **adjacent** and KEY is wired (or a Keyline dongle is) to the **WSJT-X** machine.

If KEY is only available on a remote SSB PC and cannot be brought to the WSJT-X host, this
simple agent is the wrong tool (that is a multi-host product problem, not inhibit-agent MVP).

---

## 3. Program shape

| Item | Spec |
|------|------|
| **Name** | `inhibit-agent` |
| **Project** | **wsjtx-inhibit** (sibling to the gate and **inhibit-test**) |
| **Process** | Long-running; console is enough for v1 |
| **Language** | Match wsjtx-inhibit packaging (native or scripted — implementer’s choice); protocol compatible with existing gate |
| **I/O** | One serial port (CTS); one UDP socket to localhost |

```
  SSB/CW KEY ──wire──► [CTS on WSJT-X PC]
                              │
                       [ inhibit-agent ]
                              │
                    UDP 127.0.0.1:22372   (or configured local port)
                              │
                       [ WSJT-X gate ]
                              │
                         radio PTT
```

---

## 4. Responsibilities

### 4.1 Must do

1. Open a user-specified **COM port** / **`/dev/ttyUSB*`** (or documented auto-pick of a Keyline
   device **only if** still one clear choice — default is **explicit port**).
2. Read **CTS only** (document invert flag if hardware is active-high).
3. On KEY assert: send **hold** datagrams to **localhost** gate port.
4. While KEY held: **keepalive** holds (e.g. every 200 ms).
5. On KEY release: **hang**, then **release** (`ttl_ms: 0`).
6. Fail-safe: if the agent stops, holds stop → gate deadman clears → digital TX may resume
   (prefer brief unprotected window over stuck inhibit).
7. Console state: `OPEN` / `INHIBITING` / `HANG` / `SENSE FAULT`.

### 4.2 Must not do

1. Maintain a **target list** of remote stations (always localhost).
2. Talk to WIMS, N1MM, or GridTracker.
3. Implement SO2R RF switching.
4. Block or filter **decode** (TX path only).
5. Require multi-SSB or multi-beam configuration.

### 4.3 Configuration (as simple as inhibit-test)

Goal: same cognitive load as running **inhibit-test**.

```text
inhibit-agent --port COM7
inhibit-agent --port /dev/ttyUSB0
inhibit-agent --port COM7 --invert
inhibit-agent --port COM7 --gate-port 22372
```

Optional (defaults are fine for production):

| Flag | Default | Notes |
|------|---------|--------|
| `--port` | **required** | COM / tty device |
| `--invert` | false | CTS polarity |
| `--gate-host` | `127.0.0.1` | Local only for this product |
| `--gate-port` | `22372` | Must match WSJT-X gate bind |
| `--keepalive-ms` | `200` | While KEY down |
| `--hang-ms` | adaptive or fixed per gate companion docs | Prefer one clear default |

**No** station roster, **no** WIMS URL, **no** multi-target file for MVP.

### 4.4 Datagram fields `band` and `station`

For the local gate these fields are **not** used for routing. Set them to **fixed dummy
values that identify this program**, for Wireshark / logs only, e.g.:

| Field | Value |
|-------|--------|
| `station` | `inhibit-agent` |
| `band` | `local` (or `-`) |

Do not invent real band labels or callsigns in the agent.

**Protocol reference:** same JSON/`tx_inhibit` layout as inhibit-test and the gate
([wims_tx_inhibit.md](wims_tx_inhibit.md) §11.3 if reading from the WIMS tree; copy into
wsjtx-inhibit docs when implementing).

---

## 5. Relationship to inhibit-test

| | **inhibit-test** | **inhibit-agent** |
|--|------------------|-------------------|
| Purpose | Prove gate / protocol / latency | Daily SSB priority at a real seat |
| KEY input | keyboard, script, optional serial | **Serial CTS only** (production) |
| Destination | often configurable | **localhost only** |
| Hang / keepalive | may be minimal | full hold/hang/release for voice KEY |
| Audience | developers, bring-up | operators with dual radio + gate binary |

Share code for encode/decode and hang math where practical; keep **two entry points** so
operators never confuse “test harness” with “always-on agent.”

---

## 6. Acceptance tests

1. **Bench:** gate + inhibit-agent + KEY (or CTS jumper). KEY down → PTT/RTS to radio stays
   off while WSJT shows TX intent; KEY up + hang → PTT can assert again.
2. **Dummy load:** WSJT CQ enabled; key SSB → no digital RF; FT8 still decodes in RX.
3. **Kill agent mid-KEY:** within deadman TTL, gate opens (document the window).
4. **Wrong COM:** clear SENSE FAULT, no silent “protection.”

---

## 7. Implementation notes (wsjtx-inhibit tree)

Suggested layout (illustrative):

```text
wsjtx-inhibit/
  docs/INHIBIT_AGENT.md      # this design, once moved
  tools/inhibit-test/        # existing
  tools/inhibit-agent/       # this program
  ... gate in WSJT-X ...
```

Ship inhibit-agent beside inhibit-test in release notes: “optional KEY sense for SSB
priority; not required for gate-only use.”

---

## 8. Out of scope (explicit)

- WIMS site server, fleet inventory, target assignment UI  
- Multi-beam fan-out, multi-SSB arbitration  
- Running the agent only on a remote SSB PC with non-local UDP to the gate (WIMS Key agent
  territory if needed later)  
- Changing the gate’s internal simplicity

---

## 9. Summary

**inhibit-agent** is a **wsjtx-inhibit** tool: open a **COM/tty**, watch **CTS**, send
**inhibit holds to localhost**. Same protocol as **inhibit-test**, simpler ops model than any
WIMS component, no WIMS dependency, no target list. Use it when SSB/CW and WSJT-X share a
band and voice KEY must suppress digital PTT while FT8 keeps listening.
