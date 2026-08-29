# Decision: Log helper band follows live N1MM RadioInfo

**Status:** adopted 2026-08-29  
**Context:** One N1MM per PC; its band setting is correct except briefly during setup.

## Rules

1. The **log helper** does **not** permanently trust the launcher band picker / hostname pin
   as the QSO filter.
2. It listens for N1MM **RadioInfo** UDP (Broadcast Data → Radio, typically
   `127.0.0.1:12060`).
3. Band is derived from `<TXFreq>` / `<Freq>` (N1MM units = 10 Hz).
4. **Until the first RadioInfo is heard, drop all Logged QSO / ADIF** (fail closed —
   wait, do not guess).
5. If the operator changes band in N1MM after Start seat, the helper **adapts** and
   the 2237 filter follows the new band.
6. Optional `--band` / expect-band is lab-only (warn on mismatch), not the primary filter.

## Operator requirement

N1MM: Config → Broadcast Data → enable **Radio** to at least `127.0.0.1:12060` on the
logger PC. Without that, the helper stays in “Waiting for N1MM band.”
