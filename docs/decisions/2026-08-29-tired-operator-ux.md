# Decision: Tired-operator UX (checkbox agents)

**Status:** adopted 2026-08-29; revised 2026-08-30 (drop fixed seat roles)  
**Problem:** Role menus and “this PC is an N1MM/WSJT seat” taxonomies fail under real
multi-app corners. Operators need a clean inventory of **agents**, not a role quiz.

## Primary goal

**Minimize questions.** Prefer detect → checkbox → start agent; one green/yellow/red
banner; English fix lines. Always say **agent** (not “helper”).

## Home model

Checkboxes (auto-check when the related app is detected):

| Asset | Agent | Notes |
|-------|-------|--------|
| **N1MM** | Log agent | 1:1 |
| **WSJT-X** (N instances) | Seat agent | One agent checks all local instances |
| **Key (CTS)** | Key agent | No companion app; CTS + inhibit targets |
| **Site server** | Site server | Optional; one per LAN |

- **Check** → start that agent (apps may start before or after WIMS).
- **Uncheck** → stop that agent.
- Agents own their config checks.
- Advanced / Other tools remains an escape hatch.

## Banner

- **Green:** all checked agents running; no hard config error on seat agent.
- **Yellow/red:** name which agent / what’s missing.

## Naming

Use **Log agent**, **Seat agent**, **Key agent**, **Site server** in UI and docs.
Do not use “helper” as a synonym for agent.
