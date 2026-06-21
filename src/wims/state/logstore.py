"""WIMS's own log copy + dupe/mult view (plan §3.10).

This is WIMS's database — a SQLite file (`wims.db` by default, or `:memory:` for
tests), the materialized view the decision engine queries. It is **seeded** from
N1MM's `.s3db` (read-only) and kept **live** by `<contactinfo>` broadcasts; an
operator **resync** is `reconcile()` over a fresh DB read. WIMS only ever writes
this database, never N1MM's.

VHF dupe/mult model: a QSO is a dupe of an earlier one with the same
`(call, band, grid)` — so a rover in a *new* grid is not a dupe. A multiplier is a
`grid x band` worked for the first time. N1MM's `is_mult` flag rides along to
calibrate/confirm.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from wims.integrations.n1mm.qso import LoggedQso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qsos (
    id        TEXT PRIMARY KEY,
    call      TEXT NOT NULL,
    band      TEXT NOT NULL,
    grid      TEXT,
    mode      TEXT,
    points    INTEGER DEFAULT 0,
    is_mult   INTEGER DEFAULT 0,
    contest   TEXT,
    timestamp TEXT,
    operator  TEXT,
    rover     TEXT,
    source    TEXT
);
CREATE INDEX IF NOT EXISTS ix_qsos_cbg  ON qsos (call, band, grid);
CREATE INDEX IF NOT EXISTS ix_qsos_grid ON qsos (band, grid);
"""


class LogStore:
    def __init__(self, path: str = "wims.db"):
        # check_same_thread=False so the WIMS server can share one connection across
        # its ingest + HTTP threads; callers must serialize access (the server does,
        # via its own lock). Single-threaded users (tests, CLIs) are unaffected.
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        if path != ":memory:":
            self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(_SCHEMA)
        self.con.commit()

    # -- mutations ---------------------------------------------------------- #

    def upsert(self, q: LoggedQso) -> None:
        self.con.execute(
            """INSERT INTO qsos
                 (id, call, band, grid, mode, points, is_mult, contest,
                  timestamp, operator, rover, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 call=excluded.call, band=excluded.band, grid=excluded.grid,
                 mode=excluded.mode, points=excluded.points,
                 is_mult=excluded.is_mult, contest=excluded.contest,
                 timestamp=excluded.timestamp, operator=excluded.operator,
                 rover=excluded.rover, source=excluded.source""",
            (q.id, q.call, q.band, q.grid, q.mode, q.points, int(q.is_mult),
             q.contest, q.timestamp, q.operator, q.rover_location, q.source),
        )
        self.con.commit()

    def delete(self, qso_id: str) -> None:
        self.con.execute("DELETE FROM qsos WHERE id=?", (qso_id,))
        self.con.commit()

    def reconcile(self, qsos: Iterable[LoggedQso]) -> dict:
        """Operator resync / cold-start: make the store match a full DB read.

        Upserts everything present and deletes rows whose ID is no longer in the
        source (i.e. QSOs deleted in N1MM). Returns a small change summary.
        """
        qsos = list(qsos)
        incoming = {q.id for q in qsos}
        existing = {r["id"] for r in self.con.execute("SELECT id FROM qsos")}
        for q in qsos:
            self.upsert(q)
        removed = existing - incoming
        for qid in removed:
            self.delete(qid)
        return {"upserted": len(qsos), "deleted": len(removed),
                "total": self.count()}

    # -- queries ------------------------------------------------------------ #

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM qsos").fetchone()[0]

    def is_dupe(self, call: str, band: str, grid: str | None) -> bool:
        """Already worked this call on this band (same grid, for rovers)?

        With a known grid the match is `(call, band, grid)` so a rover in a new
        grid is *not* a dupe. Without a grid it falls back to `(call, band)`.
        """
        call = call.upper()
        if grid:
            row = self.con.execute(
                "SELECT 1 FROM qsos WHERE call=? AND band=? AND grid=? LIMIT 1",
                (call, band, grid.upper()),
            ).fetchone()
        else:
            row = self.con.execute(
                "SELECT 1 FROM qsos WHERE call=? AND band=? LIMIT 1",
                (call, band),
            ).fetchone()
        return row is not None

    def is_new_mult(self, grid: str | None, band: str) -> bool:
        """Would a station in this grid be a new multiplier on this band?

        VHF mult = grid x band. New iff no QSO yet exists with that grid+band.
        """
        if not grid:
            return False
        row = self.con.execute(
            "SELECT 1 FROM qsos WHERE band=? AND grid=? LIMIT 1",
            (band, grid.upper()),
        ).fetchone()
        return row is None

    def worked_grids(self, band: str) -> set[str]:
        return {r["grid"] for r in self.con.execute(
            "SELECT DISTINCT grid FROM qsos WHERE band=? AND grid IS NOT NULL",
            (band,))}

    def close(self) -> None:
        self.con.close()
