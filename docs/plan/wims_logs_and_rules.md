# WIMS logs, contest rules, and log audit

**Status:** design proposal (no runtime change in the PR that added this file)
**Date:** 2026-10-15
**Related:** [wims_design.md](wims_design.md) §3.5 / §3.6 / §3.10 / §3.11;
[wims_log_source_survey.md](wims_log_source_survey.md) (storage tiers and logger ranking);
[wims_status.md](wims_status.md) milestones **L1–L8**.

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
| Setup page | `server/static/setup.html` | Networking, IF seats, agent config, H2 marks. Contest pick/resync is on `/n1mm`. No rule choice. No per-instance log path. |

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

Auto-pick when the operator has not chosen (`logs.json` `"primary": "auto"`):

1. Saved `last_log.json` whose `.s3db` still opens → `n1mm` (today’s restart behavior).
2. Else a configured shared ADIF that opens → `wsjtx_adif` on that file alone.
3. Else every accessible per-instance `wsjtx_log.adi` → one `wsjtx_adif` union.
4. Else an empty log, and Setup says so.

A remembered N1MM file still wins, including when Logger+ is closed, so a contest PC keeps its dupe base. Setup offers “use WSJT-X logs instead” as an explicit choice.

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

A 1-second timer under the server lock calls `primary.poll()` and applies events. The N1MM socket path is unchanged. When the primary is `wsjtx_adif`, `observe_wsjtx` also upserts type 5 / type 12 through the same id function (the file poll dedupes). That covers the seconds before the next poll, and the case where the file itself will not open (section 4).

---

## 3. Contest rules

Dupe, multiplier, and QSO points are a **rules** object. Rank weights (`snr`, `cq`, `rover`, condition open/marginal/dead) stay in `ScoringStrategy`. The two axes are independent: rules decide “is this contact worth points / a mult, or already worked?”; the strategy decides how to rank the stations that are still worth working.

### 3.0 Which rule is active

Two questions, in this order.

**1. Is N1MM the log of record?** Yes when the primary `LogSource` is `n1mm` (saved `.s3db` still opens, or the operator chose N1MM). Then N1MM is authoritative: needed and dupe are computed from that log and a contest rule. The WSJT-X Colors rule and the GridTracker mirror are not applied. Rule inside that case:

1. Contest preset the operator picked.
2. Else the saved home/custom checkbox set, if there is one.
3. Else `arrl-vhf` (today’s fleet behavior).

Setup says so: “N1MM is the log of record, so needed uses {rule}. The WSJT-X / GridTracker fallback is not used.” Switching the log primary to WSJT-X ADIF (section 2.2) is how solo leaves N1MM.

**2. Solo, N1MM not the log.** Needed for a CQ uses this order (owner direction, 2026-10-15):

| Step | When | Rule |
|------|------|------|
| (a) | Operator picked a contest preset (`arrl-vhf`, `casual`, `band-mode`, …) | That preset, against the ADIF log |
| (b) | No preset, and a home/custom checkbox set is saved | Those checkboxes (section 3.3) |
| (c) | Neither | Fallback source (section 3.6 or 3.7) |

A picked preset wins over a saved custom set. Setup shows that, so a leftover custom file does not silently apply. `casual` is an explicit preset (step a), not the automatic fallback.

The active source is always visible: on Setup, at the top of **Contest rules**, and as one line on the Operate roster (`rules.source_label` in the state contract). Examples:

| Situation | Label |
|-----------|--------|
| N1MM log, no extra pick | `N1MM · ARRL VHF` |
| Operator picked Band + mode | `Contest rule · Band + mode` |
| Custom checkboxes, no preset | `Custom checkboxes` |
| Fallback, ini read succeeded | `WSJT-X Colors · WSJT-X.ini` |
| Fallback, operator edited the copy in WIMS | `WSJT-X Colors · edited in WIMS` |
| Operator chose the GridTracker mirror | `GridTracker roster` |

### 3.1 Interface

New module `engine/contest_rules.py` (stdlib only):

```text
ContestRules
  id, title, summary          # summary is one sentence for Setup
  dupe(qso_view, call, band, mode, grid, when) -> (bool, reason)
  new_mult(qso_view, call, band, mode, grid, exchange) -> (bool, reason)
  qso_points(band, mode) -> (int, reason)
  checks() -> dict            # the checkbox snapshot, for the UI
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

### 3.2 Built-in presets

Checkboxes (section 3.3) are filled by the preset and shown disabled, so the operator can see the rule.

| Id | Title | Dupe key | Rover | Mult | Points | Summary shown on Setup |
|----|-------|----------|-------|------|--------|------------------------|
| `arrl-vhf` | ARRL VHF | call + band, whole log | `/R` adds grid | 4-char grid × band | Existing `BAND_POINTS` (6m/2m 1, 1.25m/70cm 2, 33cm/23cm/13cm 3, higher 4) | “ARRL VHF: worked on this band is a dupe. A rover in a new grid is a new contact. A new grid on this band is a multiplier. Points follow the VHF band table.” |
| `casual` | Casual | call + band + mode, whole log | off | none | 1 per QSO | “Not a contest. A call already in the log on this band and mode is a dupe. No multipliers.” |
| `band-mode` | Band + mode | call + band + mode, whole log | off | none until the operator turns one on | 1 per QSO | “Dupe is call + band + mode. Turn on a multiplier below if this contest has one.” |

`arrl-vhf` is the default **while N1MM is the log** and the operator has not picked another rule. It is not the solo fallback. Solo with no preset and no custom set uses section 3.6.

Mode identity is `SUBMODE` when set, else `MODE`, uppercased. FT8, FT4, and MSK144 are different modes. `MFSK` alone does not collapse them when submode is present.

**Exchange-backed rules** (ARRL Field Day section-once, state QSO party, CQ zone) are checkbox settings, not extra presets, until the log actually contains `ARRL_SECT` / `STATE` / `CQZ`. WSJT-X’s own ADIF usually has grid and mode and no section. When mult is `section` or `state` and the loaded QSOs have no exchange, Setup adds: “This multiplier needs a section or state in the log. WSJT-X’s own file does not record one, so new-mult will stay off.”

N1MM `ContestName` can **suggest** a preset. It does not override a saved choice.

| ContestName | Suggestion |
|-------------|------------|
| starts with `ARRLVHF`, or contains `VHF` | `arrl-vhf` |
| `DX`, empty | `casual` |
| anything else | keep the saved preset; Setup shows “N1MM contest {name} has no matching WIMS rule.” |

N1MM’s `ismultiplier` flag stays stored on the row. Prospective roster mults come from the active rules. For `arrl-vhf`, a logged `is_mult` still confirms grid × band the way §3.5 describes. For other presets, `is_mult` is display-only.

### 3.3 Custom checkboxes

Preset `custom`. Setup enables the controls:

| Control | Values | Effect |
|---------|--------|--------|
| Count a dupe per band | on / off | `band` in the key |
| Count a dupe per mode | on / off | `mode` in the key |
| Rover in a new grid is a new contact | on / off | `/R` adds `grid` |
| Dupe period | Whole log / UTC day | `qso_date` in the key when “UTC day” |
| Multiplier | None / Grid / State / Section | |
| Multiplier is per band | on / off | Ignored when multiplier is None |
| Points | VHF band table / Flat N (1–10) | Flat N is one number |

Call is always part of the dupe key. Saving with every dupe box off and period “whole log” means “this call once, any band” — Setup states that sentence before the save sticks. At least the summary line updates live as boxes change, before Save.

Grid mult uses the first four characters. State and section compare case-insensitively on the exchange field. A missing exchange is “not a new mult”, with the reason “no section/state in the log”.

### 3.4 Persistence

New file beside `last_log.json` (same directory rules: `$XDG_CONFIG_HOME/wims/`, else `~/.config/wims/`, Windows `%APPDATA%\wims\`). Override `WIMS_CONTEST_RULES`. **Do not** extend `last_log.json`; that file is the N1MM path.

Schema 2. `preset` set means step (a). `preset` null and `custom` set means step (b). Both null means step (c) when N1MM is not the log, and `arrl-vhf` when N1MM is.

```json
{
  "schema": 2,
  "preset": null,
  "custom": null,
  "fallback": "wsjtx-colors",
  "wsjtx_override": null,
  "gridtracker_path": ""
}
```

`fallback` is `wsjtx-colors` (section 3.6) or `gridtracker` (section 3.7). `wsjtx_override` is null when WIMS is mirroring the ini. A non-null object means the operator edited the category list in WIMS; that copy is what step (c) uses, and the label says “edited in WIMS”.

Custom example (step b; fallback unused while this is set):

```json
{
  "schema": 2,
  "preset": null,
  "custom": {
    "dupe_band": true,
    "dupe_mode": false,
    "rover_new_grid": true,
    "period": "utc-day",
    "mult": "grid",
    "mult_per_band": true,
    "points": "flat",
    "flat_points": 1
  },
  "fallback": "wsjtx-colors",
  "wsjtx_override": null,
  "gridtracker_path": ""
}
```

`POST /api/rules` writes the file and swaps the in-memory rules. The next roster build uses them. No restart.

State-contract key `rules` (sibling of `n1mm_sync`, which keeps its name):

```json
{
  "id": "wsjtx-colors",
  "title": "WSJT-X Colors",
  "source_label": "WSJT-X Colors · WSJT-X.ini",
  "n1mm_authoritative": false,
  "summary": "Needed when a CQ matches an enabled WSJT-X color: New DXCC.",
  "checks": {"new_dxcc": true, "new_dxcc_band": true, "new_grid": false,
             "new_grid_band": false, "new_call": false, "new_call_band": false,
             "highlight_by_mode": false, "only_fields": false},
  "saved_path": "/home/op/.config/wims/contest_rules.json"
}
```

### 3.5 Setup page

New **Contest rules** section on `setup.html`, above the networking checklist:

- The active-source line from section 3.0, including “N1MM is the log of record” when that applies.
- Preset `<select>`: (none), ARRL VHF, Casual, Band + mode. “(none)” clears step (a).
- Home/custom checkboxes and the points control. They are step (b). Saving them does not by itself clear a picked preset; clearing the preset is what lets the custom set take effect.
- The `summary` sentence under the controls.
- **Fallback** controls, used only at step (c): source `WSJT-X Colors` or `GridTracker roster`, the category list (section 3.6), and the GridTracker path (section 3.7).
- Save, and the path of `contest_rules.json`.
- When an N1MM contest is loaded and its name suggests a different preset, one line: “Loaded N1MM contest ARRLVHFSEP matches ARRL VHF.” or the “no matching rule” line from section 3.2.

`/n1mm` keeps picking the `.s3db`. It shows the same active-source line and links to Setup to change rules. Operate does not grow a settings form; the roster header shows `source_label`, and each row shows `need_reason`.

### 3.6 WSJT-X style needed rule

Step (c) default. This is the substitute for a contest rule when the operator has not picked one and has not saved a custom checkbox set. It answers “needed?” for a **CQ** the way WSJT-X colors a decoded CQ. The scoring strategy still excludes non-CQ rows (“not calling CQ”).

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

If the chosen file cannot be read, Setup says “GridTracker settings are not readable ({path}). Needed is using WSJT-X Colors until this file opens.” Step (c) falls back to section 3.6 rather than marking every station needed.

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
  "schema": 1,
  "primary": "auto",
  "shared_path": "",
  "overrides": {"6m": "D:/contest/6m.adi"}
}
```

`primary` is `auto` | `n1mm` | `wsjtx` | `adif`. `overrides` maps a UDP id to one ADIF file.

Do not search the network for logs. Only default data dirs, overrides, and `shared_path`.

A dead UNC path can block `Path.exists()` for a long time. Stat configured UNC paths on the poll thread; if the call exceeds about 2 seconds, mark the source unreadable and wait 30 seconds before trying again.

### 4.3 Warning copy

Shown in two places, same sentences:

1. Solo setup check (`format_report_solo`), new **Logs** section. The N1MM section stays, retitled as optional: “N1MM (optional contest log)”.
2. Setup page section **Logs**, fed by state key `log_access` (and, before any UDP, by the on-disk scan the solo check already ran).

| Situation | Severity | Sentence |
|-----------|----------|----------|
| Heard UDP id, data directory missing | warn | “WIMS hears {id} but cannot find its WSJT-X folder ({path}). Contacts from this radio will be missing from dupe checking. Set the log file under Setup → Logs.” |
| Directory exists, no `wsjtx_log.adi` yet | note | “{id} has no wsjtx_log.adi yet. WSJT-X creates that file when you log the first contact. Until then, stations on this radio look needed.” |
| Path set, open fails (share offline, permissions) | warn | “The log for {id} is not readable ({path}). If this file is on a shared drive, connect that drive. Dupe checking is incomplete.” |
| Open fails because the file is locked | warn | “WSJT-X has {path} open so WIMS cannot read it. WIMS will use contacts logged while WIMS is running, and will miss older ones.” |
| No N1MM file and no readable ADIF | warn | “No contest log and no WSJT-X log is readable. Every station will look needed.” |
| N1MM process absent, `.s3db` readable, primary is still N1MM | note | “N1MM is not running. WIMS is using the contest file {label}. Switch to WSJT-X logs under Setup → Logs if that file is the wrong log.” |
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

### 5.2 CLI and UI

```text
python -m wims.logaudit
python -m wims.logaudit --wsjtx-auto --n1mm-db "D:\N1MM Logger+\Databases\2026 Sep.s3db" --contest-nr 3
python -m wims.logaudit --adif \\server\vhf\logs\shared.adi --lotw lotw.adi --json report.json
```

No arguments: discover local WSJT-X logs and print the report. Exit 0 when every selected source opened and there are no disagreements and no “only in one source” rows. Exit 1 when any of those exist. Exit 2 when a selected path could not be read. Notes (LoTW, empty file before first QSO) do not by themselves fail the run.

UI, L7: Setup button **Check logs** calls the same function on the solo PC and renders the text report. No second layout. Operate does not host it.

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
| Only in A | No partner in the other selected sources. |
| Duplicate inside one file | Two records in the same file with the same call, band, mode, and time window. |
| Same contact in a shared file and a per-instance file | A match, not a duplicate, when both were selected on purpose. Say so in Notes. |

LoTW uses the same pairing, and an unpaired local QSO is filed under Notes, not under “Only in”. An LoTW QSO with no local partner is “Only in LoTW” (logged on another computer, or call/time outside the window).

Default window is the whole file. `--since YYYY-MM-DD` drops earlier QSOs before pairing.

The tool does not delete, merge, or rewrite any log.

### 5.4 Report format

Plain text, ASCII marks consistent with the solo check (`[OK]` `[! ]` `[XX]`). Optional `--json` writes the same structure for tests.

```text
WIMS log check
==============
Sources
  [OK] WSJT-X 6m   C:\Users\op\AppData\Local\WSJT-X - 6m\wsjtx_log.adi  (128 contacts)
  [OK] N1MM        D:\N1MM Logger+\Databases\2026 Sep.s3db  ARRLVHFSEP  (130 contacts)
  [! ] GridTracker not found — pass --gridtracker with the ADIF path

Window: all contacts

Matched: 120
Only in WSJT-X 6m: 3
Only in N1MM: 8
Disagreements: 1
Duplicates inside one file: 0

Only in WSJT-X 6m
  2026-09-12 14:02  K1ABC  6m  FT8  FN42

Only in N1MM
  2026-09-12 16:40  W1AW   6m  USB  FN31

Disagreements
  2026-09-12 15:10  W2XYZ  2m  FT8
    grid  WSJT-X FN31   N1MM FN32

Notes
  LoTW file not provided — confirmation was not checked.
```

JSON outline: `{sources, window, matched, only, disagreements, duplicates, notes}`. Each row includes `call`, `band`, `mode`, `time`, `grid`, `source`.

---

## 6. Risks

| Risk | What we do about it |
|------|---------------------|
| Extracting rules changes fleet VHF verdicts | L1’s only preset is `arrl-vhf`, delegated from today’s `is_dupe` / `is_new_mult`. Existing scoring tests must pass unchanged. N1MM primary and no operator pick ⇒ `arrl-vhf`. Solo with no preset and no custom set ⇒ WSJT-X Colors (section 3.0), which is a different verdict and must not run while N1MM is the log. |
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
| `DecodeHighlighting` is a Qt binary list | Plain bools (`HighlightByMode`, `OnlyFieldsSought`) are readable now. The category list needs a spike. Until it parses, show factory defaults and say the ini list was not read. |
| Mirroring GridTracker writes or guesses its config | Read-only open. No write, no UDP. Unknown filename or LevelDB ⇒ operator-supplied export, and WSJT-X Colors until that file reads. |
| WSJT-X Colors and a contest rule both apply | Section 3.0 picks one source. The roster label is that source. |

---

## 7. Open questions

1. **Solo default — resolved (2026-10-15).** No picked preset and no custom set ⇒ WSJT-X Colors against the ADIF log. N1MM as the log of record stays on the contest rule (`arrl-vhf` if the operator has not picked another).
2. **GridTracker filename.** Confirm on a real GT2 install (Windows and Linux) before `--gridtracker-auto` looks for a log name, and before the fallback reader looks for a settings file (section 3.7). Until then the operator passes a path.
3. **File lock.** Does WSJT-X on Windows allow a second process to read `wsjtx_log.adi` while the program is open? The locked-file warning depends on the answer.
4. **Suggest vs auto-switch** when N1MM `ContestName` maps to a preset. This proposal suggests only. Auto-switch would surprise someone who set Custom.
5. **Dupe period “contest weekend”** as a third period value (start/end timestamps) versus UTC day plus a `--since` on the audit only.
6. **Cabrillo** after the contest: in the audit tool later, or leave it to N1MM’s export?
7. **Fleet.** Seat agent reports `log_access` for WSJT-X PCs the site server cannot read. Confirm that L4 solo is enough before any agent work. The Colors ini and `wsjtx_log.adi` are on the WSJT-X PC; a remote site server cannot be the step (c) reader.
8. **General-tab master switch.** User guide §6.7 “Show DXCC, grid, and worked-before status” — confirm the ini key. Behavior until then is in section 3.6.
9. **Colors category list on the installed build.** Header `DecodeHighlightingModel` lists more rows than the six needed-categories (continent, CQ/ITU zone, LoTW). Confirm the Colors tab before coding, and do not treat those extra rows as needed unless the operator asks.

---

## 8. Milestones

Each step is shippable on its own. Tests are stdlib `tests/unit/test_*.py` plus a tiny ADIF under `tests/fixtures/logsource/`. No pytest. Fixtures stay small and synthetic.

| Id | Deliver | Done when |
|----|---------|-----------|
| **L1** | `ContestRules` + preset `arrl-vhf`. `LogStore.is_dupe` / `is_new_mult` delegate to it. | Existing scoring, roster, and N1MM log tests pass with no verdict change. New tests call the rules object directly. |
| **L2** | `contest_rules.json` (schema 2), `POST /api/rules`, state key `rules` including `source_label`. Setup shows which source is active (section 3.0). | N1MM primary and no pick ⇒ `N1MM · ARRL VHF`. Solo with no preset and no custom set ⇒ `WSJT-X Colors` (categories may still be defaults until L3 reads the ini). A picked preset beats a saved custom set. |
| **L3** | Steps (a) and (b): presets `casual` and `band-mode`, custom checkboxes, `need_reason` / `mult_reason`. Step (c): WSJT-X Colors rule against an ADIF fixture, including Highlight by Mode and Only grid Fields sought. Read `HighlightByMode` and `OnlyFieldsSought` from an ini fixture. Spike `DecodeHighlighting`; if it does not parse, say so and use factory defaults. | A unit test: New Call on Band is needed; the same call already on that band and mode is not; a two-letter field match honors Only grid Fields sought. The Operate row shows the category name. N1MM-primary tests still expect `arrl-vhf`. |
| **L4** | Discover per-instance and shared paths. Warnings in the solo check and on Setup (`log_access`). | A fixture directory tree (default + `--rig-name` + missing dir + shared symlink) produces the sentences in section 4.3. `LogStore` still unchanged. |
| **L5** | `WsjtxAdifLogSource` + `adif_drop`. Solo auto-pick (section 2.2). Poll + UDP fast path, one id function. | With no N1MM file, a sample `wsjtx_log.adi` seeds dupes. Appending one record flips that call to a dupe. N1MM seed still works when `last_log.json` points at a `.s3db`. |
| **L6** | `python -m wims.logaudit` for WSJT-X, N1MM, and generic ADIF. Text + JSON. | A fixture pair with one missing QSO, one grid clash, and one match exits 1 and prints the section 5.4 shape. Read-only. |
| **L7** | GridTracker path spike, then `--gridtracker-auto`. LoTW file as notes. Setup **Check logs** renders the L6 report. | A GT sample ADIF and a LoTW sample produce notes, and an unpaired LoTW-only row is not a hard “missing from WSJT-X” failure. |
| **L8** | More loggers as `--adif` documentation and, only after a survey spike, one native reader (Log4OM SQLite or CQRLOG). | The spike checklist in the survey is filled in for that one program before any SQL is merged. |
| **L9** | GridTracker roster as the step (c) alternative (section 3.7). Read-only. | A fixture JSON (once the spike names the file and keys) selects “new grid” and a CQ in a logged grid is not needed. Missing file ⇒ WSJT-X Colors, with the Setup sentence in section 3.7. No GridTracker file is written. |

L1 does not require a logger change. L2 can ship the source label before L3 fills in Colors parsing. L4 does not require rules beyond L1. L9 waits on the section 3.7 spike and can share the ADIF reader with L5. L6 can start as soon as that reader exists; it can also carry its own small reader if L5 slips, as long as the id and field rules match section 2.3.
