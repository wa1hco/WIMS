# WIMS — Project Guidelines

General collaboration style, the **development-vs-debugging contract**, coding
preferences, and safety rails live in the global `~/.claude/CLAUDE.md` (synced
across machines) and apply here unless overridden below. This file intentionally
does **not** duplicate them — if the global isn't present on this machine, sync it
rather than copying its contents here (avoids drift). Same pattern as the parallel
`map144` project.

WIMS (WSJT-X Instance Management System) — a supervised, **human-in-the-loop**
operating console for multi-instance VHF contesting (the "WSJT-X wrangler"
position). Target deployment: a fixed multi-multi VHF effort across several
vehicles on one LAN; WIMS provides cross-vehicle visibility and lets one console
operator cover several digital bands.

**The authoritative requirements/design is
[`docs/plan/wims_design.md`](docs/plan/wims_design.md)** — read it before proposing
work; record design decisions there as we go (it is the single source of truth), and
keep it updated when the *design* changes. **Build status, milestones, the
module-implementation table, and the build log live separately in
[`docs/plan/wims_status.md`](docs/plan/wims_status.md)** — update that as *code* lands.
Keep the two separated: design vs progress.

## WIMS-specific conventions

- **Python, stdlib-first.** Keep runtime dependencies minimal (currently zero);
  prefer a stdlib solution over pulling in a framework. Python 3.14.
- **Modular, pluggable, explainable, low lock-in.** Favor designs that are easy to
  swap and understand over clever ones — e.g. scoring is pluggable weighted factors
  with a visible breakdown; the UI is plain HTML/SSE behind a stable JSON API.
- **Verify live, not by assertion.** Prove each piece with the lightweight
  self-running tests in `tests/unit/` (no pytest dep) **and** a live run against
  real captures (`captures/`) or the emulator (`testbed/simulators/`). Keep the
  suite green.
- **Safety by construction:** zero TX overlap per resource group; fail-safe to RX;
  **no automated/unattended transmit** — a human always initiates TX.
- **Don't over-assume; fold in corrections** (e.g. the dev FlexRadio station is
  *not* the contest fleet) and adjust the plan.

## GUI

- **Light mode**, 12 pt (project default).
- **Stack = browser, served by the WIMS server** (stdlib HTTP + Server-Sent Events
  → static HTML). The **JSON state contract (`src/wims/server/state.py`) is the
  durable boundary**; the frontend is the only replaceable part.
- **Two-phase UI:** Phase 1 developer-oriented (information-dense, expose internals,
  discover what we actually need — rendering is disposable); Phase 2
  operator-oriented (cull, lay out, polish, lock conventions).
