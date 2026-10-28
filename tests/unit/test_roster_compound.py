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

"""One roster line for an FT8 compound call.

The lines are the 30 m FT8 decodes of P4/WE9V from the operator's ALL.TXT.
A compound CQ cannot carry a grid, so the row stays blank and names Aruba.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.callsign import COMPOUND_LINK_S  # noqa: E402
from wims.engine.dxcc import country_fields  # noqa: E402
from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.server.state import roster_to_dict  # noqa: E402
from wims.state.heard_grids import HeardGrids  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

# Exact text from ALL.TXT. Do not tidy the brackets or the semicolon.
P4_WE9V_30M = (
    "CQ P4/WE9V",
    "K5WVF <P4/WE9V> -10",
    "K5WVF RR73; YU6DX <P4/WE9V> +04",
    "<...> P4/WE9V RR73",
    "<WB8EJN> P4/WE9V RR73",
    "<P4/WE9V> WB8EJN EM48",
    "EU2NS <P4/WE9V> -01",
)


def _decode(mid, msg, *, snr=-8, df=1200):
    return M.parse(E.build_decode(
        mid, time_ms=0, snr=snr, delta_time=0.2,
        delta_frequency=df, message=msg,
    ))


def _feed(rb, lines, *, band="30m", mid="30M", start=1_000.0, heard=None):
    for i, text in enumerate(lines):
        now = start + i
        dec = _decode(mid, text)
        rb.canonicalize(dec, band, now)
        if heard is not None:
            heard.note_decode(dec, band, now)
        rb.observe_decode(dec, band, now)
    return start + len(lines)


def _rows(rb, now):
    scored, _ = rb.ranked(now=now)
    snap = roster_to_dict(
        scored, 0, now, condition="open", strategy="vhf-default",
    )
    return snap["candidates"]


def test_country_of_the_full_call_is_aruba():
    assert country_fields("P4/WE9V")["country"] == "Aruba"
    assert country_fields("<P4/WE9V>")["country"] == "Aruba"
    assert country_fields("WE9V")["country"] == "United States"


def test_all_txt_is_one_p4_line_without_a_grid():
    """Every ALL.TXT form is one P4/WE9V line. EM48 stays with WB8EJN."""
    heard = HeardGrids()
    rb = RosterBuilder(log=None)
    now = _feed(rb, P4_WE9V_30M, heard=heard)
    rows = _rows(rb, now)
    by = {}
    for row in rows:
        assert "<" not in row["call"]
        assert row["call"] not in {"RR73;", "<...>", "..."}
        by.setdefault(row["call"], row)
    assert sum(1 for row in rows if row["call"] == "P4/WE9V") == 1
    p4 = by["P4/WE9V"]
    assert p4["country"] == "Aruba"
    assert p4["continent"] == "SA"
    assert p4["cq_zone"] == 9
    assert not p4["grid"]
    assert p4["grid_assumed"] is False
    assert p4["grid_remembered"] is False
    assert p4["grid_stale"] is False
    assert p4["message"] == "EU2NS <P4/WE9V> -01"
    assert p4["to_call"] == "EU2NS"
    assert p4["is_needed"] is True
    assert p4["is_dupe"] is False
    # The hash that never resolved does not open a line.
    assert "<...>" not in by
    # WB8EJN sent EM48 while calling the fox. That square is not Aruba's.
    assert by["WB8EJN"]["grid"] == "EM48"
    assert by["WB8EJN"]["to_call"] == "P4/WE9V"
    assert by["WB8EJN"]["grid_assumed"] is False
    assert heard.current("P4/WE9V", now) is None
    assert heard.current("WB8EJN", now) == "EM48"


def test_worked_home_call_does_not_dupe_the_compound():
    """Needed follows P4/WE9V. WE9V in the log is a different call."""
    log = LogStore(":memory:")
    log.upsert(LoggedQso(
        id="home", call="WE9V", band="30m", grid="FN42", mode="FT8",
        points=1, is_mult=False, contest="DX", timestamp="", operator="",
        rover_location=None, source="test",
    ))
    rb = RosterBuilder(log=log)
    now = _feed(rb, P4_WE9V_30M)
    p4 = next(row for row in _rows(rb, now) if row["call"] == "P4/WE9V")
    assert p4["is_dupe"] is False
    assert p4["is_needed"] is True
    assert p4["country"] == "Aruba"
    assert "P4/WE9V" in p4["need_reason"]

    worked = LogStore(":memory:")
    worked.upsert(LoggedQso(
        id="p4", call="P4/WE9V", band="30m", grid="", mode="FT8",
        points=1, is_mult=True, contest="DX", timestamp="", operator="",
        rover_location=None, source="test",
    ))
    rb = RosterBuilder(log=worked)
    now = _feed(rb, ("CQ P4/WE9V", "EU2NS <P4/WE9V> -01"))
    p4 = _rows(rb, now)[0]
    assert p4["call"] == "P4/WE9V"
    assert p4["is_dupe"] is True
    assert p4["country"] == "Aruba"
    assert "P4/WE9V" in p4["need_reason"]


def test_home_call_joins_recent_compound_without_borrowing_a_grid():
    """EU2NS WE9V after the CQ is still P4/WE9V. A remembered US grid is not."""
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=10.0)
    rb.observe_decode(
        _decode("30M", "EU2NS WE9V -01"), "30m", now=40.0,
        heard_grid="FN42", heard_assumed=True, heard_tip="Grid from 30m",
    )
    rows = _rows(rb, 41.0)
    assert [row["call"] for row in rows] == ["P4/WE9V"]
    assert not rows[0]["grid"]
    assert rows[0]["grid_assumed"] is False
    assert rows[0]["country"] == "Aruba"
    assert rows[0]["message"] == "EU2NS WE9V -01"


def test_home_cq_stays_a_different_station():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("30M", "CQ WE9V FN42"), "30m", now=10.0)
    rb.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=20.0)
    rb.observe_decode(_decode("30M", "EU2NS WE9V -10"), "30m", now=30.0)
    rows = _rows(rb, 31.0)
    by = {row["call"]: row for row in rows}
    assert set(by) == {"WE9V", "P4/WE9V"}
    assert by["WE9V"]["grid"] == "FN42"
    assert by["WE9V"]["country"] == "United States"
    assert not by["P4/WE9V"]["grid"]
    assert by["P4/WE9V"]["country"] == "Aruba"
    assert by["P4/WE9V"]["grid_assumed"] is False


def test_home_call_does_not_cross_band_instance_or_window():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=10.0)
    rb.observe_decode(_decode("30M", "EU2NS WE9V -01"), "20m", now=20.0)
    rows = _rows(rb, 21.0)
    by_msg = {row["message"]: row for row in rows}
    assert by_msg["CQ P4/WE9V"]["call"] == "P4/WE9V"
    assert by_msg["EU2NS WE9V -01"]["call"] == "WE9V"
    assert by_msg["EU2NS WE9V -01"]["band"] == "20m"

    other = RosterBuilder(log=None)
    other.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=10.0)
    other.observe_decode(_decode("40M", "EU2NS WE9V -01"), "30m", now=20.0)
    calls = {row["call"] for row in _rows(other, 21.0)}
    assert calls == {"P4/WE9V", "WE9V"}

    late = RosterBuilder(log=None)
    late.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=10.0)
    when = 10.0 + COMPOUND_LINK_S + 1.0
    late.observe_decode(_decode("30M", "K1ABC WE9V RR73"), "30m", now=when)
    calls = {row["call"] for row in _rows(late, when + 1)}
    assert calls == {"P4/WE9V", "WE9V"}


def test_exchange_before_the_cq_folds_into_the_compound():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("30M", "EU2NS WE9V -10"), "30m", now=10.0)
    rb.observe_decode(_decode("30M", "CQ P4/WE9V"), "30m", now=25.0)
    rows = _rows(rb, 26.0)
    assert [row["call"] for row in rows] == ["P4/WE9V"]
    assert not rows[0]["grid"]
    assert rows[0]["grid_assumed"] is False
    assert rows[0]["country"] == "Aruba"


def test_grid_copied_with_the_home_call_stays_on_the_compound():
    """A square in the home-call message belongs to the compound, not assumed."""
    heard = HeardGrids()
    rb = RosterBuilder(log=None)
    cq = _decode("30M", "CQ P4/WE9V")
    rb.canonicalize(cq, "30m", 50.0)
    heard.note_decode(cq, "30m", 50.0)
    rb.observe_decode(cq, "30m", now=50.0)
    report = _decode("30M", "EU2NS WE9V FK52")
    rb.canonicalize(report, "30m", 60.0)
    assert report.dx_call == "P4/WE9V"
    assert report.grid == "FK52"
    heard.note_decode(report, "30m", 60.0)
    rb.observe_decode(report, "30m", now=60.0)
    assert heard.current("P4/WE9V", 61.0) == "FK52"
    assert heard.current("WE9V", 61.0) is None
    row = _rows(rb, 61.0)[0]
    assert row["call"] == "P4/WE9V"
    assert row["grid"] == "FK52"
    assert row["grid_assumed"] is False
    assert row["country"] == "Aruba"


def test_unresolved_hash_never_opens_a_line():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("30M", "EU2NS <...> -01"), "30m", now=10.0)
    rb.observe_decode(_decode("30M", "<...> <...> RR73"), "30m", now=11.0)
    rb.observe_decode(_decode("30M", "CQ <...>"), "30m", now=12.0)
    assert _rows(rb, 13.0) == []


def test_suffix_and_prefix_forms_stay_one_line():
    """ /P /R /QRP /MM and a prefix such as VE3/W1XX. """
    cases = (
        ("W1XX/P", "CQ W1XX/P FN42", "K1ABC <W1XX/P> R-05", "FN42", "United States", False),
        ("W1XX/R", "CQ W1XX/R FN31", "K1ABC <W1XX/R> RR73", "FN31", "United States", True),
        ("W1XX/QRP", "CQ W1XX/QRP", "K1ABC <W1XX/QRP> -12", "", "United States", False),
        ("W1XX/MM", "CQ W1XX/MM", "K1ABC <W1XX/MM> RR73", "", "United States", False),
        ("VE3/W1XX", "CQ VE3/W1XX", "EU2NS <VE3/W1XX> -01", "", "Canada", False),
    )
    for full, cq, reply, grid, country, rover in cases:
        rb = RosterBuilder(log=None)
        rb.observe_decode(_decode("20M", cq), "20m", now=10.0)
        rb.observe_decode(_decode("20M", reply), "20m", now=20.0)
        rows = _rows(rb, 21.0)
        assert len(rows) == 1, full
        row = rows[0]
        assert row["call"] == full
        assert (row["grid"] or "") == grid
        assert row["country"] == country
        assert row["grid_assumed"] is False
        assert row["is_rover"] is rover


def test_suffix_base_call_joins_and_a_home_cq_does_not():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("20M", "CQ W1XX/QRP"), "20m", now=10.0)
    rb.observe_decode(_decode("20M", "K1ABC W1XX -05"), "20m", now=30.0)
    rows = _rows(rb, 31.0)
    assert [row["call"] for row in rows] == ["W1XX/QRP"]
    assert rows[0]["country"] == "United States"

    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("20M", "CQ W1XX FN42"), "20m", now=10.0)
    rb.observe_decode(_decode("20M", "CQ W1XX/P FN42"), "20m", now=20.0)
    rb.observe_decode(_decode("20M", "K1ABC W1XX R-09"), "20m", now=30.0)
    by = {row["call"]: row for row in _rows(rb, 31.0)}
    assert set(by) == {"W1XX", "W1XX/P"}
    assert by["W1XX"]["grid"] == "FN42"
    assert by["W1XX/P"]["grid"] == "FN42"
    assert by["W1XX/P"]["grid_assumed"] is False


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
