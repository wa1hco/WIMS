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

"""Host-local last contest log preference + LiveFleet restore on auto_seed."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.state import last_log as LL  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402


def _mk_db(contests_qsos: list[tuple]) -> str:
    """Build a minimal multi-contest .s3db.

    contests_qsos: list of (contest_nr, name, start, [calls...])
    """
    fd, db = tempfile.mkstemp(suffix=".s3db")
    os.close(fd)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE ContestInstance (
          ContestID INT, ContestName TEXT, StartDate TEXT, ContestNR INT);
        CREATE TABLE DXLOG (
          ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, Mode TEXT,
          Points INT, IsMultiplier1 INT, ContestName TEXT, ContestNR INT,
          TimeStamp TEXT, Operator TEXT);
    """)
    for i, (nr, name, start, calls) in enumerate(contests_qsos):
        con.execute("INSERT INTO ContestInstance VALUES (?,?,?,?)",
                    (i + 1, name, start, nr))
        for j, call in enumerate(calls):
            qid = f"{nr}{j}" + "0" * (32 - len(f"{nr}{j}"))
            con.execute(
                "INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (qid[:32], call, "50", "FN42", "FT8", 1, 0, name, nr,
                 start, "WA1HCO"))
    con.commit()
    con.close()
    return db


def test_save_load_roundtrip(tmp_path=None):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    try:
        assert LL.load(path) is None
        written = LL.save({
            "db_path": "/data/wa1hco.s3db",
            "contest_nr": 0,
            "contest_name": "DX",
            "db_label": "wa1hco.s3db",
            "label": "DX · 100 QSOs",
        }, path=path)
        assert written is not None and written.is_file()
        got = LL.load(path)
        assert got is not None
        assert got["db_path"] == "/data/wa1hco.s3db"
        assert got["contest_nr"] == 0
        assert got["contest_name"] == "DX"
        assert got["db_label"] == "wa1hco.s3db"
        assert got.get("saved_ts") is not None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_match_in_catalog_path_and_basename():
    catalog = [
        {"db_path": "/a/N2OY.s3db", "contest_nr": 2, "contest_name": "ARRLVHFJUN",
         "qso_count": 950, "db_label": "N2OY.s3db"},
        {"db_path": "/a/wa1hco.s3db", "contest_nr": 0, "contest_name": "DX",
         "qso_count": 100, "db_label": "wa1hco.s3db"},
    ]
    pref = {"db_path": "/a/wa1hco.s3db", "contest_nr": 0, "contest_name": "DX"}
    m = LL.match_in_catalog(pref, catalog)
    assert m is not None and m["contest_name"] == "DX"

    # File moved to another folder — same basename + nr
    pref2 = {"db_path": "/old/wa1hco.s3db", "contest_nr": 0}
    m2 = LL.match_in_catalog(pref2, catalog)
    assert m2 is not None and m2["db_path"] == "/a/wa1hco.s3db"

    # Wrong nr
    assert LL.match_in_catalog(
        {"db_path": "/a/wa1hco.s3db", "contest_nr": 99}, catalog) is None


def test_auto_seed_prefers_remembered_over_dated_contest():
    """Home DX log remembered beats ARRLVHFJUN auto-pick (the N2OY case)."""
    db_june = _mk_db([(2, "ARRLVHFJUN", "2026-06-13", ["J1J", "J2J"])])
    db_dx = _mk_db([(0, "DX", "1900-01-01", ["D1D"] * 5)])
    pref_path = db_dx + ".last_log.json"
    try:
        # Put both under one scan dir via seed-db-dir of a parent... easier:
        # configure with no dir, discover only explicit paths via two configure
        # approaches: use a shared folder.
        root = tempfile.mkdtemp(prefix="wims-lastlog-")
        june = Path(root) / "N2OY.s3db"
        dx = Path(root) / "wa1hco.s3db"
        Path(db_june).replace(june)
        Path(db_dx).replace(dx)
        db_june = str(june)
        db_dx = str(dx)

        # Without memory: auto picks June (real date, not DX skip name).
        live0 = LiveFleet()
        live0.configure_log_discovery(databases_dir=root)
        # Isolate preference file so host prefs don't leak into the test.
        os.environ["WIMS_LAST_LOG"] = pref_path
        try:
            if Path(pref_path).is_file():
                os.unlink(pref_path)
            r0 = live0.auto_seed()
            assert r0["ok"] and r0.get("source") == "auto"
            assert r0["contest"]["contest_name"] == "ARRLVHFJUN"

            # Operator picks casual DX (Setup path) → remembered.
            live0.select_contest(db_path=db_dx, contest_nr=0)
            assert Path(pref_path).is_file()
            assert live0.snapshot(1.0)["n1mm_sync"]["active_contest"]["contest_name"] == "DX"
            assert live0.snapshot(1.0)["n1mm_sync"]["qso_count"] == 5

            # Fresh server process simulation: new LiveFleet, same pref file.
            live1 = LiveFleet()
            live1.configure_log_discovery(databases_dir=root)
            r1 = live1.auto_seed()
            assert r1["ok"] and r1.get("source") == "remembered"
            assert r1["contest"]["contest_name"] == "DX"
            assert r1["seeded"] == 5
            assert live1.snapshot(2.0)["n1mm_sync"]["qso_count"] == 5
            assert live1.snapshot(2.0)["n1mm_sync"]["seed"]["selection"] == "remembered"
        finally:
            os.environ.pop("WIMS_LAST_LOG", None)
            try:
                os.unlink(pref_path)
            except OSError:
                pass
    finally:
        for p in (db_june, db_dx):
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(root)
        except OSError:
            pass


def test_seed_explicit_db_remembers_and_ignores_other_files():
    root = tempfile.mkdtemp(prefix="wims-explicit-")
    june = Path(root) / "N2OY.s3db"
    dx = Path(root) / "wa1hco.s3db"
    Path(_mk_db([(2, "ARRLVHFJUN", "2026-06-13", ["J1J"])])).replace(june)
    Path(_mk_db([(0, "DX", "1900-01-01", ["D1D", "D2D"])])).replace(dx)
    pref_path = str(Path(root) / "last.json")
    os.environ["WIMS_LAST_LOG"] = pref_path
    try:
        live = LiveFleet()
        live.configure_log_discovery(databases_dir=root)
        r = live.seed_explicit_db(str(dx))
        assert r["ok"] and r.get("source") == "cli"
        assert r["contest"]["contest_name"] == "DX"
        assert r["seeded"] == 2
        # Preference written
        pref = LL.load(pref_path)
        assert pref is not None and Path(pref["db_path"]).name == "wa1hco.s3db"
    finally:
        os.environ.pop("WIMS_LAST_LOG", None)
        for p in (june, dx, Path(pref_path)):
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(root)
        except OSError:
            pass


def test_stale_remembered_path_falls_back_to_auto():
    root = tempfile.mkdtemp(prefix="wims-stale-")
    june = Path(root) / "N2OY.s3db"
    Path(_mk_db([(2, "ARRLVHFJUN", "2026-06-13", ["J1J"])])).replace(june)
    pref_path = str(Path(root) / "last.json")
    LL.save({
        "db_path": str(Path(root) / "gone.s3db"),
        "contest_nr": 0,
        "contest_name": "DX",
    }, path=pref_path)
    os.environ["WIMS_LAST_LOG"] = pref_path
    try:
        live = LiveFleet()
        live.configure_log_discovery(databases_dir=root)
        r = live.auto_seed()
        assert r["ok"] and r.get("source") == "auto"
        assert r["contest"]["contest_name"] == "ARRLVHFJUN"
    finally:
        os.environ.pop("WIMS_LAST_LOG", None)
        for p in (june, Path(pref_path)):
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(root)
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
