# inhibit-agent — design

**Status:** implemented in **wsjtx-inhibit** (`tools/inhibit-agent/`).  
**Audience:** wsjtx-inhibit maintainers and operators who use TX Inhibit on a dual-radio
seat.  
**Scope:** this program only. Gate internals and packaging live in the same project’s
other docs.

---

## 0. Inhibit generators (same wire protocol)

The TX Inhibit **gate** lives inside WSJT-X (wsjtx-inhibit). It listens for UDP datagrams
and masks PTT. Programs that **send** those datagrams are inhibit generators:

| Program | Role |
|---------|------|
| **inhibit-test** | Existing lab / bench tool: keyboard, script, or serial → holds to a gate (often loopback). Proves the gate and protocol. |
| **inhibit-agent** | **This document.** Production-simple sense of SSB/CW KEY (CTS) → holds to **localhost**. |

Both speak the same **tx_inhibit** datagram protocol (see the project’s gate / protocol
docs; field layout already used by inhibit-test and the gate).

**History:** KEY sensing was briefly considered inside the same package as the gate. It was
separated so the **gate** stays simple, reliable, and minimally configured. **inhibit-agent**
is a **separate small program** in the same project family.

**Name:** preferred **`inhibit-agent`**. Acceptable alternatives if packaging needs them:
`tx-inhibit-agent`, `keyline-agent`.

---

## 1. Purpose

Give **SSB/CW KEY priority over WSJT-X transmit** on a dual-radio station:

1. Sense the SSB/CW **KEY/PTT line** (USB-serial **CTS**).
2. While KEY is asserted, send **TX Inhibit hold** datagrams to the gate
   (CLI: caller’s `host:port`; GUI: `127.0.0.1:22372` unless overridden).
3. On KEY release: if the line looks like **break-in CW**, apply hang then **release**
   (`ttl_ms: 0`); if it is a **continuous** KEY (SSB / PTT / non-break-in), **release
   immediately**. No software PTT debounce — the sense path is built for **manual
   switches that already debounce**.

No remote target list, no network service dependency. Configuration should feel as simple as
**inhibit-test**.

---

## 2. Station model

One band, two radios and one or two PC, shared antenna plant:

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
4. **FT8 under voice TX (field experience):** losing a few seconds of audio in a 15 s period
   rarely kills decodes unless the signal is extremely weak. Continuous FT8 RX while SSB runs
   CQ or works stations is operationally valuable.

### 2.2 When inhibit-agent is needed

| Situation | inhibit-agent? |
|-----------|----------------|
| Operator **manually** stops SSB before using WSJT-X; never keys both | **Not required** (hardware SO2R still wise) |
| WSJT Enable Tx / CQ left on while SSB is keyed (one or two operators) | **Yes** — SSB KEY must inhibit WSJT PTT |
| Lab / bring-up without a real KEY line | Use **inhibit-test** |

### 2.3 Host placement

**inhibit-agent usually runs on the WSJT-X PC.** The GUI defaults to
**`127.0.0.1:22372`**. The CLI takes an explicit **`host:port`** so scripts can
aim at a local or LAN gate.

The **KEY line** from the SSB/CW radio must reach that PC’s serial CTS. That is fine when:

- SSB/CW and WSJT-X share **one PC**, or  
- the PCs are **adjacent** and KEY is wired (or a Keyline-style dongle is) to the **WSJT-X**
  machine.

---

## 3. Program shape

| Item | Spec |
|------|------|
| **Name** | `inhibit-agent` |
| **Project** | **wsjtx-inhibit** (beside the gate and **inhibit-test**) |
| **Process** | Long-running. **CLI** (`inhibit-agent`) for scripts; **GUI** (`inhibit-agent-gui`) for operators. Linux and Windows. |
| **I/O** | One serial port (CTS); one UDP socket to a single `host:port` |

```
  SSB/CW KEY ──wire──► [CTS on WSJT-X PC]
                              │
                       [ inhibit-agent ]
                              │
                    UDP 127.0.0.1:<gate-port>
                              │
                       [ WSJT-X gate ]
                              │
                         radio PTT
```

---

## 4. Responsibilities

### 4.1 Must do

1. **CLI:** open the caller’s **COM / tty** (required). **GUI:** auto-pick Keyline
   (USB string WA1HCO / Keyline) or the only USB-serial port — no COM to type.
2. Read **CTS only** (optional invert flag if hardware is active-high).
3. On KEY assert: send **hold** datagrams to the dest `host:port`.
4. While KEY held: **keepalive** holds (default every 200 ms).
5. On KEY release: **hang only for break-in CW**, then **release** (`ttl_ms: 0`).
   Continuous KEY (SSB / PTT / non-break-in) releases **immediately**. **Do not
   debounce PTT in software** — Keyline / footswitch / hand-PTT already include
   debounce. Hang exists only so WSJT-X PTT does not follow CW dits.
6. Fail-safe: if the agent stops, holds stop → gate deadman clears → digital TX may resume
   (prefer brief unprotected window over stuck inhibit).
7. Console state: `OPEN` / `INHIBITING` / `HANG` / `SENSE FAULT`.

### 4.2 Must not do

1. Maintain a **list** of remote gate addresses (one dest only; CLI names it).
2. Implement SO2R RF switching.
3. Block or filter **decode** (TX path only).
4. Depend on any other application for configuration or runtime.

### 4.3 Configuration (as simple as inhibit-test)

```text
inhibit-agent --port COM7 --addr 127.0.0.1:22372
inhibit-agent --port /dev/ttyUSB0 --addr 127.0.0.1:22372
inhibit-agent COM7 192.168.1.40:22372
inhibit-agent --port COM7 --addr 127.0.0.1:22372 --invert
inhibit-agent-gui
```

| Flag | CLI | GUI | Notes |
|------|-----|-----|--------|
| `--port` | **required** | optional | COM / tty. GUI auto-picks Keyline / only USB-serial |
| `--addr` | **required** | optional | `host:port`. GUI default `127.0.0.1:22372` |
| `--invert` | optional | optional | CTS polarity |
| hang | project default | same | **CW only** (same classifier as inhibit-test). Continuous KEY hang = **0**. No PTT-debounce flag. |

### 4.4 Datagram fields `band` and `station`

Not used for routing on the local gate. Set to **fixed dummy values that identify this
program** (Wireshark / logs only), e.g.:

| Field | Value |
|-------|--------|
| `station` | `inhibit-agent` |
| `band` | `local` |

Protocol: same layout as **inhibit-test** and the gate (project protocol doc).

---

## 5. Relationship to inhibit-test

| | **inhibit-test** | **inhibit-agent** |
|--|------------------|-------------------|
| Purpose | Prove gate / protocol / latency | Daily SSB KEY priority at a seat |
| KEY input | keyboard, script, optional serial | **Serial CTS** (production) |
| Destination | often configurable | CLI: one `host:port`; GUI: localhost default |
| Hang / keepalive | may be minimal | hold + keepalive; **CW hang only**; voice/PTT hang = 0 |
| Audience | developers, bring-up | operators with dual radio + gate binary |

Share encode/hang code where practical; keep **two entry points** so “test harness” is not
confused with “always-on agent.”

---

## 6. Acceptance tests

1. **Bench:** gate + inhibit-agent + KEY (or CTS jumper). KEY down → PTT to radio stays off
   while WSJT shows TX intent; KEY up + hang → PTT can assert again.
2. **Dummy load:** WSJT CQ enabled; key SSB → no digital RF; FT8 still decodes in RX.
3. **Kill agent mid-KEY:** within deadman TTL, gate opens (document the window).
4. **Wrong COM:** clear SENSE FAULT, no silent “protection.”

---

## 7. Implementation notes

Suggested layout (illustrative):

```text
wsjtx-inhibit/
  docs/INHIBIT_AGENT.md      # this design
  tools/inhibit-test/        # existing
  tools/inhibit-agent/       # this program
  ... gate in WSJT-X ...
```

Release note: “optional KEY sense for SSB priority; not required for gate-only use.”

---

## 8. Out of scope

- Multi-host target lists or remote fan-out  
- Multi-SSB arbitration  
- Changing the gate’s internal simplicity  
- Any dependency on other ham-logging or contest-console software  

---

## 9. Summary

**inhibit-agent** watches **CTS** on a USB-serial port and sends **inhibit holds** to one
gate address. CLI takes port + `host:port` for scripts; GUI auto-detects and needs no
config. Same protocol as **inhibit-test**.
