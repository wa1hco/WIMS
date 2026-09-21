# WIMS log-source survey (Windows / Linux)

**Status:** planning survey for standalone Operate  
**Date:** 2026-09-19  
**Style:** STE Lite  
**Related:** design §3.6 / §3.10; Operate log-source plan; `docs/home_h0_h1.md`

## 1. Why this survey

Standalone Operate must **read** a user-selected logger and detect new QSOs.  
WIMS keeps a local `LogStore` copy for needed / ranking.  
WIMS does **not** write the external logger.

This document ranks popular log programs by:

1. How the log is stored  
2. How a new contact becomes visible on disk or on the wire  
3. Fit for a `LogSource` backend

## 2. Detection tiers (WIMS)

| Tier | Mechanism | Latency | Complexity |
|------|-----------|---------|------------|
| **T1 Event** | UDP / API / change table | Low | Medium |
| **T2 Append ADIF** | Tail or poll an append-only `.adi` | Low–medium | Low |
| **T3 SQLite poll** | mtime + new rows / keys | Medium | Medium |
| **T4 SQL poll** | MySQL/MariaDB `MAX(id)` or change log | Medium | Medium + DSN |
| **T5 ADIF drop** | Watch a configured export / backup `.adi` | High unless auto | Low |

**Rule:** ship **T1 + T2** first. Add T3/T4 after a spike. Use **T5** for unknown or Access-based loggers.

## 3. Contenders

| Program | OS | Role | Typical storage | Best WIMS path |
|---------|----|------|-----------------|----------------|
| **N1MM+** | Windows | Contest | SQLite `.s3db` | **T1** Broadcast + DB seed (exists) |
| **WSJT-X** | Win / Linux | Digi log | `wsjtx_log.adi` | **T2** append watch |
| **Log4OM v2** | Windows | General | SQLite or MariaDB | **T3/T4** after schema spike |
| **CQRLOG** | Linux | General / awards | MySQL/MariaDB | **T4** (`log_changes`) |
| **QLog** | Win / Linux | General | SQLite | **T3** after spike |
| **KLog** | Win / Linux / macOS | General | SQLite (typical) | **T3** after spike |
| **Ham Radio Deluxe** | Windows | All-in-one | SQLite (modern) / Access | **T3** or **T5** |
| **DXKeeper** | Windows | Awards / DX | Access `.mdb` | **T5** ADIF drop |
| **N3FJP AC Log** | Windows | General / clubs | Access `.mdb` | **T5** ADIF drop |
| **Logger32** | Windows | Awards | Proprietary + ADIF | **T5** ADIF drop |
| **DXLog.net** | Windows | Contest | Contest files | Later contest peer; ADIF out |
| **Wavelog / Cloudlog** | Web | Network log | MySQL + API | Later network source |
| **HAMRS / Ham2K** | Multi | POTA / portable | App DB + ADIF | **T5** / sync later |
| **Not1MM / TLF** | Linux | Contest | Contest-specific | Niche; ADIF/Cabrillo |

## 4. Storage families

| Family | Examples | Seed | Live |
|--------|----------|------|------|
| **A Event stream** | N1MM Broadcast | `.s3db` | UDP add / replace / delete |
| **B Append ADIF** | WSJT-X | Full parse | New bytes / new `<EOR>` |
| **C SQLite** | Log4OM, QLog, HRD | SQL → `LoggedQso` | New keys after mtime |
| **D MySQL/MariaDB** | CQRLOG, optional Log4OM | SQL | Change table or `MAX(id)` |
| **E Access `.mdb`** | N3FJP, DXKeeper, old HRD | ODBC/mdbtools or ADIF | Prefer **T5** |
| **F ADIF drop** | Any logger | Import file | Watch export path |

## 5. Per-program notes

### 5.1 N1MM+ (Windows) — implemented

- **DB:** contest `.s3db`, DXLOG rows, contest filter by `ContestNR`.
- **Live:** UDP 12060 `<contactinfo>` / `<contactreplace>` / `<contactdelete>`.
- **IDs:** stable → reconcile works.
- **Manual QSOs:** yes.
- **Action:** wrap as first `LogSource` (behavior unchanged).

### 5.2 WSJT-X (Windows / Linux)

- **Files:** `wsjtx_log.adi` (ADIF) and `wsjtx.log` (CSV).  
  - Windows: `%LOCALAPPDATA%\WSJT-X\` and `WSJT-X - <rig>\` for `--rig-name`.  
  - Linux: use **File → Open log directory** (often under `~/.local/share/WSJT-X/`).
- **Update:** append one ADIF record when a QSO is logged.
- **Detect:** poll mtime/size; parse appended records; synthetic id from call+band+date+time+mode.
- **Manual QSOs:** digi only.
- **Action:** second backend; H0 path without N1MM.

### 5.3 Log4OM v2 (Windows)

- **DB:** user-chosen SQLite path (shown in UI); optional MariaDB/MySQL.
- **ADIF backups:** useful for recovery; often on close — **not** a live feed.
- **Detect:** read-only SQLite; poll new rows (schema spike required).
- **Risk:** writer lock / WAL while Log4OM is open.
- **Manual QSOs:** yes; digi via JTx / UDP into Log4OM.
- **Action:** candidate after N1MM + WSJT; Windows VM spike.

### 5.4 CQRLOG (Linux)

- **DB:** embedded or server MySQL; default data under `~/.config/cqrlog/`.
- **Tables:** `cqrlog_main` (QSOs); **`log_changes`** (insert/update/delete commands).
- **Detect:** seed from `cqrlog_main`; live poll `log_changes` by id.
- **Manual QSOs:** yes; awards-oriented.
- **Action:** best Linux-native candidate after WSJT ADIF.

### 5.5 Ham Radio Deluxe Logbook (Windows)

- **DB:** modern SQLite; older installs may use Access `.mdb`.
- **UDP:** HRD **receives** digi/contest logs — inbound to HRD, not a WIMS output.
- **Detect:** SQLite poll if path known; else ADIF export watch.
- **Action:** only if users need it; do not reverse HRD UDP.

### 5.6 DXKeeper (Windows)

- **DB:** Access `.mdb` (e.g. `Databases\<call>.mdb`).
- **Detect:** prefer operator ADIF export → **T5** watch.
- **Action:** no Jet/Access dependency in v1.

### 5.7 N3FJP AC Log (Windows)

- **DB:** Access `LogData.mdb` (often under Documents / Affirmatech paths).
- **Detect:** ADIF import/export → **T5**.
- **Action:** same as DXKeeper.

### 5.8 Logger32 (Windows)

- Strong ADIF import/export workflow; proprietary store.
- **Action:** **T5** ADIF drop.

### 5.9 DXLog.net (Windows)

- Contest logger; ADIF/Cabrillo export.
- Not a home master-log target for v1.
- Later: contest peer similar to N1MM if needed.

### 5.10 QLog / KLog

- SQLite + ADIF; cross-platform.
- **Action:** T3 after schema spike; lower priority than CQRLOG/Log4OM.

### 5.11 Wavelog / Cloudlog

- Server SQL + HTTP API.
- **Action:** later network `LogSource`; out of local-file v1.

## 6. Backend priority for Operate

| Priority | Backend | Tier | Why |
|----------|---------|------|-----|
| 1 | N1MM | T1 | Exists; contest + manual |
| 2 | WSJT-X ADIF | T2 | H0 without external logger |
| 3 | Generic ADIF drop | T5 | Escape hatch for “other” |
| 4 | CQRLOG | T4 | Linux change table |
| 5 | Log4OM SQLite | T3 | Popular Windows general log |
| later | HRD / QLog / KLog | T3 | After spikes |
| later | DXKeeper / N3FJP | T5 | Avoid Access in-process |

One **primary** source at a time (no merge of two live feeds in v1).

## 7. Spike checklist (per adapter)

Before coding a native backend:

1. Obtain a sample DB or ADIF (real station or fixture).
2. Document path discovery on Windows and Linux.
3. Map fields → `LoggedQso` (call, band, grid, mode, time, id).
4. Prove one new QSO appears within a bound (target ≤2 s).
5. Prove edit/delete if supported; else mark append-only.
6. Note locking / WAL / concurrent open behavior.
7. Confirm manual SSB/CW entry exists in that logger.

## 8. Fixtures to collect

| Fixture | Purpose |
|---------|---------|
| Small `wsjtx_log.adi` | Parse + append-watch tests |
| N1MM `.s3db` snippet / existing tests | Regression |
| Optional Log4OM SQLite sample | T3 spike |
| Optional CQRLOG dump or `log_changes` rows | T4 spike |
| Hand-made ADIF drop file | T5 tests |

Keep fixtures under `tests/fixtures/logsource/` when added.  
Do not commit large personal logs.

## 9. Open choices

1. H0 auto-pick order: N1MM → WSJT ADIF → none?
2. Watch all WSJT `--rig-name` ADIF files, or one path?
3. First native after WSJT: **CQRLOG** (Linux) or **Log4OM** (Windows VM)?
4. Keep “other logger” as ADIF drop only for a long time?

## 10. Next implementation step

1. `LogSource` protocol + N1MM adapter (no behavior change).  
2. `WsjtxAdifLogSource` seed + poll.  
3. Generic ADIF drop source + Setup selection.  
4. Then one native spike (CQRLOG or Log4OM).
