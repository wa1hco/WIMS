# Decision: Tired-operator UX (N1MM seat first)

**Status:** adopted 2026-08-29  
**Problem:** Role menus, port numbers, and multi-step bring-up fail for distracted /
untrained contest ops. Linux “works” is not enough if Windows seats need a manual.

## Rules

1. **One Desktop icon** → the right screen for this PC type (default: **N1MM seat**).
2. **One primary button:** Start seat / Stop seat.
3. **One status light:** green / yellow / red + **one plain sentence** (no port soup).
4. **Open site console** uses the configured/discovered site URL — never ask the op for
   `8787` vs `8790`.
5. Ports and role catalogs live under **Other PC types…** / Advanced.
6. Failures must be **visible without reading a log** (banner + one fix line).

## N1MM seat (first)

Start seat = **log agent** (and later **key agent** when productized). Optional checkbox:
“Also run site server on this PC.”

Start seat opens the log helper’s **small status window** (config check + interconnect),
not only a black console. Band filter follows **N1MM RadioInfo** (not a required picker).

Green when: site console reachable **and** log agent running.  
Red when: either missing — say which, in English.

## Follow-ons

WSJT seat and site-server-only one-button pages. Compact per-agent GUIs stay secondary
to this launcher home.
