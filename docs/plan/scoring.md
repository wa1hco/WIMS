# Needed-list score

How Operate orders stations. Two parts:

- **Current algorithm** — what the code does today. This is the score in the Score column.
- **Proposed algorithm** — **planned, not implemented.** A replacement for review, comment, and improvement. Nothing in that section is in the product.

The score never transmits. Work stays a separate click on a live decode
([wims_design.md](wims_design.md) §2.3 / §2.12). A hint never starts a call
(§2.15).

---

## Current algorithm

Implemented. The live roster asks `WeightedFactorStrategy` (`name` `vhf-default`)
to score every retained decode. The total is a sum of named terms. Stations that
fail a gate are stored with total **0** and an empty term list. They stay on the
roster; the show menu decides which of those rows are drawn.

### Where it lives

| Step | Code |
|------|------|
| Weights, terms, gates, total | `src/wims/engine/scoring.py` — `WEIGHTS`, `weights_for`, `band_points`, `f_new_mult`, `f_points`, `f_snr`, `f_cq`, `f_rover`, `WeightedFactorStrategy.score`, `build_candidate` |
| Which rows are scored, and the server's order | `src/wims/engine/roster.py` — `RosterBuilder.ranked` |
| Goal → dupe, new-mult, QSO points | `LogStore.classify` in `src/wims/state/logstore.py`, then the active rules: `ContestRules.classify` (`src/wims/engine/contest_rules.py`), `AwardRules.classify` / `_from_mark`, or `ChecklistRules.classify` (`src/wims/engine/goal_rules.py`) |
| CQ bit | `src/wims/udp/messages.py` — `_interpret_decode`. `is_cq` is true only when the first token is `CQ`. `QRZ` and `DE` are not CQ |
| Weight set for this process | `src/wims/server/app.py` builds `Context(weights=weights_for(self._condition))`. `--condition` is `open` (the default), `marginal`, or `dead`. There is no Setup control |
| JSON the browser receives | `roster_to_dict` in `src/wims/server/state.py`. `score` is `round(total, 1)`. `factors` is the term list. `strategy` is `vhf-default` |
| Order on screen | `src/wims/server/static/wims.js`. Default sort is Score, high to low (`_rosSort`). Any column header re-sorts. The choice is not saved. The term list is **not drawn**. The row hover is the work tip plus `need_reason` and `mult_reason` |

`ScoringStrategy.rank` drops gated stations and sorts by total. The live server
does not call it. It calls `score` on every row, then `RosterBuilder.ranked`.

### Gates (total 0, no terms)

Checked in this order inside `WeightedFactorStrategy.score`:

1. `is_dupe` — reason `dupe`.
2. `is_cq` is false — reason `not calling CQ`. A 73 / RR73 tailend stops here.
3. `reachable` is false — reason `not reachable by antenna`.

The live roster calls `build_candidate` without `reachable`, and the default is
true. The third gate is real in the strategy and unused on the air path.

A gated row still has its `is_new_mult`, `chase`, and `need_reason`. Those drive
badges and the hover. They do not enter the total. A worked call whose grid is
new is still a dupe first, so the new-mult term is not added.

### Terms

A station that passes the gates gets:

| Term | When it is added | Contribution |
|------|------------------|--------------|
| `new_mult` | `is_new_mult` | the condition's `new_mult` weight. Detail is `mult_reason`, or `new {band} grid {grid}` |
| `points` | always | `qso_points × points weight`. If `qso_points` is missing (`None`), the band table below is used instead. The detail text is `{band}={points}pt` |
| `snr` | always | `round(work × snr weight, 1)` with `work = max(0, min(10, (snr + 24) / 3))`. Detail is `{snr:+d}dB`. `round` is Python's round (halves to even) |
| `cq` | `is_cq` | the condition's `cq` weight. Detail `calling CQ` |
| `rover` | `is_rover` and `is_new_mult` | the condition's `rover` weight. Detail `rover in new grid` |

Total = sum of those contributions.

On this strategy every station that passes the gates is a CQ, so `cq` is the
same addend on every scored row. It does not change the order among those rows.
It is why a scored CQ sits above a gated row, whose total is 0.

`is_rover` is `"/R" in call` after the call is uppercased (`build_candidate`).
A call heard in two squares, without `/R` in the text, does not set the flag.

### Weights

`WEIGHTS` in `scoring.py`. Unknown condition names fall back to `open`.
The running server only passes `open`, `marginal`, or `dead`, and starts on `open`.

| Term | open | marginal | dead |
|------|------|----------|------|
| `new_mult` | 25 | 45 | 60 |
| `points` | 2 | 3 | 4 |
| `cq` | 5 | 4 | 3 |
| `snr` | 1.0 | 0.4 | 0.2 |
| `rover` | 10 | 18 | 25 |

Band points (`BAND_POINTS`), used when the rules file says `points: "vhf-band"`
and when `qso_points` is `None`:

| Band | Points |
|------|--------|
| 6m, 2m | 1 |
| 1.25m, 70cm | 2 |
| 33cm, 23cm, 13cm | 3 |
| any other name, including `?` | 4 |

Award and checklist verdicts set `points` to **1**, so the `points` term is
`1 ×` the weight, on every band. A contest file with a mode-group point map
(NY QSO Party) passes that number through as `qso_points`. A mode the contest
excludes is a dupe with `points` 0, so the term never gets into the sum.

### What the goal puts on the candidate

Scoring does not re-read the log. It trusts the verdict.

- **Contest** (`ContestRules.classify`). `is_dupe` when the call matches the
  file's dupe scope. ARRL VHF: once per band for a fixed station. A call
  containing `/R` is a dupe only when the logged 4-character grid equals this
  grid; with no grid on the decode, any same-band contact with that call
  matches. `is_new_mult` when the rules mark a new multiplier.
  ARRL VHF (`src/wims/rules/arrl_vhf.json`): a 4-character grid not yet in the
  log on that band. A 6-character grid counts as its first four. `chase` stays
  empty. `per: unverified` (NY QSO Party counties) forces `is_new_mult` false.
- **Award** (`AwardRules._from_mark`). A new DXCC entity, 4-character grid
  (VUCC), or US state sets `is_dupe` false, `is_new_mult` true, `chase`
  `needed`. A worked place that is not confirmed sets `is_new_mult` false and
  `chase` `unconfirmed`. With **Count worked but not confirmed as needed** on
  (the default), `is_dupe` is false, so the row is needed and scores as an
  ordinary CQ: no `new_mult` term. With that switch off, `is_dupe` is true and
  the total is 0. A station with no confirmed contact anywhere is not chased
  for confirmation (`is_dupe` true, `chase` empty). A place with no entity,
  grid, or state is a dupe with a plain reason.
- **Checklist** (`ChecklistRules.classify`). The first checked line that is new
  wins. `is_new_mult` is true only when that line is `dxcc`, `continent`,
  `cq`, `itu`, `grid`, or `state` (`_MULT_KINDS`). A new **call** is needed
  (`chase` `needed`, `is_dupe` false) and `is_new_mult` is false, so it does
  not get the `new_mult` term. Unconfirmed handling matches the award switch.
  Nothing checked, or an unknown entity, is a dupe.

If no rules object is attached, `classify` returns not a dupe, not a new mult,
and `points` 0. The `points` term is then 0. The server attaches the Goal
before it serves the console.

`is_needed` on the wire is `not is_dupe`. The show menu
(`src/wims/engine/roster_filter.py`, `rosKeepCandidate` in `wims.js`) hides
rows. It does not change the number. Needed, Needed and CQ, and Needed and CQ
or 73 can show a 73 whose score is 0.

### Order

Server (`RosterBuilder.ranked`), before the browser:

1. Not a dupe, then a dupe.
2. Higher total first.
3. A tie keeps the order the `(instance, call, grid)` row was first inserted.
   A later decode of the same row updates it in place and does not move it.
   Python's sort is stable.

Browser, default: Score descending, using the **rounded** tenth. Equal scores
keep the server order (JavaScript's sort is stable). Clicking another header
replaces that order until reload.

Rows older than `ttl` (300 seconds) leave the server roster
(`RosterBuilder._prune`). The Operate age box defaults to 120 seconds and only
hides rows. Neither one changes the total.

Calling-us (red) and armed (green) are row colors in `roster_to_dict`. They
are not terms.

### Worked totals (condition `open`)

These rows were scored with `get_strategy().score` and `weights_for("open")`.
SNR in the table is the decode's dB.

| Station | Inputs | Terms | Total |
|---------|--------|-------|-------|
| K1ABC, CQ, 6m, new grid, −6 dB | passes the gates, `is_new_mult`, not a rover | `new_mult +25`, `points +2` (1×2), `snr +6`, `cq +5` | **38.0** |
| W2XYZ, CQ, 2m, grid already worked, +3 dB | passes the gates, not a new mult | `points +2`, `snr +9`, `cq +5` | **16.0** |
| N0ROV/R, CQ, 6m, new grid, −18 dB | rover and new mult | `new_mult +25`, `points +2`, `snr +2`, `cq +5`, `rover +10` | **44.0** |
| Same rover, 73, not CQ | gate 2 | no terms | **0.0** |
| K1ABC already worked, even if the grid is new | gate 1 | no terms | **0.0** |
| Award or checklist, CQ, 6m, unconfirmed place, 0 dB, switch on | `chase` unconfirmed, `is_new_mult` false, `qso_points` 1 | `points +2`, `snr +8`, `cq +5` | **15.0** |
| Checklist, CQ, new call only, 6m, 0 dB | needed, `is_new_mult` false, `qso_points` 1 | same as the unconfirmed row | **15.0** |
| CQ, 70cm, new grid, −24 dB | `work` is 0 at −24 dB; 70cm is 2 points | `new_mult +25`, `points +4`, `snr +0`, `cq +5` | **34.0** |

The same K1ABC new-grid CQ at −6 dB under the other weight sets:
`marginal` **54.4** (`new_mult +45`, `points +3`, `snr +2.4`, `cq +4`),
`dead` **68.2** (`new_mult +60`, `points +4`, `snr +1.2`, `cq +3`).

N0ROV/R at 44.0 outranks K1ABC at 38.0. Both outrank W2XYZ at 16.0. The 73
and the dupe show as 0.0. Among the zeros, the server lists the non-dupe
first, and the default Score sort keeps that.

---

## Proposed algorithm

**Planned. Not implemented.** The numbers below are a starting proposal for
reviewers. They are not in `WEIGHTS`, and Setup has no score editor.

Replace the total with a sum of named terms. Each term is `weight × amount`.
A weight of 0 turns that term off. Amount is 0 or 1, except the time terms,
whose amount slides from 0 to 1.

```
total = need_new + need_qso + need_unconfirmed
      + rover_clock + recency + opening
      + regular
      + hint_psk + hint_cluster + hint_chat
      + hint_ours + hint_others + hint_recency
```

The goal's verdict is unchanged. This sum only reads it. No term starts a
call, sends Reply, Free Text, or CQ, or keys a radio.

### Live rows and hint rows

Hints are a second call roster (§2.15). They are not decode rows. The two
rosters are never merged. A station on both stays on both. A hint total
orders the second roster only. It is not compared with a live total.

- A **live** row uses need, rover clock, recency, opening, and regular.
  Hint terms are 0 once we have a decode of that station on that band.
- A **hint** row uses only the hint terms, plus a small hint recency.
  It does not get `need_new`, the rover clock, or `regular`.
- **Order.** On the live roster, needed rows sort by total, high to low, as
  today. On the hint roster, higher hint total first. Live rows that are not
  needed stay off the Needed menu, as they do today.

### Terms

Starter weights are for the first review. Later they live in the GUI.

| Term | Weight | Amount |
|------|--------|--------|
| `need_new` | 40 | 1 when `is_new_mult` (new grid, state, DXCC entity, continent, CQ zone, or ITU zone, whichever the goal already marks). 0 otherwise |
| `need_qso` | 8 | 1 when the row is needed, not a new mult, and `chase` is not `unconfirmed`. Covers a contest contact whose grid is already worked, and a checklist "new call" |
| `need_unconfirmed` | 12 | 1 when `chase` is `unconfirmed` and the goal's worked-but-not-confirmed switch is on, so the row is still needed. 0 when the switch is off, and 0 for a station who has never confirmed any contact (those rows stay not needed, as today) |
| `rover_clock` | 15 | Rovers only. See below. 0 for everyone else |
| `recency` | 10 | `max(0, 1 − minutes_since_last_heard / 2)`. Just heard is 1. Silent for 2 minutes is 0. The row still ages out of the roster at 300 seconds, as today |
| `opening` | 12 | 0 unless this band is marked meteor scatter or Es. `max(0, 1 − minutes_since_marked / life)`. Life is 15 minutes for meteor scatter and 30 minutes for Es |
| `regular` | 8 | Only on a live row that is still needed. `min(1, prior_qsos / 10) × (0.5 + 0.5 × confirmed_fraction)`. No prior QSOs → 0. Ten or more QSOs, all confirmed → 1 |
| `hint_psk` | 3 | 1 on a hint row that came from PSK Reporter. 0 on a live row |
| `hint_cluster` | 2 | 1 on a hint row from a DX cluster spot (§2.15). 0 on a live row |
| `hint_chat` | 2 | 1 on a hint row from ON4KST or Ping Jockey. 0 on a live row |
| `hint_ours` | 2 | 1 on a hint row from our own past runs of this contest (§2.15 B1). 0 on a live row |
| `hint_others` | 2 | 1 on a hint row from other stations' public ARRL logs, in range (§2.15 B2). 0 on a live row |
| `hint_recency` | 2 | Same shape as `recency`, using the hint's age and the same 2-minute window. Hint rows only |

**Rover clock.** A rover is today's `/R` test, or a call the heard-grid memory
already treats as a rover (the call ends in `/R`, or it has been heard in two
squares). The clock is per grid.

- No departure time on file: `amount = min(1, minutes_since_first_heard_in_this_grid / 20)`.
  Just arrived is 0. Still in that grid after 20 minutes is 1.
- A departure time is known (the operator typed it, or a later read of a sked
  carried one): `amount = min(1, max(0, 1 − minutes_until_departure / 20))`.
  A departure 20 minutes out is 0. Departure now is 1.

`first_seen` is not stored today. `_Entry` keeps `last_seen` only. Building
this term means remembering when this `(instance, call, grid)` was first heard,
and clearing that when the grid changes.

**Regular contacts.** Count prior QSOs with this base call in the logs WIMS
already reads, across contests, not only this weekend's dupe key. A contact
counts as confirmed the same way the award and checklist already confirm a
place (card, LoTW, or eQSL on the log row, or the GridTracker LoTW file).
The count does not change dupe or mult. A station worked this time has
`need_*` at 0, and `regular` is 0 on that row in this proposal, so a friend
who is already in the log does not climb the Needed list.

**Opening.** Meteor scatter and Es are short. The starter design is a mark the
operator sets on that band in Setup (or a later detector, if reviewers want
one). The mark is not a transmit. When it ages out, the term goes to 0.

**Hints.** Category A (PSK Reporter, DX cluster, ON4KST, Ping Jockey) and
category B (our history, others' history) are §2.15. They are a second roster,
never merged with the live roster, so these weights only order that roster.
A hint row that carries every source and was just refreshed scores
3+2+2+2+2+2 = 13. A past-contest history row is older than the 2-minute
hint window, so `hint_recency` is 0 on that row unless a category A source
refreshed it. Age is still shown on the row.

### Tie-break

Higher `recency` amount (or `hint_recency` on a hint row), then longer time
already spent in this grid, then callsign A to Z. This replaces today's
insertion-order tie.

### Worked example

Same starter weights. "Heard" is how long ago the last decode or hint refresh
was. Rover stay is 20 minutes. No opening unless the row says so.

| Station | What we know | Terms | Total |
|---------|--------------|-------|-------|
| K1ABC | Live CQ. New 6m grid. Heard 12 seconds ago. Not a rover. No prior QSOs | `need_new` 40×1 = 40. `recency` 10×0.9 = 9 | **49** |
| N0ROV/R | Live CQ. New grid. First heard in this grid 10 minutes ago. Heard 12 seconds ago. Two prior QSOs, both confirmed | `need_new` 40. `rover_clock` 15×0.5 = 7.5. `recency` 9. `regular` 8×0.2×1 = 1.6 | **58.1** |
| K2ES | Live CQ. New grid. Heard 12 seconds ago. Es marked 15 minutes ago (life 30) | `need_new` 40. `recency` 9. `opening` 12×0.5 = 6 | **55** |
| N0MSK | Live CQ. New grid. Heard 12 seconds ago. Meteor scatter marked 5 minutes ago (life 15) | `need_new` 40. `recency` 9. `opening` 12×(2/3) = 8 | **57** |
| N0ROV/R 73 | Live tailend, not CQ. Same rover facts as the CQ rover row, last heard 30 seconds ago | `need_new` 40. `rover_clock` 7.5. `recency` 10×0.75 = 7.5. `regular` 1.6 | **56.6** |
| W1AW | Live CQ. Worked grid, not confirmed, switch on. Heard 12 seconds ago | `need_unconfirmed` 12. `recency` 9 | **21** |
| W2XYZ | Live CQ. Needed, not a new mult (grid already worked, or checklist new call). Heard 12 seconds ago | `need_qso` 8. `recency` 9 | **17** |
| K1ABC dupe | Live CQ. Already worked this time. Ten prior QSOs, all confirmed. Heard 12 seconds ago | `recency` 9. Need and `regular` stay 0 | **9** (hidden on Needed) |
| W3BIG | Hint roster only. PSK Reporter and our history. Refreshed 12 seconds ago. No decode | `hint_psk` 3. `hint_ours` 2. `hint_recency` 2×0.9 = 1.8 | **6.8** |
| W4OLD | Hint roster only. Others' history, in range. No decode. The past contest is years old | `hint_others` 2. `hint_recency` 0 | **2** |

On the Needed list the live order is N0ROV/R (58.1), N0MSK (57), the rover's
73 (56.6), K2ES (55), K1ABC (49), W1AW (21), W2XYZ (17). W3BIG (6.8) and
W4OLD (2) stay on the second roster. They are not mixed into that order.
Today the 73 would be 0.0 and the rover would beat K1ABC only by the flat
`rover` +10, with no clock.

### What the operator sees

**Planned, with the editor.** Not built.

- Setup gets a closed **Score** section. Each term shows its plain name, one
  sentence, and its weight. A weight the operator changes applies on the next
  roster push. The choice is saved with the other site-server settings, the
  same way the Goal is. No command-line flag and no environment variable.
  A browser on another PC sees the same totals, because the server does the
  arithmetic.
- The Score cell hover is the reason, one short line of the terms that are
  not zero. Example: `need 40 (new grid FN31 on 6m) · rover clock 7.5 (10 min in this grid) · recency 9 (heard 12s ago)`. Zero terms stay off the line.
  The full list is available from that hover. Today's `factors` array is the
  place this text would come from; the page does not render it yet.
- The status line for a save is one short sentence, in the same voice as the
  other Operate lines.

The current `--condition` switch stays a developer flag until this section is
built. The proposal's weights replace the open / marginal / dead tables.
Reviewers can ask for those three as GUI presets (see the questions).

---

## Open questions for reviewers

Comments on this file are the point of the proposal. The starter weights are
not a decision.

1. Are the starter weights right? In particular `need_new` 40 against
   `rover_clock` 15, `regular` 8, `need_unconfirmed` 12, and `need_qso` 8.
   Should a rover who has sat in a grid for 20 minutes outrank a brand-new
   multiplier who was just decoded, as the example does (58.1 vs 49)?
2. Should a 73 or RR73 tailend take the same need term as a CQ? This proposal
   says yes. The code today gives the tailend 0.
3. Keep any of today's terms that this proposal drops — SNR, QSO points, and
   the flat CQ addend? If SNR stays, should weak signals still be pushed down
   when the band is marginal or dead?
4. Calling-us is a red row and not a term. Should it add a named term, and
   how large?
5. Rover clock. Is `/R` in the call enough, or should two squares without
   `/R` start the clock? Is 20 minutes the right expected stay? A quiet rover
   (clock high, recency already 0) stays near the top in the formula above.
   Should silence also drain the clock?
6. Where would a real departure time come from? Operator entry only, or a
   sked time parsed from chat (§2.15)? Chat parsing is still an open question
   of its own. Cluster-spot parsing is the same kind of open question.
7. Who marks meteor scatter or Es? An operator switch, the mode (MSK144 vs
   FT8), or something else? Are 15 and 30 minutes the right lives?
8. Regular contacts. Which logs count — everything WIMS can read, or only the
   same contest in past years? Is 10 QSOs the right full-scale count? Should
   the term look at the base call or the full call, so a rover is not mixed
   with the home station? Should a station who is already worked this time
   keep a small `regular` term on the All menu? This term is on a live row.
   The hint roster's history sources are separate (§2.15 B1 and B2).
9. Is `need_unconfirmed` 12, between a new mult and an ordinary new contact,
   the right place for a worked-but-not-confirmed place? Confirm that a
   station who never confirms stays off the list.
10. Hint weights: PSK 3, cluster 2, chat 2, our history 2, others' history 2,
    and hint recency 2. The two rosters are never merged, so a hint total
    orders the second roster only. Are these starter weights right for that
    order? PSK Reporter is polled about every 5 minutes, and a history row is
    years old. Should either use a longer age window than 2 minutes?
11. One set of weights, or keep open / marginal / dead as named presets in
    the Score section that the operator can load and then edit?
12. Tie-break: recency, then time in grid, then callsign. Anything missing
    (SNR, band)?
13. Confirm again that no term, and no click on the why-this-score line, may
    transmit. Work remains a click on a live decode.
