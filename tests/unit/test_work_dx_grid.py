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

"""DX Grid sent with Work: encoding, when to send, rover window, later decode."""

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.server.app import LiveFleet  # noqa: E402
from wims.state.heard_grids import (  # noqa: E402
    GRID_ASSUMED,
    GRID_REMEMBERED,
    ROVER_WINDOW_S,
    GridLookup,
    HeardGrids,
    grid_for_work,
)
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

MID = "RIG-20M"
OTHER = "RIG-6M"
CTRL = 54321
UTC = timezone.utc


class _FakeTx:
    def __init__(self):
        self.dest = ("127.0.0.1", 2237)
        self.sent = []

    def reply(self, inst, decode, *, modifiers=0, dests=None):
        self.sent.append(("reply", inst, decode.message, dests))

    def configure(self, inst, *, dx_call, dx_grid="", rx_df=None,
                  generate_messages=True, mode="", schema=2, dests=None):
        self.sent.append(("configure", inst, dx_call, dx_grid, dests))

    def configure_grid(self, inst, dx_grid, *, schema=2, dests=None):
        self.sent.append(("grid", inst, dx_grid, schema, dests))

    def halt(self, inst, *, auto_only=False, dests=None):
        self.sent.append(("halt", inst, dests))


def _hear(live, mid, message, hz, when, host="127.0.0.1", port=CTRL):
    live.observe_wsjtx(
        M.parse(E.build_status(mid, hz, mode="FT8", de_call="W1XX", de_grid="FN42")),
        when, host, port,
    )
    live.observe_wsjtx(
        M.parse(E.build_decode(
            mid, time_ms=1000, snr=-8, delta_time=0.2, delta_frequency=1200,
            message=message,
        )),
        when, host, port,
    )


def _row_id(live, when=None):
    rows = live.snapshot(when if when is not None else time.time())["roster"]["candidates"]
    assert rows, "expected a roster row"
    return rows[0]["id"]


def test_configure_grid_leaves_every_other_field_unchanged():
    raw = E.build_configure_grid("RIG-20M", "fn31")
    msg = M.parse(raw)
    assert isinstance(msg, M.Configure)
    assert msg.type == M.CONFIGURE
    assert msg.id == "RIG-20M"
    assert msg.mode == ""
    assert msg.submode == ""
    assert msg.dx_call == ""
    assert msg.dx_grid == "FN31"
    assert msg.frequency_tolerance is None
    assert msg.tr_period is None
    assert msg.rx_df is None
    assert msg.fast_mode is False
    assert msg.generate_messages is False
    # A blank grid on the older Configure helper is no change, not a space.
    blank = M.parse(E.build_configure("RIG-20M", dx_call="K1ABC", dx_grid=""))
    assert isinstance(blank, M.Configure)
    assert blank.dx_grid == ""
    assert blank.dx_call == "K1ABC"


def test_configure_grid_rejects_a_non_locator():
    try:
        E.build_configure_grid("RIG-20M", "RR73")
    except ValueError:
        pass
    else:
        raise AssertionError("RR73 is not a grid")
    try:
        E.build_configure_grid("RIG-20M", "")
    except ValueError:
        pass
    else:
        raise AssertionError("empty is not a grid")


def test_decision_remembered_none_stale_and_decode_grid():
    store = HeardGrids()
    t0 = datetime(2026, 10, 20, 18, 0, tzinfo=UTC).timestamp()
    assert grid_for_work("W1XX CX4BAN R-10", store.lookup("CX4BAN", t0)) is None

    store.note("CX4BAN", "GF15", "20m", t0)
    assert grid_for_work("W1XX CX4BAN R-10", store.lookup("CX4BAN", t0 + 60)) == "GF15"
    assert grid_for_work("CQ CX4BAN GF15", store.lookup("CX4BAN", t0 + 60)) is None
    assert grid_for_work("W1XX CX4BAN GF15", store.lookup("CX4BAN", t0 + 60)) is None
    # A fixed station is still filled after the rover window.
    assert grid_for_work(
        "W1XX CX4BAN 73", store.lookup("CX4BAN", t0 + ROVER_WINDOW_S + 60),
    ) == "GF15"

    store.note("K1ROV/R", "FN42", "6m", t0)
    fresh = store.lookup("K1ROV/R", t0 + 60)
    assert grid_for_work("W1XX K1ROV/R R-10", fresh) == "FN42"
    assert "grid assumed" in fresh.tip.lower()
    on_time = store.lookup("K1ROV/R", t0 + ROVER_WINDOW_S)
    assert grid_for_work("W1XX K1ROV/R R-10", on_time) == "FN42"
    stale = store.lookup("K1ROV/R", t0 + ROVER_WINDOW_S + 1)
    assert stale.stale and stale.grid is None
    assert grid_for_work("W1XX K1ROV/R R-10", stale) is None
    assert "grid assumed" not in stale.tip.lower()

    # Heard in two squares, no /R: same window, newest square only.
    store.note("N1MOV", "FN31", "2m", t0)
    store.note("N1MOV", "FN32", "2m", t0 + 30)
    assert store.is_rover("N1MOV", t0 + 40)
    assert grid_for_work("W1XX N1MOV 73", store.lookup("N1MOV", t0 + 40)) == "FN32"
    assert grid_for_work(
        "W1XX N1MOV 73", store.lookup("N1MOV", t0 + 30 + ROVER_WINDOW_S + 5),
    ) is None

    # A lookup that already says remembered is still blocked when the decode has a grid.
    forced = GridLookup(grid="AA00", tip="x", remembered=True)
    assert grid_for_work("CQ K1ABC FN20", forced) is None
    assert GRID_ASSUMED == "grid assumed"
    assert GRID_REMEMBERED == "grid remembered"


def test_work_sends_remembered_grid_only_to_that_instance():
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    _hear(live, MID, "CQ CX4BAN GF15", 14_074_000, now - 120)
    _hear(live, MID, "W1XX CX4BAN R-10", 14_074_000, now)
    row = next(
        c["id"] for c in live.snapshot(now)["roster"]["candidates"]
        if "R-10" in (c.get("message") or "")
    )
    tx.sent.clear()
    r = live.work_station(row)
    assert r["ok"] and r["grid"] == "GF15" and r["grid_assumed"] is True
    assert "grid assumed" in (r.get("detail") or "").lower()
    kinds = [s[0] for s in tx.sent]
    assert kinds[0] == "reply"
    assert tx.sent[0][1] == MID
    assert tx.sent[0][2] == "W1XX CX4BAN R-10"
    assert tx.sent[0][3] == [("127.0.0.1", CTRL)]
    grids = [s for s in tx.sent if s[0] == "grid"]
    assert len(grids) == 1
    assert grids[0][1] == MID and grids[0][2] == "GF15"
    assert grids[0][4] == [("127.0.0.1", CTRL)]
    assert all(s[1] == MID for s in tx.sent)


def test_work_skips_grid_when_decode_has_one_or_memory_is_empty():
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live._heard.note("K1ABC", "FN99", "20m", now - 30)
    _hear(live, MID, "CQ K1ABC FN31", 14_074_000, now)
    r = live.work_station(_row_id(live, now))
    assert r["ok"] and r["grid"] == "" and r["grid_assumed"] is False
    assert not any(s[0] == "grid" for s in tx.sent)
    assert tx.sent[0][2] == "CQ K1ABC FN31"

    tx2 = _FakeTx()
    live2 = LiveFleet(tx_controller=tx2)
    _hear(live2, MID, "W1XX N0NEW R-12", 14_074_000, now)
    r2 = live2.work_station(_row_id(live2, now))
    assert r2["ok"] and r2["grid"] == ""
    assert not any(s[0] == "grid" for s in tx2.sent)


def test_work_skips_a_stale_rover_grid():
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live._heard.note("K1ROV/R", "FN42", "6m", now - ROVER_WINDOW_S - 30)
    _hear(live, MID, "W1XX K1ROV/R 73", 14_074_000, now)
    r = live.work_station(_row_id(live, now))
    assert r["ok"] and r["grid"] == ""
    assert not any(s[0] == "grid" for s in tx.sent)


def test_refused_work_does_not_send_a_grid():
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx, grouping="band")
    now = time.time()
    live._heard.note("K1ABC", "FN31", "20m", now - 30)
    live._heard.note("K1DEF", "FN32", "20m", now - 30)
    _hear(live, MID, "W9XYZ K1ABC 73", 14_074_000, now)
    _hear(live, OTHER, "W9XYZ K1DEF 73", 14_074_000, now, port=CTRL + 1)
    rows = live.snapshot(now)["roster"]["candidates"]
    first = next(c["id"] for c in rows if c["call"] == "K1ABC")
    second = next(c["id"] for c in rows if c["call"] == "K1DEF")
    assert live.work_station(first)["ok"]
    tx.sent.clear()
    refused = live.work_station(second)
    assert refused["ok"] is False and refused["error"] == "group_busy"
    assert tx.sent == []


def test_newer_decode_updates_the_open_contact():
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    chosen = tmp / "wsjtx_log.adi"
    chosen.write_text("WSJT-X\n<eoh>\n", encoding="utf-8")
    before = chosen.read_bytes()
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    try:
        tx = _FakeTx()
        live = LiveFleet(tx_controller=tx)
        live._install_chosen({
            "kind": "wsjtx",
            "label": "WSJT-X log",
            "path": str(chosen),
            "paths": [str(chosen)],
        }, [], None)
        live._log_choice_active = True
        now = time.time()
        live._heard.note("K1ROV/R", "FN42", "20m", now - 60)
        _hear(live, MID, "W1XX K1ROV/R R-10", 14_074_000, now)
        _hear(live, OTHER, "W1XX K1ROV/R R-10", 50_313_000, now, port=CTRL + 1)
        rows = live.snapshot(now)["roster"]["candidates"]
        worked = next(c["id"] for c in rows if c["instance"] == MID and c["call"] == "K1ROV/R")
        tx.sent.clear()
        assert live.work_station(worked)["grid"] == "FN42"
        qso_at = datetime.now(UTC)
        live.observe_wsjtx(
            M.parse(E.build_qso_logged(
                MID, dx_call="K1ROV/R", dx_grid="",
                tx_frequency=14_074_000, mode="FT8",
                datetime_off=qso_at, datetime_on=qso_at,
            )),
            now + 1, "127.0.0.1", CTRL,
        )
        # An older remembered contact must not be rewritten.
        live._log.con.execute(
            "INSERT INTO qsos (id, call, band, grid, grid_source, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("old-rov", "K1ROV/R", "6m", "EM00", "remembered", "2020-01-01 00:00:00"),
        )
        live._log.con.commit()
        live._logged_qsos.append({
            "ts": now - 3600,
            "instance": MID,
            "call": "K1ROV/R",
            "band": "6m",
            "adif": "<call:7>K1ROV/R <gridsquare:4>EM00 <comment:15>grid remembered <eor>",
            "grid_source": "remembered",
        })
        live.observe_wsjtx(
            M.parse(E.build_status(
                MID, 14_074_000, mode="FT8", tx_enabled=True, transmitting=True,
            )),
            now + 2, "127.0.0.1", CTRL,
        )
        tx.sent.clear()
        live.observe_wsjtx(
            M.parse(E.build_decode(
                OTHER, time_ms=2000, snr=-5, delta_time=0.1, delta_frequency=900,
                message="CQ K1ROV/R FN99",
            )),
            now + 3, "127.0.0.1", CTRL + 1,
        )
        assert not any(s[0] == "grid" for s in tx.sent)
        live.observe_wsjtx(
            M.parse(E.build_decode(
                MID, time_ms=2000, snr=-5, delta_time=0.1, delta_frequency=900,
                message="CQ K1ROV/R FN43",
            )),
            now + 4, "127.0.0.1", CTRL,
        )
        grids = [s for s in tx.sent if s[0] == "grid"]
        assert grids == [("grid", MID, "FN43", 2, [("127.0.0.1", CTRL)])]
        assert not any(s[0] == "reply" for s in tx.sent)
        row = live._log.con.execute(
            "SELECT grid, grid_source FROM qsos WHERE call='K1ROV/R' AND band='20m'"
        ).fetchone()
        assert row["grid"] == "FN43" and row["grid_source"] == "remembered"
        relay = [q for q in live._logged_qsos if q.get("call") == "K1ROV/R"]
        assert len(relay) == 2
        forwarded = relay[-2]["adif"].lower()
        assert "fn43" in forwarded
        assert "grid remembered" in forwarded
        assert "grid assumed" not in forwarded
        assert "em00" in relay[-1]["adif"].lower()
        old = live._log.con.execute(
            "SELECT grid FROM qsos WHERE id='old-rov'"
        ).fetchone()
        assert old["grid"] == "EM00"
        shown = [
            c for c in live.snapshot(now + 5)["roster"]["candidates"]
            if c["call"] == "K1ROV/R" and c["instance"] == MID and c["grid"] == "FN43"
        ]
        assert shown and shown[0]["grid_remembered"] is False
        # The same square again does not send another Configure.
        tx.sent.clear()
        live.observe_wsjtx(
            M.parse(E.build_decode(
                MID, time_ms=3000, snr=-5, delta_time=0.1, delta_frequency=910,
                message="W1XX K1ROV/R FN43",
            )),
            now + 6, "127.0.0.1", CTRL,
        )
        assert tx.sent == []
        assert chosen.read_bytes() == before
    finally:
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


def test_closed_contact_does_not_send_a_later_grid():
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live._heard.note("CX4BAN", "GF15", "20m", now - 30)
    _hear(live, MID, "W1XX CX4BAN 73", 14_074_000, now)
    assert live.work_station(_row_id(live, now))["ok"]
    live.observe_wsjtx(
        M.parse(E.build_status(MID, 14_074_000, mode="FT8", transmitting=True)),
        now + 1, "127.0.0.1", CTRL,
    )
    live.observe_wsjtx(
        M.parse(E.build_status(MID, 14_074_000, mode="FT8", transmitting=False)),
        now + 2, "127.0.0.1", CTRL,
    )
    # Past the arm grace, with TX off and the grant released.
    later = now + 2 + 120
    tx.sent.clear()
    live.observe_wsjtx(
        M.parse(E.build_decode(
            MID, time_ms=4000, snr=-4, delta_time=0.1, delta_frequency=800,
            message="CQ CX4BAN GF16",
        )),
        later, "127.0.0.1", CTRL,
    )
    assert not any(s[0] == "grid" for s in tx.sent)


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
