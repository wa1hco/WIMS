# Decision: Tired-operator UX (checkbox agents)

**Status:** adopted 2026-08-29; revised 2026-08-30 (drop fixed seat roles);
revised again 2026-08-30 (checkbox = live seat status, **not** a saved preference)

**Problem:** Role menus and “this PC is an N1MM/WSJT seat” taxonomies fail under real
multi-app corners. Operators need a clean inventory of **agents**, not a role quiz.

## Primary goal

**Minimize questions.** Prefer detect → checkbox → start agent; one green/yellow/red
banner; English fix lines. Always say **agent** (not “helper”).

## Checkbox meaning (status, not preference)

A checkbox is **live status of a seat component**, not a setting remembered across
launches. There is **no** `agent_boxes.json` restore.

| If… | Then… |
|-----|--------|
| Companion **app is running** (N1MM / WSJT-X) | Box **checked**; matching **agent must be running** (start if needed) |
| Companion **app stops** | Box **unchecked**; matching **agent stopped** |
| Operator **checks** a box | Start the agent if it is not already up |
| Operator **unchecks** while app still live | Stop the agent; hold off auto-check until the app exits (then a later app start can auto-check again) |
| Operator **checks** with no companion app (Key, or Seat before WSJT) | Start agent; hold on until uncheck or (for Seat) WSJT becomes live |

Fresh launcher open: all boxes start **unchecked**, then detection fills them from
what is actually running / reachable.

## Home model

| Asset | Agent | Auto-check when |
|-------|-------|-----------------|
| **N1MM** | Log agent | N1MM process running |
| **WSJT-X** (N) | Seat agent | WSJT-X process running (`.ini` alone ≠ live) |
| **Key (CTS)** | Key agent | Never (no companion app) — manual check |
| **Site server** | Site server | Site console reachable (status). Do **not** start a second primary; show “up (existing)” |

- Agents own their config checks.
- Advanced / Other tools remains an escape hatch.

## Cases (checklist)

1. **Apps before WIMS** — detect → check → start agents.
2. **Apps after WIMS** — pulse detect → check → start agents.
3. **App exits** — uncheck + stop that agent.
4. **Operator unchecks while app live** — stop agent; don’t immediately re-check.
5. **Operator re-checks** — start agent again.
6. **Key** — manual each session; uncheck stops.
7. **Site already on LAN / this PC** — box checked as status; never spawn dual-primary.
8. **Site uncheck** — stop only a server **this** launcher owns; external left alone.
9. **Launcher restart** — replace orphan Log/Seat/Key; site server left alone; boxes
   re-derived from live state (not prefs).
10. **`.ini` on disk, WSJT not running** — label “off, N ini”; box **unchecked**; no
    Seat agent until WSJT starts or operator checks manually.

Open / unsure (fold in when we hit them): multi-launcher on one PC; adopting an
already-running Log/Seat without kill/restart; Key hardware auto-detect.

## Startup replace (orphans)

On every launcher open, **replace local seat agents** (Log / Seat / Key) so this
UI owns them — cmdline match only. **Never auto-kill the site server**, WSJT-X,
or N1MM. Server outage does not stop N1MM logging.

## Banner

- **Green:** checked agents are up **and** (for Seat) WSJT-X process is live.
- **Yellow:** Seat agent up but WSJT-X not running; or site unreachable; waiting…
- **Red:** hard seat config error.
- Status column names the **agent** (“Seat agent up”), never bare “running” on the
  WSJT-X row.

## Naming

Use **Log agent**, **Seat agent**, **Key agent**, **Site server** in UI and docs.
Do not use “helper” as a synonym for agent.
