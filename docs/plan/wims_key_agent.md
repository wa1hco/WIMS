# WIMS Key Agent — design (WIMS project only)

**Status:** design stub for the **WIMS-shipped** multi-station agent.  
**Not** the same program as **inhibit-agent** in **wsjtx-inhibit**.

| Program | Project | Typical use |
|---------|---------|-------------|
| **inhibit-test** | wsjtx-inhibit | Lab / protocol / gate bring-up |
| **inhibit-agent** | wsjtx-inhibit | Simple dual-radio seat: CTS → **localhost** gate; **no WIMS** |
| **WIMS Key agent** | **WIMS** | Fleet: KEY sense + **WIMS-configured target list** of WSJT-X gates |

**Authoritative design for operators without WIMS:**  
**[wsjtx_inhibit_agent.md](wsjtx_inhibit_agent.md)** (copy into the wsjtx-inhibit repo when
implementing).

---

## WIMS Key agent — differences only

1. **Ships with WIMS**, not with the WSJT-X inhibit package.
2. **Target list** of inhibit UDP endpoints (one or many WSJT-X gates on a band), **not**
   localhost-only.
3. **Configuration when under WIMS:** site server (or seat profile) pushes the list of WSJT-X
   stations / `ip:port` gates; agent **persists** last list so inhibit survives server outage.
4. **Configuration when run without a live server:** CLI and/or local file; optional later:
   direct discovery of WSJT-X inhibit listeners — **not** required for inhibit-agent.
5. Optional status **report** into WIMS inventory (SSB keyed, agent health) — never on the
   inhibit critical path.
6. Respects band policy **interlock vs coordinated** ([wims_design.md](wims_design.md) §2.14):
   coordinated ⇒ sense/report only, no holds.
7. Multi-SSB / multi-beam politics live in WIMS design docs, not in inhibit-agent.

**Protocol:** same `tx_inhibit` datagrams as inhibit-test / inhibit-agent / gate.  
**Path:** still **direct UDP generator → gate**, never through the WIMS server.

**Implementation order recommendation:** ship and harden **inhibit-agent** in wsjtx-inhibit
first; implement WIMS Key agent as a separate binary that reuses hang/encode logic and adds
target-list + WIMS integration.

---

## Cross-links

| Doc | Role |
|-----|------|
| [wsjtx_inhibit_agent.md](wsjtx_inhibit_agent.md) | **inhibit-agent** (no WIMS) |
| [wims_tx_inhibit.md](wims_tx_inhibit.md) | Gate + protocol |
| [wims_design.md](wims_design.md) function #5–#7, §2.14 | Fleet assignment / policy |
