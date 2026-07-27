# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Read N1MM's contest log DB read-only — cold-start seed and operator resync (§3.6).

The same read serves two purposes:
  * **Seed** the log copy at startup with QSOs made before WIMS was running.
  * **Resync** on demand (operator says "WIMS, refresh from N1MM" after manual
    edits/deletions, or after a broadcast outage / dropped UDP). A resync is just a
    re-read + reconcile by `ID` (LogStore.reconcile) — authoritative, and it does
    not depend on any N1MM re-broadcast feature.

One `.s3db` can hold **multiple** contest logs (`ContestInstance` + `DXLOG.ContestNR`).
WIMS must not blindly load every QSO in the file (June VHF + Sept VHF + …). Operators
should not need cryptic ContestNR flags: we **list** human-readable contests, **auto-pick**
the best candidate, and let the Status UI override.

Always opened read-only (`mode=ro`); WIMS never writes N1MM's database. Reading
while N1MM has the DB open is safe (proven for the Settings table).
"""

from __future__ import annotations

import glob
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from wims.integrations.n1mm.qso import LoggedQso

# N1MM's app-wide DBs that are not the contest log.
_NON_CONTEST = ("admin", "dxlog", "packet spots")

# ContestInstance rows that are not real operating logs.
_SKIP_NAMES = frozenset({"deletedqs", "dx"})


def _win_n1mm_user_dir() -> Path | None:
    """N1MM Logger+ UserDir from HKCU (where Databases / ini often live).

    Many installs do **not** use Documents\\N1MM Logger+\\Databases — they set
    UserDir in the registry (e.g. C:\\Users\\… so Databases is C:\\Users\\…\\Databases).
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    for key_path in (
        r"Software\N1MM Logger+",
        r"Software\N1MM Logger",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                val, _ = winreg.QueryValueEx(k, "UserDir")
            if val:
                p = Path(str(val))
                if p.is_dir():
                    return p
        except OSError:
            continue
    return None


def candidate_database_dirs(*, extra: str | Path | None = None) -> list[Path]:
    """All N1MM Databases folders that exist on this host (seed / rescan).

    Order: explicit extra dir, registry UserDir\\Databases, then Documents /
    OneDrive / profile Databases variants. Same idea as the seat-agent probe —
    N1MM can see wa1hco.s3db while Documents\\N1MM Logger+\\Databases is empty.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            if not p.is_dir():
                return
            rp = p.resolve()
        except OSError:
            return
        if rp in seen:
            return
        seen.add(rp)
        found.append(p)

    if extra:
        add(Path(extra))

    ud = _win_n1mm_user_dir()
    if ud is not None:
        add(ud / "Databases")

    home = Path.home()
    add(home / "Databases")  # common when UserDir is the profile root
    for name in ("N1MM Logger+", "N1MM Logger", "N1MMLogger+"):
        add(home / "Documents" / name / "Databases")
        add(home / "OneDrive" / "Documents" / name / "Databases")

    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if not base:
            continue
        bp = Path(base)
        add(bp / "Databases")
        for name in ("N1MM Logger+", "N1MM Logger"):
            add(bp / "Documents" / name / "Databases")
            add(bp / "OneDrive" / "Documents" / name / "Databases")

    return found


def standard_database_dirs() -> list[Path]:
    """Alias: candidate N1MM Databases folders (no extra path)."""
    return candidate_database_dirs()


def default_seed_db_dir() -> str:
    """CLI default for ``--seed-db-dir``: first existing standard root, or Documents path."""
    dirs = candidate_database_dirs()
    if dirs:
        return str(dirs[0])
    return str(Path.home() / "Documents" / "N1MM Logger+" / "Databases")


@dataclass
class ContestInfo:
    """One selectable contest log inside an N1MM .s3db (what N1MM's Open Log lists)."""

    contest_nr: int
    contest_name: str
    start_date: str | None
    qso_count: int
    db_path: str
    db_label: str            # basename for UI
    recommended: bool = False

    def label(self) -> str:
        """Human line for UI / logs — no ContestNR required to understand it."""
        when = (self.start_date or "").strip()
        if when.startswith("1900"):
            when = ""
        parts = [self.contest_name or f"Contest #{self.contest_nr}"]
        if when:
            parts.append(when[:10])  # date only
        parts.append(f"{self.qso_count} QSOs")
        return " · ".join(parts)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label()
        return d


def find_contest_db(databases_dir: str) -> str | None:
    """Best-effort: the contest log is the .s3db with a DXLOG table that isn't one
    of N1MM's app-wide databases. Pass the explicit path if this guesses wrong."""
    dbs = find_contest_dbs(databases_dir)
    return dbs[0] if dbs else None


def find_contest_dbs(databases_dir: str | None = None,
                     *, also_standard: bool = False) -> list[str]:
    """All candidate contest .s3db files under one or more Databases folders.

    When ``also_standard=True`` (or ``databases_dir`` is None), also scans every
    path from :func:`candidate_database_dirs` (registry UserDir, Documents,
    OneDrive, profile Databases). Explicit single-dir lookups leave
    ``also_standard`` off to stay narrow.
    """
    search_roots: list[Path] = []
    seen_roots: set[Path] = set()

    def add_root(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp in seen_roots:
            return
        if not p.is_dir():
            return
        seen_roots.add(rp)
        search_roots.append(p)

    if databases_dir:
        add_root(Path(databases_dir))
    if also_standard or not databases_dir:
        for d in candidate_database_dirs(extra=None):
            add_root(d)

    found: list[str] = []
    seen: set[Path] = set()
    for base in search_roots:
        for path in sorted(glob.glob(str(base / "*.s3db"))):
            p = Path(path)
            try:
                rp = p.resolve()
            except OSError:
                rp = p
            if rp in seen:
                continue
            name = p.stem.lower()
            if any(n in name for n in _NON_CONTEST):
                continue
            try:
                con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                has = con.execute(
                    "select 1 from sqlite_master where type='table' and name='DXLOG'"
                ).fetchone()
                con.close()
                if has:
                    seen.add(rp)
                    found.append(str(p))
            except sqlite3.Error:
                continue
    return found


def list_contests(db_path: str) -> list[ContestInfo]:
    """Contests inside one .s3db with QSO counts (N1MM Open Log list)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        label = Path(db_path).name
        dx_cols = {r[1] for r in con.execute("pragma table_info(DXLOG)")}
        has_nr = "ContestNR" in dx_cols
        has_ci = con.execute(
            "select 1 from sqlite_master where type='table' and name='ContestInstance'"
        ).fetchone()
        out: list[ContestInfo] = []
        if has_ci and has_nr:
            rows = con.execute(
                """
                SELECT ci.ContestNR AS nr,
                       ci.ContestName AS name,
                       ci.StartDate AS start,
                       (SELECT COUNT(*) FROM DXLOG d
                          WHERE d.ContestNR = ci.ContestNR) AS n
                FROM ContestInstance ci
                ORDER BY ci.StartDate DESC, ci.ContestNR DESC
                """
            ).fetchall()
            for r in rows:
                nr = int(r["nr"] if r["nr"] is not None else -999)
                name = (r["name"] or "").strip() or f"#{nr}"
                if name.lower() in _SKIP_NAMES and int(r["n"] or 0) == 0:
                    continue
                out.append(ContestInfo(
                    contest_nr=nr,
                    contest_name=name,
                    start_date=(r["start"] or None),
                    qso_count=int(r["n"] or 0),
                    db_path=db_path,
                    db_label=label,
                ))
        if has_nr:
            seen_nr = {c.contest_nr for c in out}
            for r in con.execute(
                """
                SELECT ContestNR AS nr, ContestName AS name, COUNT(*) AS n
                FROM DXLOG
                GROUP BY ContestNR, ContestName
                ORDER BY n DESC
                """
            ):
                nr = int(r["nr"] if r["nr"] is not None else -999)
                if nr in seen_nr:
                    continue
                name = (r["name"] or "").strip() or f"#{nr}"
                if name.lower() in _SKIP_NAMES and int(r["n"] or 0) == 0:
                    continue
                out.append(ContestInfo(
                    contest_nr=nr,
                    contest_name=name,
                    start_date=None,
                    qso_count=int(r["n"] or 0),
                    db_path=db_path,
                    db_label=label,
                ))
        if not out:
            # Single-blob / minimal test DBs: treat whole DXLOG as one contest.
            n = con.execute("SELECT COUNT(*) FROM DXLOG").fetchone()[0]
            name_row = None
            if "ContestName" in dx_cols:
                name_row = con.execute(
                    "SELECT ContestName FROM DXLOG WHERE ContestName IS NOT NULL "
                    "AND ContestName != '' LIMIT 1"
                ).fetchone()
            out.append(ContestInfo(
                contest_nr=0,
                contest_name=(name_row[0] if name_row else "ALL"),
                start_date=None,
                qso_count=int(n or 0),
                db_path=db_path,
                db_label=label,
            ))
        return out
    finally:
        con.close()


def list_all_contests(databases_dir: str | None = None,
                      db_path: str | None = None) -> list[ContestInfo]:
    """All contests from one explicit DB and/or every DB under scan roots.

    Always multi-path (UserDir + Documents + …) so same-VM N1MM logs are found
    even when Documents\\N1MM Logger+\\Databases is empty or missing.
    """
    paths: list[str] = []
    if db_path and Path(db_path).is_file():
        paths.append(db_path)
    for p in find_contest_dbs(databases_dir, also_standard=True):
        if p not in paths:
            paths.append(p)
    out: list[ContestInfo] = []
    for p in paths:
        try:
            out.extend(list_contests(p))
        except sqlite3.Error:
            continue
    return out


def pick_contest(contests: list[ContestInfo]) -> ContestInfo | None:
    """Auto-select without operator knowing ContestNR or IPs.

    Prefer the contest with QSOs that has the **latest StartDate**; if dates are
    missing/useless, prefer the largest QSO count. Skip empty placeholder rows.
    """
    usable = [c for c in contests if c.qso_count > 0
              and c.contest_name.lower() not in _SKIP_NAMES]
    if not usable:
        usable = [c for c in contests if c.qso_count > 0]
    if not usable:
        return None

    def sort_key(c: ContestInfo):
        sd = (c.start_date or "").strip()
        # 1900-01-01 placeholders sort last
        if not sd or sd.startswith("1900"):
            sd = ""
        return (sd, c.qso_count, c.contest_nr)

    return max(usable, key=sort_key)


def read_dxlog(db_path: str, *, contest_nr: int | None = None,
               contest_name: str | None = None) -> list[LoggedQso]:
    """Read DXLOG rows read-only into LoggedQso records (seed/resync).

    If `contest_nr` is set, only that contest instance is loaded (required when the
    .s3db holds June VHF + Sept VHF + …). `contest_name` is a fallback filter.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if contest_nr is not None:
            rows = con.execute(
                "SELECT * FROM DXLOG WHERE ContestNR=?", (contest_nr,)
            ).fetchall()
        elif contest_name:
            rows = con.execute(
                "SELECT * FROM DXLOG WHERE ContestName=?", (contest_name,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM DXLOG").fetchall()
    finally:
        con.close()
    return [LoggedQso.from_dxlog_row(dict(r)) for r in rows]


def discover(databases_dir: str | None = None,
             db_path: str | None = None) -> dict:
    """Full discovery payload for Status UI / startup: contests + recommendation."""
    scan_dirs = [str(p) for p in candidate_database_dirs(extra=databases_dir)]
    contests = list_all_contests(databases_dir, db_path)
    choice = pick_contest(contests)
    for c in contests:
        c.recommended = (choice is not None
                         and c.contest_nr == choice.contest_nr
                         and c.db_path == choice.db_path)
    return {
        "contests": [c.to_dict() for c in contests],
        "recommended": choice.to_dict() if choice else None,
        "db_paths": sorted({c.db_path for c in contests}),
        "scan_dirs": scan_dirs,
    }
