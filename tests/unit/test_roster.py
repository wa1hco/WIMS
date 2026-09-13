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

"""RosterBuilder: retain decodes, age out, resolve dupe/mult, rank (engine/roster.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402


def _decode(mid, msg, *, snr=-5, df=1500):
    return M.parse(E.build_decode(mid, time_ms=0, snr=snr, delta_time=0.1,
                                  delta_frequency=df, message=msg))


def test_retains_all_decodes_and_ranks():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42", snr=-2), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "CQ W2XYZ FN20", snr=-18), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "WA1HCO K3DEF FN30", snr=0), "6m", now=10.0)  # not CQ
    rows, not_needed = rb.ranked(now=11.0)
    calls = [s.candidate.call for s, _ in rows]
    assert calls == ["K1ABC", "W2XYZ", "K3DEF"]   # all decodes retained; CQ scores rank first
    assert not_needed == 0                         # empty log -> nothing worked
    k3 = next(s for s, _ in rows if s.candidate.call == "K3DEF")
    assert k3.candidate.is_cq is False and k3.total == 0.0   # non-CQ isn't scored, still listed


def test_rover_new_grid_is_distinct_row():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ROV/R FN31"), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ROV/R FN32"), "6m", now=10.0)  # new grid
    rows, _ = rb.ranked(now=11.0)
    grids = sorted(s.candidate.grid for s, _ in rows)
    assert grids == ["FN31", "FN32"]            # two rows, not collapsed
    assert all(s.candidate.is_rover for s, _ in rows)


def test_dupe_from_log_flagged_not_needed():
    log = LogStore(":memory:")
    log.upsert(LoggedQso(id="q1", call="K1ABC", band="6m", grid="FN42", mode="FT8",
                         points=1, is_mult=True, contest="VHF", timestamp="", operator="",
                         rover_location=None, source="test"))
    rb = RosterBuilder(log=log)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42"), "6m", now=10.0)   # already worked
    rb.observe_decode(_decode("SIM-6M", "CQ N1NEW FN43"), "6m", now=10.0)   # fresh + new mult
    rows, not_needed = rb.ranked(now=11.0)
    by = {s.candidate.call: s for s, _ in rows}
    assert set(by) == {"K1ABC", "N1NEW"}                # both retained, none dropped
    assert by["K1ABC"].candidate.is_dupe is True        # worked -> not needed
    assert by["N1NEW"].candidate.is_new_mult is True
    assert not_needed == 1
    assert [s.candidate.call for s, _ in rows][0] == "N1NEW"  # needed ranks above worked dupe


def test_fixed_station_other_grid_is_dupe():
    """N1MM dupes non-rovers on call+band; a wrong/different grid is still worked."""
    log = LogStore(":memory:")
    log.upsert(LoggedQso(id="q1", call="WB1GQR", band="2m", grid="EM96", mode="FT8",
                         points=1, is_mult=True, contest="VHF", timestamp="", operator="",
                         rover_location=None, source="test"))
    rb = RosterBuilder(log=log)
    rb.observe_decode(_decode("SIM-2M", "CQ WB1GQR FN42"), "2m", now=10.0)
    rows, not_needed = rb.ranked(now=11.0)
    assert len(rows) == 1
    assert rows[0][0].candidate.is_dupe is True
    assert not_needed == 1


def test_stale_entries_age_out():
    rb = RosterBuilder(log=None, ttl=60.0)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42"), "6m", now=10.0)
    assert rb.ranked(now=50.0)[0]                  # still present at +40s
    scored, _ = rb.ranked(now=200.0)               # past ttl
    assert scored == []


def test_drop_other_bands_on_qsy():
    """QSY must drop other-band rows for that instance only (wrong-band Work risk)."""
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-A", "CQ K1ABC FN42"), "20m", now=10.0)
    rb.observe_decode(_decode("SIM-A", "CQ W1XYZ FN31"), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-B", "CQ N1NEW FN20"), "20m", now=10.0)  # other instance
    n = rb.drop_other_bands("SIM-A", "6m")
    assert n == 1
    rows, _ = rb.ranked(now=10.0)
    calls = {(s.candidate.instance_id, s.candidate.call, s.candidate.band)
             for s, _ in rows}
    assert ("SIM-A", "W1XYZ", "6m") in calls
    assert ("SIM-B", "N1NEW", "20m") in calls
    assert not any(c[1] == "K1ABC" for c in calls)


def test_drop_other_bands_keeps_unknown_band_rows():
    """Provisional '?' rows are not dropped (reband handles them)."""
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-A", "CQ K1ABC FN42"), "?", now=10.0)
    assert rb.drop_other_bands("SIM-A", "6m") == 0
    assert rb.entry_for("SIM-A|K1ABC|FN42") is not None
    assert rb.reband_unknown("SIM-A", "6m") == 1
    assert rb.entry_for("SIM-A|K1ABC|FN42").band == "6m"


def test_nongrid_report_does_not_split_row():
    """RR73 / R-10 must update the gridded row, not open a second empty-grid line."""
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-2M", "W2SZ N2MKT FN13"), "2m", now=10.0)
    rb.observe_decode(_decode("SIM-2M", "W2SZ N2MKT RR73"), "2m", now=11.0)
    rows, _ = rb.ranked(now=12.0)
    assert len(rows) == 1
    sc, e = rows[0]
    assert sc.candidate.call == "N2MKT"
    assert sc.candidate.grid == "FN13"          # last-known grid kept
    assert e.grid == "FN13"
    assert e.decode.message.endswith("RR73")    # latest decode retained
    assert rb.entry_for("SIM-2M|N2MKT|FN13") is not None
    assert rb.entry_for("SIM-2M|N2MKT|") is None


def test_own_station_tx_is_not_a_roster_row():
    """Second radio hearing our CQ / our reply must not appear as DX."""
    rb = RosterBuilder(log=None)
    own = ["W2SZ"]
    rb.observe_decode(_decode("6M-WAMC", "CQ W2SZ FN32"), "6m", now=10.0, own_calls=own)
    rb.observe_decode(_decode("6M-WAMC", "K1ABC W2SZ FN32"), "6m", now=10.0, own_calls=own)
    rb.observe_decode(_decode("6M-WAMC", "CQ K1ABC FN42"), "6m", now=10.0, own_calls=own)
    rb.observe_decode(_decode("6M-WAMC", "W2SZ K1ABC FN42"), "6m", now=10.0, own_calls=own)
    rows, _ = rb.ranked(now=11.0)
    calls = [s.candidate.call for s, _ in rows]
    assert "W2SZ" not in calls
    assert calls == ["K1ABC"]


def test_own_station_matches_base_call():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("6M-A", "CQ W2SZ/R FN32"), "6m", now=10.0, own_calls=["W2SZ"])
    rows, _ = rb.ranked(now=11.0)
    assert rows == []


def test_drop_own_station_clears_already_retained():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("6M-A", "CQ W2SZ FN32"), "6m", now=10.0)
    assert rb.entry_for("6M-A|W2SZ|FN32") is not None
    assert rb.drop_own_station(["W2SZ"]) == 1
    assert rb.entry_for("6M-A|W2SZ|FN32") is None


def test_grid_after_nongrid_promotes_single_row():
    """First heard as RR73 (no grid), then a grid — still one row."""
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-2M", "W2SZ W1ZFG RR73"), "2m", now=10.0)
    assert rb.entry_for("SIM-2M|W1ZFG|") is not None
    rb.observe_decode(_decode("SIM-2M", "W2SZ W1ZFG FN42"), "2m", now=11.0)
    rows, _ = rb.ranked(now=12.0)
    assert len(rows) == 1
    assert rows[0][0].candidate.grid == "FN42"
    assert rb.entry_for("SIM-2M|W1ZFG|") is None
    assert rb.entry_for("SIM-2M|W1ZFG|FN42") is not None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {t.__name__}"); traceback.print_exc()
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
