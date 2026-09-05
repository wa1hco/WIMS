# Decision: Contest PC roles (W2SZ multi-multi)

**Status:** adopted for contest drive (2026-08-29); naming refreshed 2026-09-05  
**Context:** ARRL VHF multi-multi; WSJT-X often on separate PCs from N1MM; many WSJT
instances on the LAN; one N1MM per band (SSB/CW op) is typical logger.

---

## Priority

| Priority | Role | Where it runs |
|----------|------|----------------|
| High | **Site server** | One PC (may be co-located with an N1MM seat) |
| High | **N1MM agent** (`wims.seat`) | Every **N1MM / SSB-CW PC** — Broadcast + Log + optional KEY |
| High | **Config check** (per agent GUI) | Each agent’s compact window — checks only what *that* agent needs |
| Medium | **WSJT monitor** (`wims.agent`) | WSJT-X PC(s) — config audit + monitoring; **not** required for decode/TX |
| Low | **Solo** | Home/lab single-PC only — **out of contest launcher primary UI** |

Solo remains available as CLI (`python -m wims solo`) for testers; it is not a contest
bring-up path.

**Operator how-to:** [../operator_setup.md](../operator_setup.md).

---

## Fleet topology (W2SZ-shaped)

```
  WSJT-X PC(s)                         N1MM / SSB-CW PC(s)
  ┌─────────────────────┐              ┌──────────────────────────────┐
  │ 1..N WSJT-X         │──mcast:2237──│ N1MM (band logger)           │
  │ (often separate PC) │              │ N1MM agent (--log / --key)   │
  │ optional: WSJT      │              │   Broadcast → site server    │
  │   monitor agent     │              │   Log → local N1MM           │
  └─────────────────────┘              │   KEY → same-band holds      │
              │                        └──────────────────────────────┘
              └──────────── WIMS site server ────────┘
                   (roster, Overview / WSJT / N1MM tabs)
```

- **Many** WSJT-X instances on the network; **more than one per PC** is normal.
- N1MM PC → **`wims.seat --log --key`** (N1MM agent).
- That same PC **may also** run the WIMS site server (one server fleet-wide).

---

## Config check as a WIMS function

| Role | Config check focuses on |
|------|-------------------------|
| **Site server** | Bind/join of fleet UDP, HTTP console, presence, seed log path, no second server |
| **N1MM agent Broadcast** | Hear `127.0.0.1:12060`, `WIMS_SERVER` reachable, forward OK |
| **N1MM agent Log** | Join fleet mcast `2237`, live band, deliver TCP **52001** (N1MM digi UDP reader **OFF**) |
| **N1MM agent KEY** | KEY/CTS device, same-band InhibitStatus targets |
| **WSJT monitor** | Each local WSJT-X.ini: UDP `2237`, outgoing iface, Accept UDP, unique `--rig-name`, Secondary UDP off if Log owns logging |

Do **not** require a WSJT monitor for RF operation — decoding and CQ stay in WSJT-X.

---

## Compact GUI (N1MM agent)

Sections: **Broadcast** · **Log** · **KEY** (not a separate “Status” section — that name
is reserved for N1MM Broadcast Data terminology).

Launcher Desktop starts the right intent(s) for “this PC.”

---

## Relation to design functions

- #7 Key — N1MM agent **KEY** on SSB/CW PC  
- #9 Seat agent — reframed as **WSJT monitor** (optional)  
- #10 Log — N1MM agent **Log** ([2026-08-22-remote-n1mm-logging.md](2026-08-22-remote-n1mm-logging.md))  
- Broadcast bridge — N1MM agent **Broadcast** → `/api/n1mm/broadcast`  

---

## Implementation notes

- TCP **52001** preferred for Log delivery; UDP **2333** fallback.  
- Fleet Broadcast Data dest: **`127.0.0.1:12060`** (identical on every logger).  
- Console nav: Operate / Overview / WSJT-X / N1MM / Setup.  
