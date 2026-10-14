# Home testing: H2 dual RX + TX-capable mark

**Audience:** one PC, one transceiver, two decode streams.  
**Goal:** see both WSJT-X instances in Operate; Work and Inhibit only the TX path.  
**Radio control:** still manual / N1MM / WSJT (option E). Mute is H3. CAT is H4.

Related: [`home_h0_h1.md`](home_h0_h1.md),
[`plan/wims_home_dual_rx_slice.md`](plan/wims_home_dual_rx_slice.md),
[`plan/shared_trx_second_rx.md`](plan/shared_trx_second_rx.md).

## What H2 adds

| Piece | Role |
|-------|------|
| **Two WSJT-X ids** | MAIN TX + SUB/SDR decode (or TRX + separate SDR) |
| **`seat-profile.json` marks** | `tx_capable` true/false per `--rig-name` |
| **Operate** | Decode-only rows stay visible; **Work is denied** on them |
| **Setup toggles** | Mark TX vs decode-only; optional `station_class` |
| **Config check** | Warn/error when shared-trx class has 0 or ≥2 TX marks |

H0/H1 still work with one instance and no profile file.

## Station classes (pick one)

| Class | Second RX | Typical audio |
|-------|-----------|---------------|
| **`shared_trx_dual_rx`** | Same radio SUB / dual-watch (e.g. IC-9700) | Radio 2nd-RX USB / codec |
| **`shared_trx_second_rx`** | Separate SDR | Virtual cable / IQ from SDR |

Unset class is fine for a single digi. Use a shared-trx class when you want the
“exactly one TX-capable” check.

## Wiring checklist

### A. Same radio dual RX (`shared_trx_dual_rx`)

1. One transceiver with dual RX enabled (MAIN + SUB).  
2. Two WSJT-X processes with **unique** `--rig-name` (example: `HOME-FT8`, `HOME-SUB`).  
3. Both report UDP `224.0.0.73:2237` with **Accept UDP requests ON** on the TX instance.  
4. TX instance audio + CAT/PTT on the MAIN / TX path.  
5. Decode-only instance audio from SUB (no PTT / no Work needed).  
6. Mark TX vs decode-only on **Setup → Home dual RX (H2)**.  
7. H1 Inhibit `--targets` → TX instance gate only (often `127.0.0.1:22372`).

Do not hot-switch RX2 while transmitting. Radio T/R protects the second RX.

### B. TRX + separate SDR (`shared_trx_second_rx`)

1. One transceiver for TX.  
2. Coupler / splitter → SDR with T/R or limiter protection.  
3. TX WSJT-X on the transceiver path (`rf_path=trx`, `tx_capable=true`).  
4. One or more decode-only WSJT-X on SDR audio (`rf_path=sdr_rx`, `tx_capable=false`).  
5. Same UDP plane A and unique `--rig-name` values.  
6. Mark instances on Setup. Inhibit targets the TX gate only.

## seat-profile.json

Default path:

| OS | Path |
|----|------|
| Windows | `%LOCALAPPDATA%\WIMS\seat-profile.json` |
| Linux | `~/.local/share/wims/seat-profile.json` |

Example (also in `examples/seat-profile-home-dual-rx.json`):

```json
{
  "station_class": "shared_trx_dual_rx",
  "wsjt_instances": [
    {"id": "HOME-FT8", "rf_path": "trx", "tx_capable": true},
    {"id": "HOME-SUB", "rf_path": "sdr_rx", "tx_capable": false}
  ]
}
```

Rules:

- Unset `tx_capable` means **true** (fleet-safe).  
- Explicit `false` → Operate **Work denied**; treat as decode-only.  
- Shared-trx class → config check wants **exactly one** TX-capable mark.  
- Optional path override: `python -m wims.solo --seat-profile /path/to.json`
  (same flag on `wims.server.app`).

Edit via **Setup** toggles, or copy the example file into the default path.

## Operate and Inhibit behavior

| Action | TX-capable instance | Decode-only instance |
|--------|---------------------|----------------------|
| Show in roster / Status | Yes | Yes (badge **decode**) |
| Click Work | Allowed | Denied (`decode_only`) |
| H1 KEY hold | Target this gate | Do not target |

Home Inhibit still uses explicit targets (`127.0.0.1:22372` by default).  
Point that at the **TX-capable** patched gate.

## Quick start

1. Run two WSJT-X instances (unique `--rig-name`).  
2. Start Operate: `Start-Wims-Solo` / `python -m wims.solo`.  
3. Open **Setup**. Mark one TX-capable, one decode-only. Save.  
4. Confirm Status shows **TX** / **decode** badges.  
5. Work a line on the TX source only.  
6. Optional: Start Inhibit (home) aimed at the TX gate.

## Not in H2

| Later stage | What |
|-------------|------|
| **H3** | KEY → TX-audio mute |
| **H4** | CAT handoff / ownership after ADR spike |

## If something fails

| Symptom | Check |
|---------|--------|
| Both look TX-capable | No profile, or Save not clicked |
| Work denied on MAIN | MAIN marked decode-only — flip mark on Setup |
| Check says many TX | Shared-trx class with ≥2 `tx_capable: true` |
| Empty second stream | SUB/SDR audio; unique `--rig-name`; same UDP plane |
| KEY holds wrong instance | `--targets` / `WIMS_KEY_TARGETS` must be TX gate |
