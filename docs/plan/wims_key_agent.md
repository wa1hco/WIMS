# WIMS Key Agent — design (WIMS only)

**Status:** design stub for the agent **shipped with WIMS**.  
**Not** the same program as **inhibit-agent** (that design lives for the **wsjtx-inhibit**
project in [inhibit_agent.md](inhibit_agent.md) — copy that file into wsjtx-inhibit; it
mentions nothing about WIMS).

| Program | Project | Typical use |
|---------|---------|-------------|
| **inhibit-test** | wsjtx-inhibit | Lab / protocol / gate bring-up |
| **inhibit-agent** | wsjtx-inhibit | Dual-radio seat: CTS → **localhost** gate; no other apps required |
| **WIMS Key agent** | **WIMS** | Fleet: KEY sense + **WIMS-configured** multi-target list |

---

## WIMS Key agent — differences from inhibit-agent

1. **Ships with WIMS**, not with the WSJT-X inhibit package.
2. **Target list** of inhibit UDP endpoints (one or many gates), not localhost-only.
3. **Under WIMS:** server pushes the list of WSJT-X stations / `ip:port`; agent **persists**
   last list so inhibit survives server outage.
4. **Without a live server:** CLI and/or local file; optional later discovery — separate from
   inhibit-agent’s single-port simplicity.
5. Optional **status report** into WIMS inventory (SSB keyed, health) — not on the inhibit path.
6. Band policy **interlock vs coordinated** ([wims_design.md](wims_design.md) §2.14):
   coordinated ⇒ sense/report only, no holds.
7. Multi-SSB / multi-beam assignment policy lives in WIMS design docs.

**Protocol:** same **type-18** `NetworkMessage::TxInhibit` datagrams as the gate and
inhibit-test / inhibit-agent (per-Controller ID leases). See
[`docs/protocols/wsjtx_tx_inhibit.md`](../protocols/wsjtx_tx_inhibit.md).  
JSON `tx_inhibit` from the early spike is obsolete and will not hold a patched station.  
**Path:** still **direct UDP → gate**, never through the WIMS server.

**Hang (same as inhibit-agent):** break-in CW only. Continuous KEY / SSB PTT releases
immediately. **No software PTT debounce** — the sense path is for **manual switches
that already debounce** (Keyline, footswitch, hand mic). Hang exists only so the
WSJT-X radio’s PTT does not follow CW dits.

**Order:** implement and harden **inhibit-agent** in wsjtx-inhibit first; WIMS Key agent later
as a separate binary with target-list + WIMS integration.

## Cross-links

| Doc | Role |
|-----|------|
| [inhibit_agent.md](inhibit_agent.md) | **inhibit-agent** (wsjtx-inhibit; no WIMS content) |
| [../protocols/wsjtx_tx_inhibit.md](../protocols/wsjtx_tx_inhibit.md) | **Current wire** (type 18 + leases) — implement from here |
| [wims_tx_inhibit.md](wims_tx_inhibit.md) | Gate + product design (WIMS companion; §11.3 JSON historical) |
| [wims_design.md](wims_design.md) §2.14, functions #5–#7 | Fleet policy / assignment |
