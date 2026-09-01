# Decision: Tired-operator UX (checkbox agents)

**Status:** adopted 2026-08-29; revised 2026-08-30 (drop fixed seat roles);
revised 2026-08-30 (briefly: checkbox = live status); **revised 2026-09-01 —
seat intent vs running apps**

**Problem:** Role menus fail under multi-app corners. Mixing “is the app live?”
with “should the agent run?” in one checkbox row confused operators.

## Primary goal

**Minimize questions.** Detect what is running; remember what this seat **will**
run; start matching **agents**. Always say **agent** (not “helper”).

## Two surfaces (do not align checkboxes with app rows)

### 1. Running on this PC (read-only)

Observational: N1MM, WSJT-X (N live + names), Log / Seat / Key agents, Site server.

### 2. This seat will run (intent — remembered)

| Intent | Starts |
|--------|--------|
| **N1MM** | Log agent |
| **WSJT-X** | Seat agent (one agent; audits all **live** instances) |
| **SSB/CW KEY** | Key agent (no companion app; KEY/CTS) |
| **Site server** | Site console on this PC (adopt if already up; never dual-primary) |

- Intent is stored in `seat_intent.json` (per PC).
- Check intent → start agent (apps may start later).
- Uncheck → stop that agent.
- App exits while intent still on → agent may stay; banner yellow until app returns.
- App running with intent off → shown in Running only; no auto agent.

## WSJT-X (several instances)

One WSJT-X intent checkbox. Running list shows how many are live and their
`--rig-name`s. Seat agent remains **one** process.

## SSB/CW KEY (now vs later)

**Now:** SSB/CW KEY intent → Key agent; `WIMS_KEY_DEVICE` / `WIMS_KEY_TARGETS`.  
**Later:** multi USB-serial ↔ radio/band map UI.

## Banner

- **Green:** intent agents up; WSJT intent implies live instance for full Ready (else yellow).
- **Yellow:** intent on but app/agent missing; update available; site unreachable.
- **Red:** hard config error on a **live** WSJT instance (idle `.ini` never red).

## Startup replace

On open: replace orphan Log/Seat/Key; never auto-kill site server / WSJT-X / N1MM.

## Naming

**Log agent**, **Seat agent**, **Key agent**, **Site server** — never “helper”.
