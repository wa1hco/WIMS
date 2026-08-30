# Decision: Remote WSJT-X → N1MM logging (2333 / 52001 / log agent)

**Status:** direction set; **localhost delivery leaning TCP 52001** (2026-08-29)  
**Participants:** Jeff WA1HCO, Roger W3SZ (email); public N1MM forum trail below  
**Sources:**

- Email Jeff → Roger/Ed/Fred (Sat 2026-08-22); Roger reply same day; Jeff follow-up Sun 2026-08-23
- Lab retest Aug 2026 (Wireshark + insert); ON4ACP / N2AMG 2019 thread
- N1MM docs: [Sending Log Data](https://n1mmwp.hamdocs.com/sending-log-data-to-n1mm/), Configurer WSJT/JTDX Setup

---

## Problem

Fleet WSJT-X instances share **one** multicast decode stream (`224.0.0.73:2237`) so WIMS
(and optionally GridTracker) can see all bands. The band’s N1MM must **not** join that
group as a WSJT reader — it would log every instance / every band.

Need: **WSJT-X on PC A logs to N1MM on PC B**, without putting logging through WIMS.

## Port facts

| Port | Who | Behavior |
|------|-----|----------|
| **UDP 2237** | WSJT-X → group | Full protocol (decodes, status, QSO Logged). N1MM reader joining this = over-log. |
| **UDP 2333** | Secondary ADIF / JTAlert → N1MM | Documented unicast log path. See **UDP 2333 behavior** below. |
| **TCP 52001** | JTDX / “Others” → N1MM | N1MM is TCP server; **LAN client works** (lab + firewall/Private). Same ADIF `Log` envelope. Label says JTDX; treat as N1MM’s open TCP log API. |
| **TCP 52002/52004** | N1MM-launched WSJT | CAT/PTT, **not** logging. |

Envelope for 2333 and 52001 (N1MM “Sending Log Data”):

```text
<command:3>Log <parameters:nnnn> …ADIF… <EOR>
```

---

## UDP 2333 behavior (comments + lab)

### Observed (not a “socket closed” failure)

1. **ON4ACP (2019)** — [N1MMLoggerPlus #44025](https://groups.io/g/N1MMLoggerPlus/message/44025): Linux → N1MM on another PC, port 2333, documented ADIF format. `netstat` shows N1MM **`0.0.0.0:2333`**. Wireshark: packets arrive. **No QSO in N1MM.**
2. **Rick Ellison N2AMG** (reply): works with **localhost**; **had not tried** a real IP.
3. **WA1HCO lab (2026-08):** same pattern — bind `0.0.0.0:2333`, LAN datagrams visible, **`127.0.0.1:2333` inserts**, remote PC does not. Pointing N1MM’s WSJT UDP IP at the sender did not help.
4. Official “Sending Log Data” still defaults **`127.0.0.1:2333`** for WSJT-X/JTAlert UDP — no clear statement that LAN sources are supported.

**Reading:** not “N1MM isn’t listening.” Packets hit the NIC and the wildcard bind; **inserts appear filtered to loopback sources** (undocumented; never clearly called intentional). No public N1MM-dev statement found that remote-2333 is *designed* to fail — only years of “localhost works / remote doesn’t.”

### Coupling to UDP 2237 (UI, not “2333 needs 2237”)

Configurer **WSJT/JTDX Setup** uses **one Enable + IP + UDP port** for:

| When | That UDP port field | Meaning |
|------|---------------------|---------|
| Load WSJT from N1MM / Decode List | typically **2237** | Full WSJT UDP protocol |
| Independent JTAlert / Secondary ADIF | set to **2333** | Log envelope only |

Docs say: if the digi app is **not** launched from N1MM, change that port to **2333**. Operators often hear this as “2333 is tied to 2237.” Accurate statement: **same Enable/IP UI switches role with the port number.** Separate Enable exists for **JTDX/Others TCP (52001)**.

Unrelated but adjacent: **2237 unicast conflicts** when JTAlert and N1MM both want `127.0.0.1:2237` (decode path) — different problem from remote-2333 inserts.

### Docs vs practice

W3SZ PackRats beginner PDF and many guides still describe Secondary UDP → N1MM **2333** with the N1MM PC’s IP, as if remote works. Field evidence says treat **remote 2333 as unreliable**.

---

## Roger W3SZ recommendation (2026-08-22)

1. Unmodified WSJT-X **Secondary UDP** (ADIF) → IP of the N1MM PC.
2. **Helper on the N1MM PC** delivers to N1MM as **localhost** (2333 and/or 52001).
3. Don’t add another WSJT-X TCP log setting if a helper suffices; Secondary “deprecated” ≠ removal.
4. Low odds N1MM will fix remote-2333.

## Jeff follow-up / WIMS tilt (2026-08-23)

Ops risk: silent failure if helper isn’t up after reboot. Prefer agent that:

- Joins **multicast `:2237`**
- Filters to **this N1MM’s band**
- Forwards to **localhost** N1MM (no remote 2333)

→ `testbed/log_agent.py` (2026-08-23).

---

## Current lean (2026-08-29): prefer **TCP 52001** for agent → N1MM

**Coded in `wims.log`:** deliver Log envelope to **`127.0.0.1:52001`** first (N1MM
“JTDX / Others TCP”), fall back to UDP **2333**. UDP sendto alone can report FWD
with no N1MM insert when nothing is listening.

**Keep the TCP session open** (JTDX does). Connect-send-close per QSO still
inserts the contact, then N1MM `LoggingTCPListening` pops an error box:
`Unable to read data from the transport connection` / WSAECONNABORTED
(lab 2026-08-29, `logerror.txt`). Helper holds one socket for the process
lifetime and FIN-closes it only on quit.

**Why:**

- Same envelope; N1MM documents it as a first-class ingest beside 2333.
- Lab already proved **TCP 52001 accepts a real client** (LAN and thus trivially localhost).
- UDP 2333’s insert path has a **multi-year remote-ignore cloud**; even for localhost-only helper use, 52001 is the clearer “API” (connect, send, ACK) and avoids hoping UDP filter quirks stay friendly.
- “JTDX” in the label = historical client name; treat as **Others TCP log standard**.

**Still acceptable:** localhost **UDP 2333** as a fallback if 52001 is disabled on a seat.

Roger’s architecture (helper on N1MM PC) stands either way; only the **localhost leg** preference is 52001.

---

## What code does today

`testbed/log_agent.py` / `Start-LogAgent.cmd`:

- Join `224.0.0.73:2237`
- Band-pin from hostname / `--band`
- Forward ADIF to **`127.0.0.1:2333`** (legacy default — **update toward 52001**)

## Remaining product work

1. Switch agent default (and docs) to **TCP `127.0.0.1:52001`**; keep `--n1mm` / flag for 2333 fallback.
2. Seat lifecycle: auto-start, Status health, loud failure if agent/N1MM TCP down.
3. Band detection: hostname pin vs live N1MM band.
4. Optional: Secondary UDP → helper as belt-and-suspenders (Roger’s literal path).

## Do not confuse

- **52001** = TCP log API on N1MM (preferred agent delivery).
- **2333** = UDP ADIF ingest (same-PC tradition; remote inserts untrusted).
- **2237** = fleet decode/control multicast for WIMS — not the remote-log unicast to N1MM.
