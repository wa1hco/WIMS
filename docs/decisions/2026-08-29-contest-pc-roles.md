# Decision: Contest PC roles (W2SZ multi-multi)

**Status:** adopted for contest drive (2026-08-29) — replaces Solo-first launcher emphasis  
**Context:** ARRL VHF multi-multi; WSJT-X often on separate PCs from N1MM; many WSJT
instances on the LAN; one N1MM per band (SSB/CW op) is typical logger.

---

## Priority

| Priority | Role | Where it runs |
|----------|------|----------------|
| High | **Site server** | One PC (may be co-located with an N1MM seat) |
| High | **Log agent** | Every **N1MM PC** |
| High | **Key agent** | N1MM / SSB-CW PC (KEY sense → inhibit fan-out) |
| High | **Config check + monitor** (per agent) | Each agent’s compact GUI — checks only what *that* agent needs |
| Medium | **WSJT seat agent** | WSJT-X PC(s) — not required to decode/TX; exists for **config audit + monitoring** |
| Low | **Solo** | Home/lab single-PC only — **out of contest launcher primary UI** |

Solo remains available as CLI (`python -m wims solo`) for testers; it is not a contest
bring-up path.

---

## Fleet topology (W2SZ-shaped)

```
  WSJT-X PC(s)                         N1MM / SSB-CW PC(s)
  ┌─────────────────────┐              ┌──────────────────────────────┐
  │ 1..N WSJT-X         │──mcast:2237──│ N1MM (band logger)           │
  │ (often separate PC) │              │ Log agent  (mcast→localhost) │
  │ optional: seat      │              │ Key agent  (KEY→inhibit)     │
  │   agent = config +  │              │ optional: WIMS site server   │
  │   monitor only      │              │ compact GUI per agent        │
  └─────────────────────┘              └──────────────────────────────┘
              │                                      │
              └──────────── WIMS site server ────────┘
                   (roster, inventory, assignments)
```

- **Many** WSJT-X instances on the network; **more than one per PC** is normal.
- N1MM PC is usually the **SSB/CW operator’s logging seat** → **log agent + key agent**.
- That same PC **may also** run the WIMS site server (one server fleet-wide).

---

## Config check as a WIMS function (not a separate product)

Move “is this PC set up right?” into **each WIMS role**, scoped to what that role touches:

| Role | Config check focuses on |
|------|-------------------------|
| **Site server** | Bind/join of fleet UDP, HTTP console, presence, seed log path, no second server |
| **Log agent** | Join `224.0.0.73:2237`, band pin, N1MM localhost delivery (TCP **52001** preferred), firewall/Private |
| **Key agent** | KEY/CTS device, inhibit targets / assignment, band policy interlock vs coordinated |
| **WSJT seat agent** | Each local WSJT-X.ini: UDP group/port, outgoing iface, Accept UDP, unique `--rig-name`, Secondary UDP off if log agent owns logging |

Do **not** require a WSJT seat agent for RF operation — decoding and CQ stay in WSJT-X.
The agent’s reason to exist on a WSJT PC is **verify + watch** interconnect and settings.

Same for N1MM: the log/key agents exist because the seat needs **reliable logging and
inhibit**, plus **continuous proof** that N1MM/WSJT/WIMS wiring still matches the plan.

---

## Compact GUI per agent (target UX)

Each long-running agent gets a small local window (tkinter or existing `:8790` style), not
the full Operate roster:

- **Status** — running / last QSO forwarded / KEY up / last error
- **Interconnect** — multicast joined? N1MM TCP up? server reachable?
- **Fleet SW configuration** — results of the scoped config check (OK / warn / fail)
- **Actions** — Rescan config, Open site Status (if known), Quit

Launcher on the Desktop starts the right role(s) for “this PC.”

---

## Relation to earlier Switchboard function table

Extends [wims_design.md](../plan/wims_design.md) functions #7 and #9:

- #7 Key agent — still SSB/CW sense PC (often = N1MM PC)
- #9 Seat agent — reframed as **WSJT seat monitor/config** (optional for TX path)
- **New explicit:** Log agent on N1MM PC ([2026-08-22-remote-n1mm-logging.md](2026-08-22-remote-n1mm-logging.md))

---

## Implementation notes

- **Log helper compact GUI + scoped checks:** shipped as `python -m wims.log`
  (Tk status window; Start seat opens it). TCP **52001** send path still follow-on
  (checks already probe 52001; delivery remains UDP 2333 until that lands).
- **Key helper GUI / daemon:** still follow-on.
- This decision sets the **role model** and launcher emphasis.
