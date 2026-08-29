# Decision: Tired-operator UX (N1MM seat first)

**Status:** adopted 2026-08-29  
**Problem:** Role menus, port numbers, and multi-step bring-up fail for distracted /
untrained contest ops. Linux “works” is not enough if Windows seats need a manual.

## Primary goal

**Minimize questions asked of the operator and setup decisions they must make.**

Prefer: discover, remember, fail with one English fix line.  
Avoid: pickers, ports, URLs, and “which band is this PC?” on the home screen.

## Rules

1. **One Desktop icon** → the right screen for this PC type (default: **N1MM seat**).
2. **One primary button:** Start seat / Stop seat.
3. **One status light:** green / yellow / red + **one plain sentence** (no port soup).
4. **Open site console** uses env / last-known / presence discovery — never ask the op for
   `8787` vs `8790` on the home screen.
5. Ports, role catalogs, and rare overrides live under **Other PC types…** / Advanced.
6. Failures must be **visible without reading a log** (banner + one fix line).
7. **Band** for the log helper comes from **N1MM RadioInfo**, not a launcher question
   ([n1mm-live-band](2026-08-29-n1mm-live-band.md)).

## N1MM seat (first)

Start seat = **log agent** (and later **key agent** when productized). Optional checkbox:
“Also run site server on this PC” (only decision for the designated server box).

Start seat opens the log helper’s **small status window**. If N1MM Radio broadcast is
off, the helper says so in one line — do not make the operator pre-declare a band.

Green when: site console reachable **and** log agent running.  
Red when: either missing — say which, in English.

## Follow-ons

WSJT seat and site-server-only one-button pages. Keep burning down remaining decisions
(N1MM Broadcast Data still requires a one-time N1MM setting until we can auto-verify).
