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

"""Heard-grid memory: tail-end logging, rover squares, and the roster hover."""

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.log.app import rebuild_n1mm_adif  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.state.heard_grids import (  # noqa: E402
    MAX_AGE_S,
    ROVER_WINDOW_S,
    HeardGrids,
)
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc


def _t(hour=14, minute=10, day=19) -> float:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC).timestamp()


def test_tail_end_qso_gets_the_remembered_grid():
    """A blank QSO Logged line takes the grid heard earlier, not the WSJT-X file."""
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    chosen = tmp / "wsjtx_log.adi"
    chosen.write_text("WSJT-X\n<eoh>\n", encoding="utf-8")
    before = chosen.read_bytes()
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    heard_at = time.time() - 2 * 24 * 3600
    qso_at = datetime.now(UTC) - timedelta(seconds=30)
    try:
        live = LiveFleet()
        live._install_chosen({
            "kind": "wsjtx",
            "label": "WSJT-X log",
            "path": str(chosen),
            "paths": [str(chosen)],
        }, [], None)
        live._log_choice_active = True
        live.observe_wsjtx(
            M.parse(E.build_status(
                "IC7300", 14_074_000, mode="FT8", decoding=True, de_call="W1XX",
            )),
            now=heard_at, src_ip="10.0.0.8",
        )
        live.observe_wsjtx(
            M.parse(E.build_decode(
                "IC7300", time_ms=0, snr=-8, delta_time=0.1,
                delta_frequency=800, mode="FT8", message="CQ DX CX4BAN GF15",
            )),
            now=heard_at + 1, src_ip="10.0.0.8",
        )
        # The live roster row has aged off. The fill has to come from memory.
        live._roster._entries.clear()
        live.observe_wsjtx(
            M.parse(E.build_qso_logged(
                "IC7300", dx_call="CX4BAN", dx_grid="",
                tx_frequency=14_074_000, mode="FT8",
                datetime_off=qso_at, datetime_on=qso_at,
            )),
            now=time.time(), src_ip="10.0.0.8",
        )
        row = live._log.con.execute(
            "SELECT call, grid, grid_source FROM qsos"
        ).fetchone()
        assert row is not None
        assert row["call"] == "CX4BAN"
        assert row["grid"] == "GF15"
        assert row["grid_source"] == "remembered"
        relay = list(live._logged_qsos)
        assert relay and "GF15" in relay[-1]["adif"]
        assert "grid remembered" in relay[-1]["adif"].lower()
        assert relay[-1]["grid_source"] == "remembered"
        wire = rebuild_n1mm_adif(relay[-1]["adif"], operator="IC7300")
        assert "GF15" in wire
        assert "grid remembered" in wire.lower()
        assert chosen.read_bytes() == before
    finally:
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


def test_expiry_drops_an_old_station():
    store = HeardGrids()
    heard = _t()
    store.note("CX4BAN", "GF15", "20m", heard)
    assert store.lookup("CX4BAN", heard + MAX_AGE_S).grid == "GF15"
    assert store.lookup("CX4BAN", heard + MAX_AGE_S + 1).grid is None


def test_six_char_upgrades_and_a_different_square_replaces():
    store = HeardGrids()
    t0 = _t()
    assert store.note("K1ABC", "FN", "6m", t0) is False
    store.note("K1ABC", "FN42", "6m", t0)
    store.note("K1ABC", "FN42ab", "6m", t0 + 60)
    assert store.current("K1ABC", t0 + 60) == "FN42AB"
    # A later 4-character hearing of the same square keeps the subsquare.
    store.note("K1ABC", "FN42", "6m", t0 + 120)
    assert store.current("K1ABC", t0 + 120) == "FN42AB"
    # A different square wins even when the stored grid was 6 characters.
    store.note("K1ABC", "FN43", "2m", t0 + 180)
    assert store.current("K1ABC", t0 + 180) == "FN43"


def test_rr73_and_free_text_are_ignored():
    store = HeardGrids()
    t0 = _t()
    assert store.note_message("W1XX CX4BAN RR73", "20m", t0) is False
    assert store.note_message("TNX FER QSO FN31", "20m", t0) is False
    assert store.note_message("W1XX CX4BAN FN42 TU", "20m", t0) is False
    assert store.note_message("RR73", "20m", t0) is False
    assert store.current("CX4BAN", t0) is None
    assert store.note_message("CQ DX CX4BAN GF15", "20m", t0) is True
    assert store.current("CX4BAN", t0) == "GF15"
    assert store.note_message("W1XX CX4BAN R-10", "20m", t0 + 1) is False
    assert store.current("CX4BAN", t0 + 1) == "GF15"


def test_persistence_round_trip():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "heard_grids.json"
    t0 = _t()
    store = HeardGrids(path)
    store.note("CX4BAN", "GF15", "20m", t0)
    store.note("CX4BAN", "GF15xx", "20m", t0 + 30)
    again = HeardGrids(path)
    assert again.current("CX4BAN", t0 + 60) == "GF15XX"
    found = again.lookup("CX4BAN", t0 + 60)
    assert found.remembered and "20m" in found.tip and "14:10" in found.tip


def test_rover_grid_change_and_hover():
    store = HeardGrids()
    first = _t(hour=14, minute=10)
    second = _t(hour=14, minute=22)
    store.note("K1ROV/R", "FN42", "6m", first)
    store.note("K1ROV/R", "FN43", "2m", second)
    assert store.is_rover("K1ROV/R", second)
    found = store.lookup("K1ROV/R", second + 60)
    assert found.grid == "FN43"
    assert "Now FN43" in found.tip
    assert "Was FN42 at 14:10" in found.tip
    assert "6m" in found.tip


def test_stale_rover_grid_is_not_used():
    store = HeardGrids()
    heard = _t()
    store.note("K1ROV/R", "FN42", "6m", heard)
    stale = store.lookup("K1ROV/R", heard + ROVER_WINDOW_S + 60)
    assert stale.grid is None and stale.stale
    assert "FN42" in stale.tip and "not used" in stale.tip
    # A fixed station keeps a square for the whole expiry window.
    store.note("CX4BAN", "GF15", "20m", heard)
    assert store.lookup("CX4BAN", heard + ROVER_WINDOW_S + 60).grid == "GF15"


def test_slash_r_uses_only_a_recent_grid():
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    chosen = tmp / "wsjtx_log.adi"
    chosen.write_text("WSJT-X\n<eoh>\n", encoding="utf-8")
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    try:
        live = LiveFleet()
        live._install_chosen({
            "kind": "wsjtx",
            "label": "WSJT-X log",
            "path": str(chosen),
            "paths": [str(chosen)],
        }, [], None)
        live._log_choice_active = True
        recent = time.time() - 2 * 60
        _hear(live, "K1ROV/R", "FN42", recent, hz=144_174_000)
        live._roster._entries.clear()
        qso_at = datetime.now(UTC)
        live.observe_wsjtx(
            M.parse(E.build_qso_logged(
                "IC7300", dx_call="K1ROV/R", dx_grid="",
                tx_frequency=144_174_000, mode="FT8",
                datetime_off=qso_at, datetime_on=qso_at,
            )),
            now=time.time(), src_ip="10.0.0.8",
        )
        row = live._log.con.execute(
            "SELECT grid, grid_source FROM qsos WHERE call='K1ROV/R'"
        ).fetchone()
        assert row["grid"] == "FN42" and row["grid_source"] == "remembered"

        # The same call, heard too long ago, stays blank.
        live2 = LiveFleet()
        live2._install_chosen({
            "kind": "wsjtx",
            "label": "WSJT-X log",
            "path": str(chosen),
            "paths": [str(chosen)],
        }, [], None)
        live2._log_choice_active = True
        old = time.time() - 2 * 3600
        _hear(live2, "K1ROV/R", "FN42", old, hz=144_174_000)
        live2.observe_wsjtx(
            M.parse(E.build_decode(
                "IC7300", time_ms=0, snr=-4, delta_time=0.1,
                delta_frequency=900, mode="FT8", message="W1XX K1ROV/R R-10",
            )),
            now=time.time(), src_ip="10.0.0.8",
        )
        shown = _row(live2, "K1ROV/R")
        assert not shown["grid"]
        assert shown["grid_stale"] is True
        assert "FN42" in shown["grid_tip"]
        assert "not used" in shown["grid_tip"]
        assert "10 minutes" in shown["grid_tip"]
        assert "grid assumed" not in shown["grid_tip"].lower()
    finally:
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


def test_logged_grid_does_not_override_a_newer_heard_grid():
    """Log says FN42. A new decode says FN43. Needed and Mult follow FN43."""
    live = LiveFleet()
    live._log.upsert(LoggedQso(
        id="q-rov", call="K1ROV/R", band="2m", grid="FN42", mode="FT8",
        points=0, is_mult=False, contest=None, timestamp=None,
        operator=None, rover_location=None, source="seed",
    ))
    now = time.time()
    _hear(live, "K1ROV/R", "FN43", now, hz=144_174_000)
    row = _row(live, "K1ROV/R", now=now + 1)
    assert row["grid"] == "FN43"
    assert row["is_dupe"] is False
    assert row["is_new_mult"] is True
    assert "FN43" in row["mult_reason"]
    live.observe_wsjtx(
        M.parse(E.build_decode(
            "IC7300", time_ms=0, snr=-6, delta_time=0.1,
            delta_frequency=700, mode="FT8", message="W1XX K1ROV/R R-10",
        )),
        now=now + 2, src_ip="10.0.0.8",
    )
    later = _row(live, "K1ROV/R", now=now + 3)
    assert later["grid"] == "FN43"
    assert later["grid_remembered"] is True
    assert "FN43" in later["grid_tip"]
    assert "grid assumed" in later["grid_tip"].lower()
    assert later["is_dupe"] is False
    assert later["is_new_mult"] is True
    stored = live._log.con.execute(
        "SELECT grid FROM qsos WHERE call='K1ROV/R'"
    ).fetchone()
    assert stored["grid"] == "FN42"


def test_roster_styles_a_remembered_grid():
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(
        encoding="utf-8",
    )
    css = (ROOT / "src" / "wims" / "server" / "static" / "wims.css").read_text(
        encoding="utf-8",
    )
    assert "function rosGrid" in js
    assert "grid-remembered" in js and "grid_tip" in js
    assert "grid assumed" in js
    assert "grid-remembered" in css
    assert "grid-assumed" in css


def _hear(live, call, grid, now, hz=14_074_000):
    live.observe_wsjtx(
        M.parse(E.build_status(
            "IC7300", hz, mode="FT8", decoding=True, de_call="W1XX",
        )),
        now=now, src_ip="10.0.0.8",
    )
    live.observe_wsjtx(
        M.parse(E.build_decode(
            "IC7300", time_ms=0, snr=-8, delta_time=0.1,
            delta_frequency=800, mode="FT8",
            message=f"CQ {call} {grid}",
        )),
        now=now + 0.2, src_ip="10.0.0.8",
    )


def _row(live, call, now=None):
    rows = live.snapshot(now if now is not None else time.time())["roster"]["candidates"]
    return next(c for c in rows if c["call"] == call)


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
    if failed:
        raise SystemExit(1)
