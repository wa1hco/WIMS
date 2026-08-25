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

"""Solo tester path: a casual (non-contest, HF) N1MM log seeds and drives the
needed<->dupe roster flip testers use to verify the algorithm (release P0).

The casual log lives under N1MM's default "DX" contest — a `_SKIP_NAMES` name that
`pick_contest`'s fallback must still rescue. N1MM stores `DXLOG.Band` as the MHz edge
("14" = 20m), which `_band` normalizes to the same label the roster derives from the
WSJT-X dial ("20m"), so dupe matching lines up on HF."""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.server.app import LiveFleet  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402

MID = "RIG-20M"
QID = "x" + "0" * 31


def _casual_db() -> str:
    """One 20m FT8 QSO (K1ABC) logged under the default 'DX' contest."""
    fd, db = tempfile.mkstemp(suffix=".s3db")
    os.close(fd)
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE ContestInstance (ContestID INT, ContestName TEXT, StartDate TEXT, ContestNR INT);
      CREATE TABLE DXLOG (ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, Mode TEXT,
        Points INT, IsMultiplier1 INT, ContestName TEXT, ContestNR INT, TimeStamp TEXT, Operator TEXT);
    """)
    con.execute("INSERT INTO ContestInstance VALUES (1,'DX','2026-07-19',5)")
    con.execute("INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (QID, "K1ABC", "14", "FN31", "FT8", 1, 0, "DX", 5, "2026-07-19", "WA1HCO"))
    con.commit()
    con.close()
    return db


def _needed(live) -> dict:
    rows = live.snapshot(time.time())["roster"]["candidates"]
    return {r["call"]: r["is_needed"] for r in rows}


def test_casual_dx_log_seeds_and_flips_needed_dupe():
    db = _casual_db()
    # Isolate host last-log prefs; use explicit seed so real N2OY/wa1hco on disk
    # cannot win auto-discover (also_standard scan).
    pref = db + ".last_log.json"
    os.environ["WIMS_LAST_LOG"] = pref
    try:
        live = LiveFleet()
        # Explicit path: only this file's contests; pick_contest fallback still
        # rescues the skip-named 'DX' log when it is the only one in the file.
        res = live.seed_explicit_db(db)
        assert res["ok"] and res["seeded"] == 1, res
        assert res.get("source") == "cli"
        assert (res.get("contest") or {}).get("contest_name") == "DX"

        now = time.time()
        live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, de_call="WA1HCO",
                           de_grid="FN42")), now, "127.0.0.1")
        for call, grid in (("K1ABC", "FN31"), ("W9NEW", "EM79")):   # both on 20m
            live.observe_wsjtx(M.parse(E.build_decode(MID, time_ms=1000, snr=-8, delta_time=0.2,
                               delta_frequency=1500, message=f"CQ {call} {grid}")), now, "127.0.0.1")

        m = _needed(live)
        assert m["K1ABC"] is False, "logged call should read as dupe"
        assert m["W9NEW"] is True, "unlogged call should read as needed"

        live._log.delete(QID)                             # tester removes the QSO
        assert _needed(live)["K1ABC"] is True, "delete must flip roster row to needed"

        live._log.upsert(LoggedQso.from_dxlog_row(        # tester works W9NEW
            {"id": "n1", "call": "W9NEW", "band": "14", "gridsquare": "EM79",
             "mode": "FT8", "contestname": "DX", "contestnr": 5}))
        assert _needed(live)["W9NEW"] is False, "log must flip roster row to dupe"
    finally:
        os.environ.pop("WIMS_LAST_LOG", None)
        for p in (db, pref):
            try:
                os.unlink(p)
            except OSError:
                pass


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
