# Decision: Plane A uses a single UDP port — 2237

**Status:** adopted for current fleet / operator docs (2026-09-05)  
**Supersedes (for operators):** per-band port table 2238–2243 in older networking drafts.

## Decision

All WSJT-X instances and the WIMS site server join:

```text
224.0.0.73:2237
```

Bands are **not** separated by UDP port. Distinguish instances with unique `--rig-name`
(UDP id). Band for roster / Log / KEY comes from **Status dial frequency** (and N1MM
RadioInfo on the logger PC), not from the UDP port number.

**N1MM’s built-in WSJT/JTDX UDP reader stays OFF.** Digi → N1MM logging is the
**N1MM agent Log** path (mcast `2237` → localhost `:52001`/`:2333`), not N1MM joining
plane A as a reader.

## Why

- Operators were still being told “144 → 2238, 432 → 2241…” after the fleet had moved
  to one port — docs and code defaults disagreed with reality.
- One port removes the empty-roster class of “WSJT on 2238, WIMS still on 2237.”
- Multi-instance on one LAN already requires unique `--rig-name`; that is enough identity.

## Code / docs

- Site server default `--ports` → **`2237`** only (override with comma list for lab).
- KEY discovery joins **2237** for every band label.
- Operator docs (`operator_setup.md`, User-manual, tester_*) describe **2237 only**.
- [wims_networking.md](../plan/wims_networking.md) leads with **2237 + agent**; §4.3 / §4.5 /
  §4.9 multi-port Scheme A remains **historical / optional lab** only.

## Escape hatch

Lab or experiments may still pass `--ports 2237,2238,…`. That is not the contest default.
