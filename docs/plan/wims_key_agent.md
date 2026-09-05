# WIMS Key Agent — design (WIMS only)

**Status:** product path via **`wims.seat`** (2026-09-03).  
**Not** the same program as **inhibit-agent** (that design lives for the **wsjtx-inhibit**
project in [inhibit_agent.md](inhibit_agent.md)).

| Program | Project | Typical use |
|---------|---------|-------------|
| **inhibit-test** / inhibit bench | wsjtx-inhibit / WIMS testbed | Lab / protocol / gate bring-up |
| **inhibit-agent** | wsjtx-inhibit | Dual-radio seat: CTS → **localhost** gate; no other apps required |
| **WIMS seat (`--key`)** | **WIMS** | N1MM / SSB-CW PC: KEY sense + **same-band** digi targets |

---

## Packaging (chosen)

On the N1MM PC, the **N1MM agent** (`wims.seat`) owns live band from Broadcast Data
(RadioInfo). UI sections: **Broadcast** · **Log** · **KEY**.

```bash
python -m wims.seat --log --key    # contest default when both intents on
python -m wims.seat --log          # Broadcast + Log
python -m wims.seat --key          # Broadcast + KEY
```

| Section | Job |
|---------|-----|
| **Broadcast** | Hear N1MM Broadcast Data on `127.0.0.1:12060`; POST XML to site `/api/n1mm/broadcast` |
| **Log** | Fleet digi Logged QSOs → local N1MM (`:52001` / `:2333`) |
| **KEY** | CTS → same-band type-18 holds |

Launcher intents **N1MM** and **SSB/CW KEY** start that one process with the matching
flags. Escapes: `wims.log`, `wims.key daemon` → wrappers.

Modules stay separate; they share **one live band**. Not N1MM networking **:12070**.

---

## Key policy

**Inhibit every digi instance on the same band as this KEY.**

- **KEY band** = N1MM RadioInfo on this PC (same rule as the log agent).  
  **Fail closed:** no holds until a live band is heard.
- **Digi band** = Status dial frequency → `band_label`.  
- **Inhibit address** = UDP source IP of plane-A traffic + **InhibitStatus (type 17)**  
  `inhibit_port`. Both Status and type 17 required before a target is used  
  (no blind assume of 22372 unless `WIMS_KEY_TARGETS` override).
- On QSY: release previous band’s targets; discover on the new band-stream port  
  (plane A port **2237** for all bands).

**Wire:** type-18 `TxInhibit` with stable **Controller ID**  
([`docs/protocols/wsjtx_tx_inhibit.md`](../protocols/wsjtx_tx_inhibit.md)).  
Holds never go through the WIMS server.

**Overrides:** `WIMS_KEY_DEVICE`, `WIMS_KEY_TARGETS=host:port,…`,  
`WIMS_KEY_CONTROLLER_ID`. Lab: `--device sim:up`.

**Hang:** break-in CW adaptive (10.5×dit); continuous KEY / SSB hang 0.  
No software PTT debounce.

---

## Cross-links

| Doc | Role |
|-----|------|
| [inhibit_agent.md](inhibit_agent.md) | **inhibit-agent** (wsjtx-inhibit; no WIMS content) |
| [../protocols/wsjtx_tx_inhibit.md](../protocols/wsjtx_tx_inhibit.md) | **Current wire** (type 18 + leases) |
| [wims_tx_inhibit.md](wims_tx_inhibit.md) | Gate + product / latency design |
| [wims_design.md](wims_design.md) §2.14 | Band policy interlock vs coordinated |
