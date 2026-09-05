# Decision: Log helper band follows live N1MM RadioInfo

**Status:** adopted 2026-08-29  
**Context:** One N1MM per PC; its band setting is correct except briefly during setup.

## Rules

1. The **log helper** does **not** permanently trust the launcher band picker / hostname pin
   as the QSO filter.
2. It listens for N1MM **RadioInfo** UDP: joins fleet multicast `224.0.0.73:12060`
   (bound `0.0.0.0:12060`, so loopback / LAN unicast destinations are also heard;
   `--radio-group ''` for unicast-only).
3. Band is derived from `<TXFreq>` / `<Freq>` (N1MM units = 10 Hz).
4. **Until the first RadioInfo is heard, drop all Logged QSO / ADIF** (fail closed —
   wait, do not guess).
5. If the operator changes band in N1MM after Start seat, the helper **adapts** and
   the 2237 filter follows the new band.
6. Optional `--band` / expect-band is lab-only (warn on mismatch), not the primary filter.

## Operator requirement

**Fleet Broadcast Data (all N1MM PCs, identical):**

```text
127.0.0.1:12060
```

Enable **Radio** + **Contacts**. The **N1MM agent** hears localhost and POSTs XML to
the site server (`POST /api/n1mm/broadcast`). Status no longer requires LAN/Tailscale
multicast for plane B.

Optional lab: multicast `224.0.0.73:12060` or unicast to the site LAN IP still works if
the site server is listening. **Never** use Tailscale `100.x` in Broadcast Data.

**Do not confuse** Broadcast hear (`:12060`) with QSO **delivery** to local N1MM
(`127.0.0.1:52001` / `:2333`) — localhost delivery is correct for Log.
Without RadioInfo on `:12060`, the agent stays in “Waiting for N1MM Broadcast.”
