# WIMS — WSJT-X Instance Management System

A supervised, **human-in-the-loop** operating console for multi-instance VHF contesting — the
"WSJT-X wrangler" position. WIMS gives one console operator cross-vehicle visibility and lets them
cover several digital bands at once, working alongside N1MM+, GridTracker, and a Green Heron
rotator.

**WIMS is a remote operating position, not an autobot.** Every active transmitter always has a
human: the local op in the seat, or the WIMS console operator who smoothly takes over a band when
its seat is empty. WIMS **ranks and recommends; the operator clicks every transmission.** There is
no automated/unattended TX.

> Authoritative **requirements & design**: [docs/plan/wims_design.md](docs/plan/wims_design.md) ·
> **build status & milestones**: [docs/plan/wims_status.md](docs/plan/wims_status.md)

## What it does

- **Call roster.** Every WSJT-X decode is shown in a ranked roster (à la GridTracker) with source
  info; the operator clicks a station to have the receiving instance start the contact. Sorted by
  **expected score gain** — only contest-relevant stations, ordered to grow the score fastest.
- **Contest scoring.** Pluggable, explainable factors (new-mult `grid × band`, points, SNR, CQ,
  rover) with a per-row breakdown; **N1MM is the dupe/multiplier authority** — WIMS keeps its own
  copy of the N1MM log and self-computes prospective new-mults, reconciling to N1MM.
- **Cross-vehicle console.** One combined roster, per-instance band-activity + health, one merged
  log/dupe-mult view — replacing "anyone there?" over chat.
- **Zero TX overlap by construction.** A per-resource-group interlock grants at most one
  transmitter per group; an independent overlap detector watches observed state as defense in depth.
- **SSB/CW priority.** When an SSB/CW op keys up, no WIMS-managed WSJT-X may transmit on that same
  band: a **preventive gate** (don't start) plus a **10 ms fast halt** (audio-path mute) for the
  mid-cycle race. See design §3.4.1.
- **Setup assist & diagnostics.** Verifies connectivity to every WSJT-X and N1MM instance (N1MM
  presence from any broadcast — no QSO needed), discovers the fleet, names every discrepancy, and
  is the protocol-aware network view so you never reach for Wireshark.

## Architecture at a glance

```
   WSJT-X #1 (6m FT8) ┐
   WSJT-X #2 (6m MSK) ┤          ┌──────────────────────────┐
   WSJT-X #3 (2m FT8) ┼─UDP──▶  │          WIMS            │ ◀── human override (SSB/CW op)
   WSJT-X #N ...       ┘         │  - UDP parse/control     │
        ▲                        │  - multi-instance mgr    │
        │  Reply / HaltTx /      │  - INTERLOCK (TX arbiter)│──▶ Dashboard
        │  FreeText / Replay     │  - decision engine       │
        └────────────────────────│  - safety / watchdog     │
                                 └───────┬─────────┬────────┘
                                         │         │
                           N1MM+ (log, ◀┘          └▶ Green Heron (rotator)
                           dupe/needed)
```

A **site server** is the single multicast consumer, state authority, and only sender of control to
WSJT-X; thin **operator consoles** connect over one unicast link (LAN or internet). Per-instance
**control leases** decide who may TX which instance; no valid lease → that instance is RX-only
(fail-safe). The time-critical 10 ms SSB/CW mute runs in a **local agent on the radio host**, never
through the server. Full design in [wims_design.md](docs/plan/wims_design.md) §4 / §4.5.

## Status

**Phase-1 (developer-oriented) read-only console is live** — fleet/instances, interlock/overlap
safety panel, ranked call roster, decode-activity heatmaps, decode log, N1MM sync, and loggers, on
a two-page browser UI (Operate / System status) fed by one SSE state contract. The decision engine
scores against a log copy seeded from the N1MM `.s3db` at startup and kept current from live
`<contactinfo>`. Stdlib-only, zero runtime dependencies; tests run without pytest.

See [wims_status.md](docs/plan/wims_status.md) for milestones (M1–M7), the per-module status table,
and the build log.

## Quick start

```bash
# Run the server (auto-seeds the N1MM contest log; ingests WSJT-X multicast + N1MM broadcasts)
python src/wims/server/app.py --iface 127.0.0.1
#   Operate:        http://localhost:8787/
#   System status:  http://localhost:8787/status

# No-RF test bed: simulate a fleet of WSJT-X instances
python testbed/simulators/emulator.py --iface 127.0.0.1 \
    --instances ROY-6M:50313000,CHIP-2M:144174000,TRL-432:432174000

# Tests (no pytest dependency)
for t in tests/unit/test_*.py; do python "$t"; done
```

Requires **Python 3.14**, stdlib only.

## Repository layout

```
WIMS/
├── docs/plan/            wims_design.md (requirements & design) · wims_status.md (status)
├── src/wims/
│   ├── core/             shared domain model (band labels, …)
│   ├── udp/              §3.1 WSJT-X parser/sink + §3.2 controller + encoder + activity map
│   ├── interlock/        §3.4 TX arbiter + overlap detector
│   ├── engine/           §3.5 scoring + roster builder
│   ├── integrations/n1mm/  §3.6 contactinfo listener, DXLOG seed, LoggedQso
│   ├── state/            §3.10 SQLite log copy + dupe/mult/resync
│   ├── discovery/        §3.15 fleet discovery, health, N1MM presence
│   └── server/           §3.12 stdlib HTTP + SSE state contract + static two-page UI
├── testbed/              §5 no-RF test bed (WSJT-X emulator, interlock bench)
├── tests/unit/           per-module unit tests
└── captures/             local packet captures (gitignored)
```

## License

Not yet licensed — all rights reserved pending a license decision.
