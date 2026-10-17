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

"""WIMS's own log copy + dupe/mult view (plan §3.10).

This is WIMS's database — a SQLite file (`wims.db` by default, or `:memory:` for
tests), the materialized view the decision engine queries. It is **seeded** from
N1MM's `.s3db` (read-only) and kept **live** by N1MM contact UDP (`<contactinfo>`
add, `<contactreplace>` edit, `<contactdelete>` delete); an operator **resync**
is `reconcile()` over a fresh DB read. WIMS only ever writes this database, never
N1MM's.

VHF dupe/mult model (N1MM / ARRL VHF): a **fixed** station is a dupe on
`(call, band)` — grid does not reopen the QSO (wrong logged grid, or they
send a different square). A **rover** (`/R` in the call) may be worked again
in a new grid, so the key is `(call, band, grid)`. A multiplier is a
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
    source    TEXT,
    submode   TEXT,
    qso_date  TEXT,
    time_on   TEXT,
    exchange  TEXT,
    state     TEXT,
    my_state  TEXT,
    my_county TEXT,
    dxcc      TEXT,
    contest_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_qsos_cbg  ON qsos (call, band, grid);
CREATE INDEX IF NOT EXISTS ix_qsos_grid ON qsos (band, grid);
"""

# Older wims.db files predate the ADIF columns. CREATE IF NOT EXISTS will not add them.
_EXTRA_COLUMNS = (
    ("submode", "TEXT"),
    ("qso_date", "TEXT"),
    ("time_on", "TEXT"),
    ("exchange", "TEXT"),
    ("state", "TEXT"),
    ("my_state", "TEXT"),
    ("my_county", "TEXT"),
    ("dxcc", "TEXT"),
    ("contest_id", "TEXT"),
)


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
        self._ensure_columns()
        self.con.commit()
        # Fleet default is ARRL VHF so existing dupe/mult tests stay put.
        # Solo attaches a different rules object after startup, not in __init__.
        from wims.engine.contest_rules import load_builtin
        self.rules = load_builtin("arrl-vhf")
        self.station_state = ""
        self.station_county = ""
        self._gen = 0
        self._row_cache = None
        self._row_gen = -1

    def _ensure_columns(self) -> None:
        have = {row[1] for row in self.con.execute("PRAGMA table_info(qsos)")}
        for name, typ in _EXTRA_COLUMNS:
            if name not in have:
                self.con.execute(f"ALTER TABLE qsos ADD COLUMN {name} {typ}")

    def _touch(self) -> None:
        self._gen = getattr(self, "_gen", 0) + 1

    def generation(self) -> int:
        return getattr(self, "_gen", 0)

    def cached_rows(self) -> list[dict]:
        gen = self.generation()
        if self._row_cache is None or self._row_gen != gen:
            self._row_cache = [dict(row) for row in self.con.execute("SELECT * FROM qsos")]
            self._row_gen = gen
        return self._row_cache

    # -- mutations ---------------------------------------------------------- #

    def upsert(self, q: LoggedQso) -> None:
        self.con.execute(
            """INSERT INTO qsos
                 (id, call, band, grid, mode, points, is_mult, contest,
                  timestamp, operator, rover, source,
                  submode, qso_date, time_on, exchange, state, my_state,
                  my_county, dxcc, contest_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 call=excluded.call, band=excluded.band, grid=excluded.grid,
                 mode=excluded.mode, points=excluded.points,
                 is_mult=excluded.is_mult, contest=excluded.contest,
                 timestamp=excluded.timestamp, operator=excluded.operator,
                 rover=excluded.rover, source=excluded.source,
                 submode=excluded.submode, qso_date=excluded.qso_date,
                 time_on=excluded.time_on, exchange=excluded.exchange,
                 state=excluded.state, my_state=excluded.my_state,
                 my_county=excluded.my_county, dxcc=excluded.dxcc,
                 contest_id=excluded.contest_id""",
            (q.id, q.call, q.band, q.grid, q.mode, q.points, int(q.is_mult),
             q.contest, q.timestamp, q.operator, q.rover_location, q.source,
             q.submode, q.qso_date, q.time_on, q.exchange, q.state, q.my_state,
             q.my_county, q.dxcc, q.contest_id),
        )
        self._touch()
        self.con.commit()

    def delete(self, qso_id: str) -> None:
        self.con.execute("DELETE FROM qsos WHERE id=?", (qso_id,))
        self._touch()
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

    def classify(self, call: str, band: str, grid: str | None = None,
                 mode: str | None = None, *, my_county: str | None = None,
                 exchange: str | None = None, state: str | None = None):
        """Dupe, mult, points, and the plain reasons for the active rules file."""
        from wims.engine.contest_rules import Verdict
        call_u = (call or "").upper()
        grid_n = (str(grid).strip().upper() if grid else None) or None
        county = self.station_county if my_county is None else my_county
        rules = getattr(self, "rules", None)
        if rules is None:
            return Verdict(
                is_dupe=False, is_new_mult=False, points=0,
            )
        return rules.classify(
            self, call_u, band, mode, grid_n,
            exchange=exchange, my_county=county, state=state,
        )

    def is_dupe(self, call: str, band: str, grid: str | None = None,
                mode: str | None = None, my_county: str | None = None) -> bool:
        """Already worked under the active contest rules?

        The default rules file is ARRL VHF: fixed station ``(call, band)``,
        rover ``/R`` adds grid. Other contests replace ``self.rules``.
        """
        return bool(self.classify(
            call, band, grid, mode, my_county=my_county,
        ).is_dupe)

    def is_new_mult(self, grid: str | None, band: str, call: str = "",
                    mode: str | None = None, exchange: str | None = None) -> bool:
        """New multiplier under the active rules. ARRL VHF is grid x band."""
        return bool(self.classify(
            call, band, grid, mode, exchange=exchange,
        ).is_new_mult)

    def worked_grids(self, band: str) -> set[str]:
        return {r["grid"] for r in self.con.execute(
            "SELECT DISTINCT grid FROM qsos WHERE band=? AND grid IS NOT NULL",
            (band,))}

    def close(self) -> None:
        self.con.close()
