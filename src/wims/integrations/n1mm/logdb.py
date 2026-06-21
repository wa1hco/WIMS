"""Read N1MM's contest log DB read-only — cold-start seed and operator resync (§3.6).

The same read serves two purposes:
  * **Seed** the log copy at startup with QSOs made before WIMS was running.
  * **Resync** on demand (operator says "WIMS, refresh from N1MM" after manual
    edits/deletions, or after a broadcast outage / dropped UDP). A resync is just a
    re-read + reconcile by `ID` (LogStore.reconcile) — authoritative, and it does
    not depend on any N1MM re-broadcast feature.

Always opened read-only (`mode=ro`); WIMS never writes N1MM's database. Reading
while N1MM has the DB open is safe (proven for the Settings table).
"""

from __future__ import annotations

import glob
import sqlite3
from pathlib import Path

from wims.integrations.n1mm.qso import LoggedQso

# N1MM's app-wide DBs that are not the contest log.
_NON_CONTEST = ("admin", "dxlog", "packet spots")


def find_contest_db(databases_dir: str) -> str | None:
    """Best-effort: the contest log is the .s3db with a DXLOG table that isn't one
    of N1MM's app-wide databases. Pass the explicit path if this guesses wrong."""
    for path in sorted(glob.glob(str(Path(databases_dir) / "*.s3db"))):
        name = Path(path).stem.lower()
        if any(n in name for n in _NON_CONTEST):
            continue
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            has = con.execute(
                "select 1 from sqlite_master where type='table' and name='DXLOG'"
            ).fetchone()
            con.close()
            if has:
                return path
        except sqlite3.Error:
            continue
    return None


def read_dxlog(db_path: str) -> list[LoggedQso]:
    """Read all DXLOG rows read-only into LoggedQso records (seed/resync)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select * from DXLOG").fetchall()
    finally:
        con.close()
    return [LoggedQso.from_dxlog_row(dict(r)) for r in rows]
