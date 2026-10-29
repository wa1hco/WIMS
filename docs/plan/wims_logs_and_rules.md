# WIMS logs, contest rules, and log audit

**Status:** design proposal (no runtime change in the PR that added this file)
**Date:** 2026-10-15
**Related:** [wims_design.md](wims_design.md) §3.5 / §3.6 / §3.10 / §3.11;
[wims_log_source_survey.md](wims_log_source_survey.md) (storage tiers and logger ranking);
[wims_status.md](wims_status.md) milestones **L1–L9**.

Solo (`python -m wims solo`) runs on the same PC as the WSJT-X instances. N1MM may be
absent. WSJT-X may log only to its own ADIF, to one shared ADIF, or through GridTracker.
Needed-vs-dupe and QSO points must follow the contest the operator is actually in.
When no contest rule is selected, solo “needed” follows WSJT-X’s own Colors
categories against `wsjtx_log.adi` (or GridTracker’s roster filters, if the
operator picks that source). When N1MM is the log of record, N1MM stays authoritative.

WIMS still **reads** logs and **never writes** them. A human still initiates every TX.

---

## 1. Current state and gaps

### What works today

| Piece | Where | Behavior |
|-------|--------|----------|
| Log copy | `state/logstore.py` (`:memory:` SQLite in the server) | Seed + live upsert/delete + `reconcile()`. |
| QSO record | `integrations/n1mm/qso.py` `LoggedQso` | N1MM field set: call, band, grid, mode, points, `is_mult`, contest, time, operator, rover location, source, stable `ID`. |
| N1MM backend | `integrations/logsource/n1mm_source.py` | `discover` / `seed` / `resync` / `status`, plus `parse_live()` for `<contactinfo>`, `<contactreplace>`, `<contactdelete>`. |
| Protocol | `integrations/logsource/base.py` | `LogSource`, `LogSourceCandidate`, `LogEvent`. Only `N1mmLogSource` is registered. |
| Dupe / mult | `LogStore.is_dupe`, `is_new_mult` | Hard-coded ARRL VHF. Fixed station: `(call, band)`. Rover (`/R`): `(call, band, grid)`. Mult: grid × band. |
| Rank score | `engine/scoring.py` | `vhf-default`: exclude dupe, non-CQ, unreachable; add `new_mult`, `points` (`BAND_POINTS`), `snr`, `cq`, `rover`. Breakdown is already on the roster row (`factors`). |
| Which file | `state/last_log.py` | Host file `last_log.json` remembers the N1MM `.s3db` + `contest_nr`. |
| Solo check | `agent/report.py` `format_report_solo` | Plain-language WSJT-X UDP check. N1MM block is titled as required “for the needed-vs-dupe roster test”. Missing N1MM is a warning, and an empty log makes every station look needed. |
| WSJT logged QSO | `server/app.py` `observe_wsjtx` | Type 5 `QSOLogged` and type 12 `LoggedADIF` go into `_logged_qsos` (last 80) for `GET /api/logged-qsos`. They do **not** enter `LogStore`. |
| ADIF parse | `log/app.py` | Length-aware ADIF reader used to **deliver** QSOs into N1MM. Available to reuse for reading. |
| Setup page | `server/static/setup.html` | Goal, networking, IF seats, agent config, H2 marks. The log is on `/log`. |

`LogSource` is real, and the server constructs `N1mmLogSource` in `seed_from_db`. Live N1MM still enters through the 12060 listener, not through a method on the protocol (`parse_live` is N1MM-only). Design §3.6’s `live_events()` is not on the protocol yet.

### Gaps this design closes

1. **One logger assumed.** Dupe/needed has a single authority: an N1MM contest file plus contact UDP. Solo with GridTracker, with only `wsjtx_log.adi`, or with no logger at all has no log copy.
2. **One contest rule.** ARRL VHF dupe/mult/points are inside `LogStore` and `BAND_POINTS`. A casual day, a band+mode contest, or a per-day dupe uses the same verdicts. N1MM’s contest list is not consulted.
3. **WSJT-X files unread.** Per-instance data dirs and a shared-drive ADIF are not discovered. Setup never says the log WIMS needs is missing.
4. **No cross-check.** Nothing reads two logs and reports “this QSO is only in WSJT-X” or “grids disagree”. `wims.log` is the N1MM **delivery** agent, a different job.

Storage-tier notes for Log4OM, CQRLOG, DXKeeper, and the rest stay in the [survey](wims_log_source_survey.md). This doc decides how solo uses them.

---

## 2. LogSource — keep the contract, add a poll

The engine keeps depending on `LoggedQso` + `LogSource`. N1MM stays the first backend. New backends implement the same protocol.

### 2.1 Protocol (extend, do not replace)

Already required: `kind`, `title`, `discover()`, `seed()`, `resync()`, `status()`.

Add one method with a default of “no events”:

```text
poll() -> list[LogEvent]
```

`LogEvent.op` stays `add` | `replace` | `delete`. File backends use `add` for a new ADIF record and `replace` when a full re-read changes a known id. `delete` is for N1MM `<contactdelete>` and for an ADIF re-read whose id disappeared.

N1MM does **not** move onto `poll()`. `N1mmLogSource.parse_live(xml)` stays the 12060 path. `poll()` on that class returns `[]`. File backends have nothing to parse from UDP, so `poll()` is their live path.

`status()` already returns a dict. File backends add:

| Key | Meaning |
|-----|---------|
| `paths` | Files this source is reading |
| `accessible` | `true` when every selected file opened |
| `warnings` | Plain-language strings for Setup (section 4) |
| `qso_count` | Last successful read |
| `last_poll_ts` | Epoch of the last `poll` |

`LogSourceCandidate.extra` carries `instance_id`, `accessible`, `warning`, and `shared` (true when two instances resolve to one file).

### 2.2 One primary feed

Operate has **one** primary `LogSource` into `LogStore`. Merging two live feeds double-counts. The audit tool (section 5) is the place that reads many logs at once.

| `kind` | Tier (survey) | Live path | Notes |
|--------|---------------|-----------|-------|
| `n1mm` | T1 | `parse_live` on 12060 | Exists. Fleet default when a usable `.s3db` is selected. |
| `wsjtx_adif` | T2 | `poll` ~1 s | New. Union of per-instance `wsjtx_log.adi`, or one shared file when that path is set. |
| `adif_drop` | T5 | `poll` ~2 s | New. Operator-picked ADIF (GridTracker export, shared drive, backup). Same parser as WSJT-X. |

Auto-pick when the operator has not chosen (`logs.json` `"explicit": false`) follows the Goal. It does not keep a leftover N1MM file just because that file opens. See §2.5. A saved choice in `logs.json` always wins, including across restarts and across Goal changes.

### 2.3 `LoggedQso` fields to add

Optional, default `None`, so current N1MM constructors stay valid:

| Field | Why |
|-------|-----|
| `submode` | FT8 / FT4 / MSK144 when ADIF `MODE` is only `MFSK` or `DIGI`. Dupe mode uses submode when present. |
| `qso_date`, `time_on` | `YYYYMMDD` / `HHMMSS`. Dupe-per-day and the audit clock. |
| `exchange` | Section, state, or serial when the logger stored one. |
| `state`, `section` | Split out of ADIF `STATE` / `ARRL_SECT` when present. |

Stable id for a file QSO (no N1MM `ID`):

```text
wsjtx|{realpath}|{qso_date}|{time_on}|{CALL}|{BAND}|{MODE}
```

UDP type 5 / type 12 uses the same function (`datetime_on`, call, band, mode) so a fast-path upsert and a later file read hit one row. Band comes from ADIF `BAND`, else from `FREQ` via `band_label_mhz`, else from the instance’s live band.

WSJT-X rewrites `wsjtx_log.adi` when the operator edits the log. `poll` treats a shorter file, or a size change that is not a pure append, as `resync()` + `reconcile()`. Append-only growth parses bytes after the last complete `<eor>`.

Parser: the length-aware reader in `wims.log.app` (honor `<tag:N>`). WIMS opens the file read-only and closes it after each read. It never writes the ADIF.

### 2.4 Where it hooks

`WimsServer` already holds `_log_source`. Seed and resync call `seed()` / `resync()` then `LogStore.reconcile`, as `seed_from_db` does for N1MM.

A 1-second timer under the server lock calls `primary.poll()` and applies events. The N1MM socket path is unchanged when the chosen log is N1MM. When the chosen log is WSJT-X or another ADIF file, `observe_wsjtx` also upserts type 5 / type 12 through the same id function (the file poll dedupes). N1MM contact packets do not enter the log copy in that case. That covers the seconds before the next poll, and the case where the file itself will not open (section 4).

### 2.5 Log to use (2026-10-17)

The **Log** page (`/log`) shows **Log to use**. The line is always there, in plain language:

`Log in use: <name>, <path>, <contact count>, <cutoff>`

The operator picks the log. The Goal does not. A saved choice in `logs.json` is reloaded immediately when it changes, without restarting the server, and it stays when the Goal changes.

Three fields, kept separate:

| Field | Meaning |
|-------|---------|
| Log (`selection`) | Which file counts. N1MM contest (name and contact count), a WSJT-X log (shared file or one radio), or a GridTracker ADIF the program already finds. |
| `count_since` | Optional UTC start. Contacts before this time do not count. |
| `count_until` | Optional UTC end. Contacts after this time do not count. Empty means no end. |

The window changes the needed/dupe **lookup**. Contacts outside it are not “already worked,” even though they remain in the logger’s file. This is not a display filter.

Presets, so nobody types a date:

| Preset | What it sets |
|--------|----------------|
| Whole log | Clears both times. |
| Start now | `count_since` is this moment. The end stays open. A fresh challenge (“how fast can I work 100 countries?”) uses this on the chosen log. |
| This year | `count_since` is January 1 of this year, local midnight, stored in UTC. The end stays open. |

**Suggestion, only when nothing is saved.** A contest Goal suggests the newest N1MM contest whose name matches that contest. A leftover file for a different contest is not used, and the page says so. Just operating, an award, or a custom list suggests the WSJT-X log. The page says why. **Suggested for this goal** clears a saved choice and lets that suggestion run again.

A new contest needs a new log in N1MM or the other logger. WIMS reads that log and does not create it. The page says that next to the selector.

Warnings, in plain words: the file is missing, it cannot be read, it has no contacts that count, or its newest contact is from before today’s operating session.

**How often a station counts** (once per band, once per band and mode group, once per contest, or a checklist scope) still applies, to the contacts inside the window.

WSJT-X’s logged ADIF does not store a contest name or an exchange. When that log is selected for a contest Goal, the Log page says county, section, and contest-name checks cannot be completed from it.

**Where the controls live.** Log to use, the count-since presets, the log-in-use line, per-radio log warnings, the shared WSJT-X file, Check logs, and Resync of an N1MM contest file are on `/log`. Setup keeps the Goal and the installation checks. `/n1mm` is only the list of several N1MM stations at once. With one N1MM station, or none, that tab stays hidden.

**Follow-up, not in this change.** A challenge view (countries so far, elapsed time, rate) can sit on this same log plus `count_since` / `count_until`. Do not add that pace UI until the lookup above is the one operators trust.

---

## 3. Contest rules

**Update (2026-10-19).** WSJT-X Colors is retired. Several WSJT-X instances
(`--rig-name` flex, IC9700, each with its own ini) do not share one color
list, and WIMS never parsed the DecodeHighlighting categories. Just operating
is the checklist. A saved `wsjtx-colors` choice is rewritten once into the
matching checklist lines (see §3.8). Sections 3.6 and 3.7 below describe the
retired path; they are not what Setup does now.

**Update (2026-10-17).** The casual control is no longer one Contest menu with
an empty “None” row. It is a Goal menu plus a second menu. See §3.8. Where
older sentences say “dropdown None”, read “Just operating (not a contest)”
with Worth working set to Checklist.

Dupe, multiplier, and QSO points are a **rules** object. Rank weights (`snr`, `cq`, `rover`, condition open/marginal/dead) stay in `ScoringStrategy`. The two axes are independent: rules decide “is this contact worth points / a mult, or already worked?”; the strategy decides how to rank the stations that are still worth working.

### 3.0 Which rule is active

The log and the rule are separate. Needed and dupe are always computed from the log chosen under **Log to use** (§2.5). The Goal only decides what counts against that log. Just operating uses the checklist. It is evaluated against the selected log, including when that log is an N1MM file. Choosing N1MM does not switch the rule to ARRL VHF.

**Rule, in order:**

| Step | When | Rule |
|------|------|------|
| (a) | Goal is a named contest | That contest’s rules file (section 3.2), against the log chosen in §2.5 |
| (b) | Goal is Custom and an Advanced rules file was saved | That file |
| (c) | Goal is Just operating, or Custom → My checklist | The checklist (section 3.8) |

A named contest wins over a custom file. Custom is not on the casual path: it appears in the dropdown only after Advanced saves one.

The active source is always visible: on Setup, as the plain sentence under Goal, and as one line on the Operate roster (`rules.source_label` in the state contract). Examples:

| Situation | Label |
|-----------|--------|
| Just operating | `Checklist` |
| Goal is NY QSO Party | `NY QSO Party` |
| Goal is Custom, saved contest rules | `Custom rules` |

### 3.1 Interface

New module `engine/contest_rules.py` (stdlib only):

```text
ContestRules
  id, title, summary          # summary is one sentence for Setup
  dupe(qso_view, call, band, mode, grid, when) -> (bool, reason)
  new_mult(qso_view, call, band, mode, grid, exchange) -> (bool, reason)
  qso_points(band, mode) -> (int, reason)
  checks() -> dict            # the loaded file, for Advanced and the state contract
  to_dict() -> dict           # state contract
```

`qso_view` is a small query surface over `LogStore` (`worked(call, band, mode, grid, day)`, `mult_seen(kind, value, band)`). Rules do not import N1MM.

`LogStore.is_dupe` / `is_new_mult` become one-line delegates so `scoring.build_candidate` stays valid. L1 wires `arrl-vhf` and locks today’s verdicts in `tests/unit/test_scoring.py` / `test_roster.py`. Later, `build_candidate` copies `reason` onto the candidate.

Roster row (state contract) gains:

| Field | Example |
|-------|---------|
| `need_reason` | `Needed: K1ABC is not in the log on 6m.` |
| `mult_reason` | `New mult: grid FN20 on 6m.` |

`factors[].detail` for `new_mult` and `points` uses the same sentences. Dupes stay on the roster (the console already hides them by default) with `need_reason` set, score excluded, reason visible when the operator shows worked stations.

### 3.2 One rules file per contest

Each contest is one small file WIMS loads. The engine does not hard-code NYQP, ARRL VHF, or the next one. JSON is the format (same as `last_log.json` and `if_seats.json`; stdlib `json` only). TOML is not a second format in v1. Python 3.11+ `tomllib` could read it later without a dependency.

Shipped files live in the package, for example `src/wims/rules/nyqp.json`. A custom file from Advanced is stored beside `last_log.json` and is not a substitute for the shipped file.

**License.** WIMS is GPL-3.0-or-later. Each rules file is an original summary, written from that contest’s published rules, with the rules URL in the file. Copying GPL-3.0 code (Not1MM contest plugins are the example) is allowed only with the original copyright and GPL notices kept. Prefer writing our own file from the sponsor’s page. Do **not** commit N1MM User Defined Contest gallery files (`.udc`) or DXLog contest files. Their licenses are not verified. An optional importer may read a `.udc` the operator already has on their own disk (section 3.3). It does not download or bundle one.

**Reference only, not shipped.** N1MM’s published UDC guide describes an INI-like `.udc` whose fields cover contest name, dupe type, points, multiplier names, exchange, and Cabrillo name. DXLog.net uses one `.txt` definition per contest (bands, modes, exchange, dupe, scoring) under its contest-definition folder. Those field lists are a map for the importer. They are not source files in this repo.

Schema (one contest):

| Field | Meaning |
|-------|---------|
| `id`, `title` | Stable id and the dropdown label |
| `license` | `GPL-3.0-or-later` |
| `rules_url`, `rules_version`, `rules_date` | Sponsor page, the version we read, and its date |
| `season` | `{start, end}` dates for this running. Used only to suggest the contest |
| `year` | Season year the file was written for |
| `aliases` | N1MM `ContestName` and ADIF `CONTEST_ID` strings that suggest this file |
| `mode_groups` | Map of group id → mode names. Built-in groups are `CW`, `PH`, `DIG` |
| `excluded_modes` | Ban list (section 3.2.1). A QSO in an excluded mode is not a contact in this contest |
| `dupe_scope` | `band` (call+band), `band+group` (call+band+mode group), or `all` (call once) |
| `dupe_reset` | What makes the same call new again. Example: `my_county` when a NY station changes county. Empty means no reset |
| `points` | Points per mode group, or a named table such as `vhf-band` |
| `multipliers` | List of `{type, who, cap, per}`. `per` is `band`, `mode`, `contest`, or `unverified` |
| `summary` | Plain sentence the UI shows. Generated if omitted |

Mode identity is `SUBMODE` when set, else `MODE`. A mode that is not in `PH` or `CW` is `DIG`, then the ban list removes it. `MFSK` alone does not pick a submode.

`arrl-vhf` stays the in-code rule for L1 so today’s fleet tests do not move: dupe call+band, rover `/R` adds grid, mult is 4-character grid × band, points are the existing `BAND_POINTS` (6m/2m 1, 1.25m/70cm 2, 33cm/23cm/13cm 3, higher 4). It becomes a file in the same schema when the loader exists. It is the N1MM-present default only when no contest file was suggested or picked. It is not the solo dropdown default.

While a multiplier’s `per` is `unverified`, WIMS does not mark `is_new_mult`. The summary says the scope is unconfirmed. Dupe and points still run. A missing exchange (county, section, state) does not invent a multiplier; the reason says the log has no exchange.

N1MM’s `ismultiplier` flag stays on the row. For `arrl-vhf` it still confirms grid × band. For a file-backed contest, prospective mults come from the file.

#### 3.2.1 Ban list

`excluded_modes` is a list of `{mode}` or `{mode, submode}`. This is the generic “digital but not these modes” mechanism. No contest is implied by the mechanism itself. NYQP uses it for modes that cannot carry that contest’s exchange. A later contest can list different modes without a code change.

Placeholder entry, not attached to a contest yet:

| ADIF | Cabrillo | UDP |
|------|----------|-----|
| `MODE=MFSK`, `SUBMODE=JTTY` | No Cabrillo code. Treat as `DG` if a Cabrillo line is ever written | The mode string WSJT-X puts on the UDP status/decode is **not** verified. Check it on a live JTTY period before matching decodes. Until then, classify JTTY only from ADIF `SUBMODE` |

A live decode whose UDP mode is empty or unrecognized is not guessed into JTTY. An excluded mode is not needed and scores 0. Plain reason: “FT8 is not counted in NY QSO Party.”

#### 3.2.2 First file: NY QSO Party

Written from the published rules, version **1.1**, dated **2026-09-25**: <https://nyqp.org/wordpress/nyqp-rules/>. Original summary. Not an N1MM or DXLog file.

Verified from those rules:

| Item | Value |
|------|--------|
| Dupe | Once per band per mode group |
| Groups | Phone = SSB, FM, AM. CW = CW. Digital = RTTY and every other digital mode, one group. Phone and digital on the same band do not dupe |
| Points | Phone 1, CW 2, digital 3 |
| NY station mults | 50 states + 62 NY counties + 13 Canadian provinces, cap 125 |
| Non-NY mults | NY counties only, cap 62 |
| DX | No multiplier |
| County change | A NY station that changes county is a new station (`dupe_reset: my_county`) |
| Entry | Digital QSOs count only in the Mixed category |
| Illegal modes | Digital modes that cannot carry the NYQP exchange natively are not allowed. Standard FT8 fails that test. FT4 is the same class (native exchange is a report/grid, not a county) and is on the ban list for that reason |

Unverified, so `multipliers[].per` is `unverified`: whether each state, county, or province counts once per contest or again on every band or mode. The caps are the sizes of those lists. They are not a statement of the per-band rule. Until this is checked against the rules page, WIMS does not mark new multipliers. Dupe and points do run.

`season` start/end for the suggestion come from that year’s rules page when the file is written. Do not invent the weekend in code.

Digital-only-in-Mixed is stored as an entry constraint. WIMS mentions it only when the operator’s category is already known (N1MM entry category). It does not add a category question to the casual screen.

Sketch (the shipped file matches this shape):

```json
{
  "id": "nyqp",
  "title": "NY QSO Party",
  "license": "GPL-3.0-or-later",
  "rules_url": "https://nyqp.org/wordpress/nyqp-rules/",
  "rules_version": "1.1",
  "rules_date": "2026-09-25",
  "year": 2026,
  "season": {"start": "", "end": ""},
  "aliases": ["NYQP", "NY-QSO-PARTY", "NY QSO"],
  "mode_groups": {
    "PH": ["SSB", "USB", "LSB", "FM", "AM"],
    "CW": ["CW"],
    "DIG": ["RTTY"]
  },
  "excluded_modes": [{"mode": "FT8"}, {"mode": "FT4"}],
  "dupe_scope": "band+group",
  "dupe_reset": "my_county",
  "points": {"PH": 1, "CW": 2, "DIG": 3},
  "multipliers": [
    {"type": "ny_county", "who": "all", "cap": 62, "per": "unverified"},
    {"type": "state", "who": "ny_station", "cap": 50, "per": "unverified"},
    {"type": "province", "who": "ny_station", "cap": 13, "per": "unverified"}
  ],
  "dx_multiplier": false,
  "entry_constraints": [{"modes": "DIG", "category": "Mixed"}],
  "summary": "Dupes: once per band per mode group."
}
```

`DIG: ["RTTY"]` plus “anything not PH or CW is DIG” covers the rest of the digital group. Confirm the exact N1MM `ContestName` / ADIF `CONTEST_ID` against one real NYQP log before treating `aliases` as complete. NY-station vs not: use N1MM or ADIF `MY_STATE` when present. If it is missing, multipliers use the non-NY set (counties only, the smaller one) and the summary says “WIMS does not know if this station is in NY, so only NY counties would count.” A fixed station with one county never trips `dupe_reset`. County comes from the logged exchange when the log has it.

### 3.3 Advanced editor and .udc import

Hidden under Advanced (section 3.5). Same schema as the shipped files, not a second language. The editor can change mode groups, the ban list, `dupe_scope`, `dupe_reset`, points, and multiplier `per`. Saving writes a custom file and sets the dropdown to Custom.

The importer reads one local `.udc` path the operator chooses. It fills the fields it recognizes (name, dupe, points, multiplier names) and lists what it skipped. It does not write the `.udc`, does not fetch the N1MM gallery, and does not accept a DXLog `.txt` until that license is known. Unmapped keys stay in an `unparsed` note on screen so the operator can see the gap.

### 3.4 What is remembered

The dropdown choice is a small file beside `last_log.json` (same directory rules: `$XDG_CONFIG_HOME/wims/`, else `~/.config/wims/`, Windows `%APPDATA%\wims\`). Do not extend `last_log.json`. `WIMS_CONTEST_RULES` may point at that file in tests. Operator docs do not mention it. There is no contest CLI flag.

```json
{
  "schema": 3,
  "contest": null,
  "fallback": "wsjtx-colors",
  "wsjtx_override": null,
  "gridtracker_path": ""
}
```

`contest` null means dropdown None (step c) unless N1MM is the log, in which case the in-code `arrl-vhf` rule applies until a suggestion or a pick says otherwise. A string id loads that rules file (step a). `"custom"` is step b.

`fallback` is `wsjtx-colors` (section 3.6) or `gridtracker` (section 3.7), used only when the dropdown is None and N1MM is not the log. `wsjtx_override` works as before: null mirrors the ini; a saved object means “edited in WIMS”.

Changing the dropdown applies on the next roster build and is saved. No separate Save button on the casual control. `POST /api/rules` remains the call the page uses.

State-contract key `rules`:

```json
{
  "id": "nyqp",
  "title": "NY QSO Party",
  "source_label": "NY QSO Party",
  "n1mm_authoritative": false,
  "summary": "Dupes: once per band per mode group.",
  "rules_url": "https://nyqp.org/wordpress/nyqp-rules/",
  "rules_version": "1.1"
}
```

### 3.5 Setup, for a casual operator

The screen operators see now is §3.8 (Goal, then Checklist). The bullets below are the 2026-10-15 dropdown. They are not the current Setup page.

This is part of the design, not polish to do later. The casual screen auto-detects what it can and asks for almost nothing.

Auto, with no extra questions: WSJT-X log locations (section 4), band and mode from UDP, IF-reporting seats (already on Setup), WSJT-X Colors settings (section 3.6). Where a contest is known, suggest it. Do not require it.

Suggestion sources, in order, never overriding an explicit dropdown choice:

1. N1MM `ContestName` or ADIF `CONTEST_ID` matches a file’s `aliases`.
2. Today’s date falls in a file’s `season`.

The dropdown moves to that contest and the sentence says it is a suggestion: “Suggested from the date: NY QSO Party. Choose Just operating (not a contest) if that is wrong.” Choosing Just operating sticks for that season window. See §3.8.

**Always visible**

- One dropdown, labeled Contest: None / NY QSO Party / ARRL VHF / … (Custom only if a custom file exists).
- One plain line from `summary`. NYQP’s line is “Dupes: once per band per mode group.” A second short clause is allowed when it changes what the operator will see, for example “FT8 and FT4 are not counted.”
- While N1MM is the log: “N1MM is the log of record.” The dropdown still selects which rules read that log. None under N1MM means `arrl-vhf`, not WSJT-X Colors.

**Advanced, collapsed by default**

- The section 3.3 editor, the custom file path, and the `.udc` importer.
- WSJT-X Colors category list and “Use WSJT-X.ini again”.
- GridTracker fallback path (section 3.7).
- Station state and county, only if they were not detected.

No new command-line arguments. `python -m wims solo` is unchanged. Operate shows `source_label` and each row’s `need_reason`. It does not grow a contest form. The log is chosen on `/log`. `/n1mm` lists several N1MM stations when more than one is on the network.

### 3.6 WSJT-X style needed rule

Retired 2026-10-19. Setup does not read a Colors ini. The behavior below is how that rule used to work, kept so the migration in §3.8 has something to map from.

Step (c), when the Contest dropdown is None and N1MM is not the log. It answers “needed?” for a **CQ** the way WSJT-X colors a decoded CQ. The scoring strategy still excludes non-CQ rows (“not calling CQ”).

A CQ is **needed** when **any** enabled category below matches the ADIF log (`wsjtx_log.adi`, or the shared file when that is the primary). The roster reason names the first match in Colors-tab order (top of the list wins). If WIMS cannot read that order, it uses the order in the table.

| Category | Needed when |
|----------|-------------|
| New DXCC | The call’s DXCC entity is not in the log |
| New DXCC on Band | That entity is not in the log on this band |
| New Grid | The grid is not in the log |
| New Grid on Band | That grid is not in the log on this band |
| New Call | The call is not in the log |
| New Call on Band | The call is not in the log on this band |

Options, same names as the Colors tab:

| Option | Effect |
|--------|--------|
| Highlight by Mode | Worked-before is per mode. A 6 m FT8 QSO does not count as worked for 6 m FT4. |
| Only grid Fields sought | Grid compare uses the first two characters (the field, `FN`) instead of the four-character square (`FN42`). Field and square highlighting are alternatives, as on the Colors tab. |

ADIF fields on each logged QSO:

| Field | Role |
|-------|------|
| `CALL` | Required. A record with no call is ignored. |
| `BAND` | Optional. Without it, the record does not fill “on band” sets. |
| `MODE` / `SUBMODE` | Optional. With Highlight by Mode off, mode is ignored. With it on, a record with no mode does not count as worked for any mode. Submode wins when both are present (FT8, FT4, MSK144 stay distinct). |
| `GRIDSQUARE` | Optional. Without it, the record does not fill grid sets. |
| `DXCC` | Optional. When present, that entity number is the logged entity. When absent, the entity comes from the call. |

DXCC for a decoded call (and for a logged call with no `DXCC` field) comes from WSJT-X’s `cty.dat`, read-only, searched beside the WSJT-X install and in the data directory. `log/pfx.py` is a small prefix table for N1MM inserts and is not the DXCC authority. If `cty.dat` cannot be read, New DXCC and New DXCC on Band stay off and Setup says “DXCC highlighting is off because cty.dat was not found.”

QSO points under this rule are flat 1. `is_new_mult` is true when the winning category is New DXCC, New DXCC on Band, New Grid, or New Grid on Band. New Call and New Call on Band are needed, and they are not multipliers. Example reasons:

- `Needed: New Grid on Band — FN20 on 6m is not in wsjtx_log.adi.`
- `Not needed: K1ABC on 6m FT8 matches no enabled WSJT-X color.`

Per instance: a decode on `--rig-name` 6m uses that instance’s ini and that instance’s `wsjtx_log.adi`. A configured shared log is the single ADIF; categories still come from the instance ini. If two inis disagree, Setup lists each one and the label says the rule is per instance.

**Read the Colors tab so the operator does not enter it twice.** WIMS reads the same ini `wsjtx_config.py` already opens (section 4.1 paths). Confirmed QSettings keys (WSJT-X `Configuration.cpp`, Colors tab):

| Key | Control |
|-----|---------|
| `HighlightByMode` | Highlight by Mode. Default false. |
| `OnlyFieldsSought` | Only grid Fields sought. Default false. |
| `IncludeWAEEntities` | Include extra WAE entities. Default false. Affects which DXCC entities count; not one of the six categories. Honor it when New DXCC is on. |
| `DecodeHighlighting` | The ordered category list: enabled flag plus colors, one row per highlight type. |

`HighlightByMode`, `OnlyFieldsSought`, and `IncludeWAEEntities` are plain `true`/`false` lines. `DecodeHighlighting` is a Qt `QVariant` list (`QList` of highlight rows, written with `QDataStream`). A stdlib reader for that blob is a spike (L3 in the milestone table). Until the blob parses, WIMS uses the factory defaults from `DecodeHighlightingModel::default_items` and Setup says: “WIMS could not read the Colors list from WSJT-X.ini. Showing WSJT-X’s default categories. You can edit them here.”

Factory defaults in current WSJT-X source (verify on the Colors tab of the installed build before coding — the list has grown): New DXCC and New DXCC on Band start enabled; New Grid, New Grid on Band, New Call, and New Call on Band start disabled. The same list also has rows that are **not** this needed rule: CQ in message, My Call in message, Transmitted message, New Continent, New Continent on Band, New CQ Zone, New CQ Zone on Band, New ITU Zone, New ITU Zone on Band, and LoTW. User guide §6.7 ([Colors](https://wsjtx.github.io/wsjtx/guide-full.html)) is the check. Dragging a row changes priority only. WIMS does not write `WSJT-X.ini`.

Implementation note (2026-10-15): the `DecodeHighlighting` blob is still unread. When `cty.dat` is found, WIMS shows the factory defaults above. When `cty.dat` is not found, New DXCC and New DXCC on Band cannot match, so those two stay off and New Call, New Call on Band, New Grid, and New Grid on Band start on. Setup says so. The operator can edit the six checkboxes under Advanced.

The General tab box “Show DXCC, grid, and worked-before status” (user guide §6.7) turns worked-before coloring on inside WSJT-X. Its ini key is **not** confirmed yet. When the spike finds it and the box is off, Setup says “WSJT-X is not coloring worked-before status (General tab). WIMS is still using the Colors categories below.” WIMS does not refuse the fallback because of that box.

If the operator edits a category in WIMS, save into `wsjtx_override` and stop live-mirroring until they press **Use WSJT-X.ini again**. No enabled category at all: Setup warns “No color category is enabled, so no CQ will show as needed.”

### 3.7 GridTracker roster as the fallback source

Alternative for step (c) only. The operator sets `fallback` to `gridtracker`. WIMS then mirrors GridTracker’s decode-list / call-roster filters (needed, new call, new grid, new DXCC, worked-before) instead of the WSJT-X Colors list. This is **read-only**. WIMS never writes a GridTracker file, never changes a GridTracker setting, and never sends GridTracker a configuration UDP.

**Where the settings live**

| What | Where | Confidence |
|------|--------|------------|
| GridTracker 2 app data | Windows `%APPDATA%\GridTracker2\` (`\Users\{name}\AppData\Roaming\GridTracker2`). Linux `~/.config/GridTracker2\`. macOS `~/Library/Application Support/GridTracker2\`. | GridTracker 2 changelog 2.241115 |
| GridTracker 1 export/import file | `Documents\gt_settings.json` (Windows `C:\Users\%user%\Documents\`, Linux `~/Documents/`). The Export Settings button writes this name. | GridTracker 1 user guide. This is a snapshot the operator exported, not proof of the live GT2 store. |
| Live roster filter object | In GT2 code the call-roster window reads `rosterSettings` (fields seen in source include `cqOnly`, `requireGrid`, `minDb`, `usesLoTW`, `useseQSL`, `usesOQRS`, `onlySpot`, and an award-tracker flag). Hunting mode is the New / New + Unconfirmed / Mixed control; the hunting target is Call, Grid, DXCC, and the other roster columns. | Seen in GT2 source. The on-disk JSON path of this object is **not** confirmed. |

**How WIMS would read them**

1. Look for a JSON settings file under the GT2 app-data directory. The filename is a spike (`gt_settings.json` is the name to try first; do not ship a guess).
2. If that directory has no readable JSON, use `gridtracker_path` when the operator set one (an exported `gt_settings.json` is the intended file).
3. Map the roster’s worked-before filter onto the same ADIF test as section 3.6, using the log files named in the settings. If the settings do not name a log, use `wsjtx_log.adi` and say “GridTracker’s log list was not in the settings file. Using wsjtx_log.adi.”
4. “New” means not in that log for the hunting target (call, grid, or DXCC). “New + Unconfirmed” also treats a logged QSO as still needed when the ADIF confirmation field GT uses is empty (`LOTW_QSL_RCVD` / `EQSL_QSL_RCVD` / `QSL_RCVD` — which field GT actually checks is part of the spike). If those fields are absent, treat the filter as “New” and say so.
5. Reload when the file’s mtime changes. Do not hold a write lock.

**Unknown until a spike on a real GT2 install**

- The live filename, and whether roster filters are in that JSON or in Chromium local storage (LevelDB under the app-data directory). LevelDB is out of scope for a stdlib reader. In that case the operator’s exported JSON is the supported input, and Setup says the live store was not a plain file.
- JSON keys for Hunting target, Callsigns = New / New + Unconfirmed / All, and per-band / per-mode worked-before.
- Whether GT’s “new grid” is a four-character square or a two-letter field.
- Which ADIF files GT has loaded when several are configured.

If the chosen file cannot be read, needed stays on the checklist (section 3.8). GridTracker is still a log you can pick under Log to use. It is not a second rules source.

### 3.8 Goal menu (2026-10-17)

The Setup control is two menus. The first is the goal. The second depends on that goal. Advanced stays collapsed. No new command-line flag. The page does not ask anyone to type a path for a normal start.

| Goal | Second menu | What “needed” means |
|------|-------------|---------------------|
| Contest | NY QSO Party, ARRL VHF, and any later rules file | That file (section 3.2), against the log |
| Award | DXCC, Worked All States, VUCC (grid squares), County hunting | A station is new when that place is not already in the log. A worked place that is not confirmed still counts, from a station not already worked there |
| Just operating (not a contest) | Checklist | The ticked lines below |
| Custom | My checklist, and Saved contest rules when Advanced has saved one | The ticked lines, or the saved custom file (section 3.3) |

“Just operating (not a contest)” is the old empty Contest row. The saved file still uses `contest: null` for that choice. A named contest id is unchanged. A saved `goal_id` of `wsjtx-colors` (including that old empty menu) is converted once, the first time the file is read, into checklist lines, then saved. WIMS does not read a WSJT-X.ini to do that.

**Awards.** Logged contacts are the already-have list. DXCC matches a country number stored on the contact, and a callsign country only when a lookup is available. Without that lookup the summary says a station counts only when the log stores a country number. Worked All States is the fifty US states; a province does not count, and a station with no state is not marked new. VUCC is the four-character grid square. County hunting is shown and disabled: WIMS does not have a county list.

**Checklist** (Just operating → Checklist, or Custom → My checklist). Each line is overall, per band, or per mode. One scope per line. New DXCC entity starts ticked, overall. Also available: new continent, new CQ zone, new ITU zone, new grid, new state or province, new call. Continent and the two zone lines need the country file (`cty.dat`) WSJT-X already keeps. When that file is missing they stay on the list, unchecked on screen, with a tip, and a saved tick is kept for the next time the file is found. New county and new callsign prefix are on the list and cannot be ticked. The short prefix table used for N1MM inserts is not a prefix list, and it is not used here. The Operate callsign badge names one new line: grid, state, DXCC, CQ zone, ITU zone, continent, or call. Judgment stays on that line's scope. When several lines are new, the badge shows one, in this order: grid, state, DXCC, CQ zone, ITU zone, continent, call. Grid is the smallest place the rules compute. A new call is last because it is not a multiplier. The score adds the new-multiplier weight once when any multiplier place is new, so the badge does not list the other places. Hover has the sentence for the place that won. The mult badge stays the word mult. Unconfirmed stays the word unconfirmed. County and prefix have no label. A contest row does not use this badge. The country file lists the prefix KG4 under Guantanamo Bay. A call with that prefix and a three-letter suffix, such as KG4LDK, is a United States call and uses the United States entry, including its zone rules. A one- or two-letter suffix, such as KG4AA, stays Guantanamo Bay. An exact callsign written in the file wins over both.

**Worked but not confirmed.** Awards and the checklist (grid, US state, DXCC entity, continent, CQ zone, ITU zone) use the log WIMS already reads. A place with no contact is **needed**. A place with a confirmed contact is not needed. A place that is worked and not confirmed is **unconfirmed** when the station heard is not one of the stations already worked for that place, in the scope the line uses. Overall means any band or mode. Per band means that band. Per mode means that mode. The same station again, in that scope, stays not needed. A station who has been worked before and has never confirmed any contact is not marked unconfirmed (a new place can still be needed). Under All, the hover can say worked before, never confirmed. A new call is not this rule: the call itself is the unit. Confirmation is a card or LoTW yes already in the log (`QSL_RCVD` or `LOTW_QSL_RCVD`). An eQSL yes (`EQSL_QSL_RCVD`) counts when that field is present. The accepted set is `CONFIRMED_QSL_FIELDS` in `adif.py`. WIMS also reads a LoTW confirmation file GridTracker already keeps on this PC, when it finds one. GridTracker 2 stores `LoTW_QSL.adif` under `Ginternal` in its config folder: `~/.config/GridTracker2` on Linux, `%APPDATA%\GridTracker2` on Windows, and `~/Library/Application Support/GridTracker2` on macOS. An `XDG_CONFIG_HOME` config folder is checked on Linux and macOS too. GridTracker 1 stored `LogbookOfTheWorld.adif` in `~/Documents/GridTracker` (and under OneDrive Documents on Windows). When more than one of these files is present, the newest wins. WIMS only reads the file, and reads it again when the file's modified time changes. It does not download LoTW and it does not write the file. A logged contact is confirmed when a LoTW record matches the call, the band, the mode, and the start time within 30 minutes (LoTW's window). Modes in the same LoTW mode group match, so FT8 matches DATA and MFSK. The grid, state or province, and DXCC entity on that record also count as confirmed for that place, on the record's band and mode group. Setup says `LoTW confirmations: from GridTracker, updated <time>`, or `LoTW confirmations: not found`. A file that is not ADIF is reported as unreadable and confirms nothing. Setup has one checkbox, **Count worked but not confirmed as needed**, stored as `count_unconfirmed` (default true). Needed, Needed and CQ, and Needed and CQ or 73 include those stations when the box is checked. All still shows them, with the word unconfirmed, when it is not. Contest rules do not use this. Work stays a click. Nothing transmits on its own.

Zones use the country-file number when the entity is one zone. A prefix written as `prefix(cq)[itu]` uses that number. United States, Canada, Russia, Australia, and China span more than one CQ zone; those plus Brazil span more than one ITU zone. For those, the zone comes from the grid when the square sits inside one zone box (`rules/zones.py`, approximating the CQ WAZ map and the EI8IC ITU map). A missing grid, a two-character field, or a square the boxes will not call is **zone uncertain**. That station is not marked needed for the zone. A logged contact with an uncertain zone does not count as that zone already worked. ADIF `CQZ`, `ITUZ`, and `CONT` on a logged contact win over the derivation.

**Colors migration.** `new_dxcc` → DXCC overall, `new_dxcc_band` → DXCC per band, and the same for grid and call. Both on → per band. Highlight by mode, only when it was saved in WIMS, changes the call line to per mode (a new band in a mode already worked is then not marked; the checklist keeps one scope). DXCC and grid are not changed by that flag. Only grid fields sought is not migrated; grid stays four characters. No saved category list → the factory pair, New DXCC and New DXCC on Band, which is one line: DXCC per band. A contest goal that still has a leftover color edit keeps the contest and does not copy those categories onto its checklist.

**Log.** The Goal does not choose the log. The Log page → **Log to use** does (§2.5). An explicit contest, award, checklist, or Just operating reads that same log. Nothing in the goal selects a different file.

**Suggestion.** A date or contest name in the log may still move an unset menu to a contest. The sentence says it is a suggestion and tells the operator to choose Just operating if that is wrong. An explicit goal is not overwritten.

**Saved file.** Schema 5, same path as before, beside `last_log.json`. On startup an older file is rewritten once. `contest` is kept in sync for a contest id and for saved contest rules. Awards and Just operating leave `contest` empty. `fallback` is cleared. `wsjtx_override` is cleared after the Colors lines have been copied onto the checklist.

```json
{
  "schema": 5,
  "goal": "operating",
  "goal_id": "checklist",
  "contest": null,
  "explicit": true,
  "count_unconfirmed": true,
  "checklist": {
    "dxcc": {"enabled": true, "scope": "overall"},
    "continent": {"enabled": false, "scope": "overall"},
    "cq": {"enabled": false, "scope": "overall"},
    "itu": {"enabled": false, "scope": "overall"},
    "grid": {"enabled": false, "scope": "overall"},
    "state": {"enabled": false, "scope": "overall"},
    "county": {"enabled": false, "scope": "overall"},
    "prefix": {"enabled": false, "scope": "overall"},
    "call": {"enabled": false, "scope": "overall"}
  }
}
```

`goal_id` for a contest is the rules-file id (`nyqp`, `arrl-vhf`). For an award it is `dxcc`, `was`, `vucc`, or `county`. For Just operating it is `checklist`. For Custom it is `checklist` or `custom-file`.

A heard station counts as a new state only when its state is already known (a state on the logged contact, or the exchange). A decode with no state is not invented from the callsign or from the grid. The summary says so.

---

## 4. WSJT-X log discovery and the “log not accessible” warning

Solo’s server is on the WSJT-X PC, so it can read the files. A fleet site server on another machine cannot; that case is the seat agent reporting the same structure inside the existing agent report (after L4, same messages). L4’s acceptance test is solo.

### 4.1 Paths

`--rig-name NAME` uses the application name `WSJT-X - NAME`. The default instance is `WSJT-X`. UDP id `WSJT-X`, blank, and `(active/default)` all mean the default directory.

| OS | Data / log directory | Log file | Settings file (already scanned) |
|----|----------------------|----------|----------------------------------|
| Windows | `%LOCALAPPDATA%\WSJT-X\` | `wsjtx_log.adi` | `%LOCALAPPDATA%\WSJT-X\WSJT-X.ini` |
| Windows, `--rig-name NAME` | `%LOCALAPPDATA%\WSJT-X - NAME\` | `wsjtx_log.adi` | `WSJT-X.ini` in that same directory |
| Linux | `$XDG_DATA_HOME/WSJT-X/` or `~/.local/share/WSJT-X/` | `wsjtx_log.adi` | `~/.config/WSJT-X.ini` |
| Linux, `--rig-name NAME` | `…/WSJT-X - NAME/` | `wsjtx_log.adi` | `~/.config/WSJT-X - NAME.ini` |

`wsjtx.log` (CSV, same directory) is a fallback only when the `.adi` is missing and the CSV exists. The ADIF is the contract.

**Discovery gap today:** `wsjtx_config.discover_ini_paths` globs `%LOCALAPPDATA%\WSJT-X\**\WSJT-X*.ini` and `~/.config/WSJT-X*.ini`. It does not look at sibling `%LOCALAPPDATA%\WSJT-X - NAME\`, and it does not look at `~/.local/share` at all. Log discovery is a new helper (L4), not a reuse of that glob. It should also list those sibling ini dirs so the setup check can name rigs that are installed but not yet heard on UDP.

Match a live UDP id to a directory by that rig-name. Operator overrides win (`logs.json` below).

### 4.2 Shared drive and one file for several instances

WSJT-X has no “log path” setting. A shared log is one of:

1. The operator sets **Shared log file** in Setup to a full path (`\\server\vhf\logs\wsjtx_log.adi`, `D:\contest\wsjtx_log.adi`, `/mnt/contest/wsjtx_log.adi`).
2. The per-instance `wsjtx_log.adi` is a symlink or junction to that file. `Path.resolve()` collapses them. When two rigs share one resolved path, status says “6m and 2m write the same log file. WIMS counts each contact once.” and the primary source reads it once.

If **Shared log file** is set, `LogStore` reads that file and does not also ingest the per-instance files. The audit tool may still be pointed at both.

`logs.json`, same config directory, override `WIMS_LOGS`:

```json
{
  "schema": 2,
  "primary": "auto",
  "explicit": false,
  "selection": null,
  "count_since": "",
  "count_until": "",
  "cutoff": "whole",
  "shared_path": "",
  "overrides": {"6m": "D:/contest/6m.adi"}
}
```

`primary` is `auto` | `n1mm` | `wsjtx` | `adif`. `explicit` false means the Goal may suggest a log (§2.5). A saved `selection` wins. `count_since` and `count_until` are separate UTC timestamps; empty means that side is open. `overrides` maps a UDP id to one ADIF file. Schema 1 files still load: `primary` other than `auto` is a saved choice.

Do not search the network for logs. Only default data dirs, overrides, and `shared_path`.

A dead UNC path can block `Path.exists()` for a long time. Stat configured UNC paths on the poll thread; if the call exceeds about 2 seconds, mark the source unreadable and wait 30 seconds before trying again.

### 4.3 Warning copy

Shown in two places, same sentences:

1. Solo setup check (`format_report_solo`), new **Logs** section. The N1MM section stays, retitled as optional: “N1MM (optional contest log)”.
2. Log page, **Each radio’s log**, fed by state key `log_access` (and, before any UDP, by the on-disk scan the solo check already ran).

| Situation | Severity | Sentence |
|-----------|----------|----------|
| Heard UDP id, data directory missing | warn | “WIMS hears {id} but cannot find its WSJT-X folder ({path}). Contacts from this radio will be missing from dupe checking. Set the log file on the Log page.” |
| Directory exists, no `wsjtx_log.adi` yet | note | “{id} has no wsjtx_log.adi yet. WSJT-X creates that file when you log the first contact. Until then, stations on this radio look needed.” |
| Path set, open fails (share offline, permissions) | warn | “The log for {id} is not readable ({path}). If this file is on a shared drive, connect that drive. Dupe checking is incomplete.” |
| Open fails because the file is locked | warn | “WSJT-X has {path} open so WIMS cannot read it. WIMS will use contacts logged while WIMS is running, and will miss older ones.” |
| No N1MM file and no readable ADIF | warn | “No contest log and no WSJT-X log is readable. Every station will look needed.” |
| N1MM process absent, `.s3db` readable, primary is still N1MM | note | “N1MM is not running. WIMS is using the contest file {label}. Choose the WSJT-X log on the Log page if that file is the wrong log.” |
| Readable log | ok | “{id}: {path} ({n} contacts).” |

`log_access` entries: `{instance, path, status, message}` with `status` of `ok` | `missing_file` | `missing_dir` | `unreadable` | `locked`.

Empty-before-first-QSO (`missing_file`) is normal. It is a note, not a fault, and it does not fail the solo check’s error count. `missing_dir`, `unreadable`, and `locked` are warnings.

---

## 5. Log audit tool

A separate read-only check that the selected logs agree. It is how the operator audits a weekend run **with no logger**: the WSJT-X ADIF files are the digi record, and any other file the operator adds is compared to them.

Package `src/wims/logaudit/` (new). Do not put this in `wims.log`, which inserts into N1MM.

### 5.1 Sources, in build order

Readers are shared with section 2 (ADIF parser, N1MM `read_dxlog`). The audit tool is allowed to open many at once. Operate is not.

| Priority | Source | What “support” means first | Native database |
|----------|--------|----------------------------|-----------------|
| 1 | WSJT-X ADIF | `--wsjtx-auto` uses section 4 discovery, including a shared path | The ADIF is the store |
| 2 | N1MM Logger+ | `--n1mm-db` + optional `--contest-nr` via existing `read_dxlog` | Already implemented |
| 3 | Generic ADIF | Repeatable `--adif PATH` (shared drive, backup, any program’s export) | — |
| 4 | GridTracker | `--gridtracker PATH`, or `--gridtracker-auto` after a path spike | ADIF inside the GT data dir. Likely roots: Windows `%APPDATA%\GridTracker2\`, Linux `~/.local/share/GridTracker2/`. Filename is **not** locked here — spike, then pick `*.adi`. |
| 5 | LoTW | `--lotw PATH.adi` from a file the operator downloaded | Confirmation overlay. A local QSO missing from LoTW is a note (“not in this LoTW download”), not a failed match. |
| 6 | Log4OM | ADIF export via `--adif` until a SQLite spike (survey checklist) | Later |
| 7 | DXKeeper, N3FJP, HRD, Logger32 | ADIF export via `--adif` | No Access / `.mdb` in-process |
| 8 | CQRLOG, QLog, KLog | ADIF export via `--adif` | SQL only after a spike |
| 9 | Cabrillo | After the contest, file compare | Later; not a live logger |

### 5.2 Where the operator runs it

Check logs is an occasional tidy-up. It is not part of the live console. Operate does not host it.

Two ways to open it, same check:

1. Double-click **Check logs** (Desktop, Start menu, or app menu). `Add WIMS to Desktop` creates that icon along with **WIMS**. The files are `scripts/Check logs.sh` and `scripts/Check logs.bat` (Windows also `scripts/windows/Check-Logs.cmd`).
2. Log page → **Check logs**.

The window opens immediately and says what it is doing (which file it is checking, which file it skipped because it had not changed). The first line of the result is a plain summary. **Show details** lists only contacts that are in one log and missing from another, grouped under the log that lacks them, with a filter and pages of 40. Exact extra copies inside one log are counted, not printed one by one.

A path that does not answer within 2 seconds is marked unreadable. Six radios that point at one dead share wait once, not six times. The sentence says to connect that drive and check again.

While the check runs it remembers each file’s size and modification time. The next check does not read a file that has not changed.

Several instances that point at one log are one log. “Point at one log” means the same real path, the same inode (a link), or the same bytes. That collapse is not reported as duplicates. The summary says how many logs were read and how many of them were shared.

Exit 0 when every selected log opened and the logs agree. Exit 1 when a contact is missing from one of the logs, a grid or mode disagrees, or extra copies were collapsed. Exit 2 when a selected path could not be read, including a path that did not answer. Notes (LoTW not checked, GridTracker not installed) do not by themselves fail the run.

### Developer

```text
python -m wims.logaudit
python -m wims.logaudit --wsjtx-auto --n1mm-db "D:\N1MM Logger+\Databases\2026 Sep.s3db" --contest-nr 3
python -m wims.logaudit --adif \\server\vhf\logs\shared.adi --lotw lotw.adi --json report.json
```

No arguments: discover local WSJT-X logs, the N1MM log chosen in WIMS, and a GridTracker ADIF under the GridTracker data folder. Progress lines go to standard error. The report goes to standard output.

### 5.3 What “consistent” means

Normalize each QSO to a match key:

- Call, uppercased, spaces removed. `/R` stays, so a rover is a different call from the fixed station.
- Band from `BAND` or frequency, via `band_label_mhz`.
- Mode: submode if present, else mode.
- Time: `QSO_DATE` + `TIME_ON` as UTC. Two records **match** when call, band, and mode agree and the times differ by at most 3 minutes (WSJT-X and N1MM often disagree by the logging second).
- Grid: when both sides have one, the first four characters must agree. Six characters versus four is a match on the first four. One side missing a grid is a **note** on that pair, not a disagreement.

Greedy one-to-one pairing inside the window. A QSO already paired is not paired again.

| Result | Meaning |
|--------|---------|
| Matched | One record on each side, key agrees, grid agrees or is absent on one side. |
| Disagreement | Paired, and grid (4-char) or band or mode differs. Time is already inside the window. |
| Only in A | No partner in the other selected sources. The summary counts that contact as missing from each other log. |
| Duplicate inside one file | Two records in the same file with the same call, band, mode, and time window. |
| Same file from several instances | One log. Same real path, same inode, or identical bytes. Not a duplicate and not a match against itself. The summary counts it as a shared file. |

LoTW uses the same pairing, and an unpaired local QSO is filed under Notes, not under “Only in”. An LoTW QSO with no local partner is “Only in LoTW” (logged on another computer, or call/time outside the window).

Default window is the whole file. `--since YYYY-MM-DD` drops earlier QSOs before pairing.

The tool does not delete, merge, or rewrite any log.

### 5.4 Report format

The first line is the summary. ASCII marks on the source list stay consistent with the solo check (`[OK]` `[! ]` `[XX]`). Details list contacts missing from a log, not the contacts that matched. A long list stops after 40 rows in the text report and says how many remain. The window pages those rows and can filter them.

```text
WIMS log check
==============
3 logs read, 1 shared file, 12 contacts missing from N1MM.

Sources
  [OK] WSJT-X   C:\Users\op\AppData\Local\WSJT-X\wsjtx_log.adi  (128 contacts; shared by WSJT-X 6m, WSJT-X 2m)
  [OK] N1MM     D:\N1MM Logger+\Databases\2026 Sep.s3db  (116 contacts)
  [OK] GridTracker log.adi  (128 contacts)

Window: all contacts

Matched: 116
Missing from N1MM: 12
Disagreements: 0
Extra copies collapsed: 0

Missing from N1MM
  2026-09-12 14:02  K1ABC  6m  FT8  FN42  (in WSJT-X)

Notes
  LoTW was not checked.
```

Why an earlier build was slow, measured on synthetic ADIF before this change: pairing walked every contact against every later contact. Two copies of 1,000 contacts took 0.08 s, 5,000 took 1.9 s, and 15,000 took 19.7 s. Reading one 15,000-contact file took about 0.3 s. Discovery also parsed every instance log, and it did that again inside the per-file loop. A dead UNC path has no timeout on `stat`. After the change, 20,000 contacts in two logs (50 missing) finishes in about 1 s, including the read.

JSON outline: `{summary, sources, window, matched, matched_count, only, missing, disagreements, duplicates, notes}`. Each row includes `call`, `band`, `mode`, `time`, `grid`, `source`. `missing` is grouped by the log that lacks the contact. The Setup page and the Check logs window send that shape without the full `matched` list.

---

## 6. Risks

| Risk | What we do about it |
|------|---------------------|
| Extracting rules changes fleet VHF verdicts | L1’s only in-code preset is `arrl-vhf`, delegated from today’s `is_dupe` / `is_new_mult`. Existing scoring tests must pass unchanged. Just operating uses the checklist against whichever log is selected (§2.5). The log does not switch that rule. |
| Shipping someone else’s contest definition | Rules files are original GPL-3.0 summaries with `rules_url`. No N1MM `.udc` gallery and no DXLog `.txt` in the repo. Importer reads only a path the operator picks on their machine. |
| NYQP multiplier scope guessed wrong | `per` stays `unverified`. New-mult stays off until the rules page is checked. Dupe and points still follow the verified table. |
| Shared file plus per-instance files double-count in `LogStore` | Primary reads one or the other (section 4.2). Audit may read both and labels those pairs as the same contact. |
| WSJT-X holds an exclusive lock on Windows | Warning `locked`. UDP type 5/12 fills contacts logged after WIMS started. Older contacts stay missing until the file opens. Confirm lock behavior on a real Windows WSJT-X before trusting the warning text. |
| ADIF edit rewrites the file; there is no per-record delete | Shrink or non-append size change ⇒ full `resync` + `reconcile`. |
| Id mismatch between UDP and file | One id function (section 2.3). A test fixture logs one QSO both ways and expects one row. |
| Dead network share stalls the server | UNC stat on the poll thread with a 2 s budget and 30 s backoff. |
| Mode strings disagree (`FT8` vs `DIGI` vs `MFSK`) | Prefer submode. Audit reports a mode disagreement when the normalized values differ, so the operator sees it. |
| Section / state mult with a WSJT-X-only log | Setup says new-mult stays off (section 3.2). We do not invent a section from the callsign. |
| N1MM `gridsquare` empty (already true for some DX configs) | Grid mult stays “no grid”. Audit files a missing grid as a note. |
| `Path.resolve()` on Linux does not see a Windows junction made elsewhere | Compare resolved paths on the machine that holds the file. Document that the shared-drive check runs on the WSJT-X PC. |
| Audit time window pairs the wrong QSO when a station is worked twice in 3 minutes | Rare on FT8. The report shows both times. A later milestone can tighten the window; 3 minutes is the first cut. |
| Reading Log4OM SQLite while it is open | Out of scope until the survey spike. ADIF export only. |
| `DecodeHighlighting` is a Qt binary list | Closed 2026-10-19. WIMS does not read a Colors ini. A saved color list, if the operator edited one in WIMS, is converted once to checklist lines (§3.8). |
| Mirroring GridTracker writes or guesses its config | Read-only open. No write, no UDP. GridTracker stays a selectable log. It is not a rules source. Needed stays on the checklist when no other goal is chosen. |
| Two rules both apply | Section 3.0 picks one source. The roster label is that source. |

---

## 7. Open questions

1. **Solo default — resolved (2026-10-15), UX revised the same day, Goal menu 2026-10-17, Colors retired 2026-10-19.** Just operating ⇒ Checklist. A saved WSJT-X Colors choice is rewritten once as checklist lines. A suggested contest (date or `CONTEST_ID`) may move an unset menu to that contest, and the sentence says it is a suggestion. An explicit choice sticks. The log under Log to use is the only log, including when that log is N1MM. Choosing N1MM does not switch the rule to `arrl-vhf`. See §3.8.
2. **GridTracker filename.** Confirm on a real GT2 install (Windows and Linux) before `--gridtracker-auto` looks for a log name, and before the fallback reader looks for a settings file (section 3.7). Until then the operator passes a path.
3. **File lock.** Does WSJT-X on Windows allow a second process to read `wsjtx_log.adi` while the program is open? The locked-file warning depends on the answer.
4. **Suggest vs auto-switch** when N1MM `ContestName` maps to a preset. This proposal suggests only. Auto-switch would surprise someone who set Custom.
5. **Dupe period “contest weekend”** as a third period value (start/end timestamps) versus UTC day plus a `--since` on the audit only.
6. **Cabrillo** after the contest: in the audit tool later, or leave it to N1MM’s export?
7. **Fleet.** Seat agent reports `log_access` for WSJT-X PCs the site server cannot read. Confirm that L4 solo is enough before any agent work. The Colors ini and `wsjtx_log.adi` are on the WSJT-X PC; a remote site server cannot be the step (c) reader.
8. **General-tab master switch.** User guide §6.7 “Show DXCC, grid, and worked-before status” — confirm the ini key. Behavior until then is in section 3.6.
9. **Colors category list on the installed build.** Header `DecodeHighlightingModel` lists more rows than the six needed-categories (continent, CQ/ITU zone, LoTW). Confirm the Colors tab before coding, and do not treat those extra rows as needed unless the operator asks.
10. **NYQP multiplier scope.** Once per contest, or again per band or mode? Unverified against <https://nyqp.org/wordpress/nyqp-rules/> (v1.1, 2026-09-25). Do not mark new mults until this is filled in.
11. **NYQP season dates and alias strings.** `season.start` / `season.end`, N1MM `ContestName`, and ADIF `CONTEST_ID` — fill from the rules page and one real log. The suggestion logic stays off for NYQP until `season` is non-empty.
12. **JTTY on the UDP wire.** ADIF is `MODE=MFSK` / `SUBMODE=JTTY`. The status/decode mode string is unchecked. Cabrillo has no JTTY code; assume `DG` only if Cabrillo export is built.

---

## 8. Milestones

Each step is shippable on its own. Tests are stdlib `tests/unit/test_*.py` plus a tiny ADIF under `tests/fixtures/logsource/`. No pytest. Fixtures stay small and synthetic.

| Id | Deliver | Done when |
|----|---------|-----------|
| **L1** | `ContestRules` + preset `arrl-vhf`. `LogStore.is_dupe` / `is_new_mult` delegate to it. | Existing scoring, roster, and N1MM log tests pass with no verdict change. New tests call the rules object directly. |
| **L2** | Dropdown choice file (schema 3) and `rules.source_label`. Casual Setup is one Contest dropdown plus the plain summary. Advanced stays collapsed. No new CLI flag. | N1MM and dropdown None ⇒ `N1MM · ARRL VHF`. Solo dropdown None ⇒ `WSJT-X Colors`. Picking NY QSO Party shows “Dupes: once per band per mode group.” A date or `CONTEST_ID` suggestion does not override an explicit None. |
| **L3** | Rules-file loader. First file `nyqp.json` (section 3.2.2), original text, `rules_url` set. Generic `excluded_modes`. WSJT-X Colors remains dropdown None, including Highlight by Mode and Only grid Fields sought. Read the plain ini bools. Spike `DecodeHighlighting`. | Tests: phone and digital on the same band are not a dupe; two digital modes on the same band are; points 1 / 2 / 3; FT8 scores 0 and is not needed; `per: unverified` does not set `is_new_mult`. N1MM-primary tests still expect `arrl-vhf`. A JTTY ban-list entry is accepted by the loader and is not wired to NYQP. |
| **L4** | Discover per-instance and shared paths. Warnings in the solo check and on Setup (`log_access`). | A fixture directory tree (default + `--rig-name` + missing dir + shared symlink) produces the sentences in section 4.3. `LogStore` still unchanged. |
| **L5** | `WsjtxAdifLogSource` + `adif_drop`. Solo auto-pick (section 2.2). Poll + UDP fast path, one id function. | With no N1MM file, a sample `wsjtx_log.adi` seeds dupes. Appending one record flips that call to a dupe. N1MM seed still works when `last_log.json` points at a `.s3db`. |
| **L6** | Check logs for WSJT-X, N1MM, and generic ADIF. Summary first, text + JSON. | A fixture pair with one missing QSO, one grid clash, and one match exits 1 and prints the section 5.4 shape. Shared path, inode, and identical bytes count as one log. Read-only. |
| **L7** | GridTracker ADIF under the app-data folders. LoTW file as notes. Setup **Check logs** and the Desktop **Check logs** icon render the same summary. | A GT sample ADIF and a LoTW sample produce notes, and an unpaired LoTW-only row is not a hard “missing from WSJT-X” failure. A path that does not answer within 2 seconds is unreadable. Unchanged files are not read again. |
| **L8** | More loggers as `--adif` documentation and, only after a survey spike, one native reader (Log4OM SQLite or CQRLOG). | The spike checklist in the survey is filled in for that one program before any SQL is merged. |
| **L9** | GridTracker roster as the step (c) alternative (section 3.7). Read-only. | A fixture JSON (once the spike names the file and keys) selects “new grid” and a CQ in a logged grid is not needed. Missing file ⇒ WSJT-X Colors, with the Setup sentence in section 3.7. No GridTracker file is written. |
| **L10** | Goal menu (section 3.8). Schema 4 migrates a schema 3 contest id. | Setup shows Goal, then a second menu. Just operating stays on WSJT-X Colors. DXCC, WAS, and VUCC use the log as the already-have list. County and callsign prefix are visible and not selectable. An explicit Just operating choice is not replaced by a date or contest-name suggestion. N1MM plus Just operating stays ARRL VHF. |

L1 does not require a logger change. L2 can ship the source label before L3 fills in Colors parsing. L4 does not require rules beyond L1. L9 waits on the section 3.7 spike and can share the ADIF reader with L5. L6 can start as soon as that reader exists; it can also carry its own small reader if L5 slips, as long as the id and field rules match section 2.3.
