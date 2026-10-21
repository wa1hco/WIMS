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

"""Worked but not confirmed: a new station in that place is still wanted.

A new place stays needed. A confirmed place is not needed. The same station
again is not needed. Another station in a worked, unconfirmed place is
unconfirmed. Per band follows the line's scope.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.goal_rules import AwardRules, ChecklistRules, shape_choice  # noqa: E402
from wims.engine.roster_filter import row_visible  # noqa: E402
from wims.engine.scoring import build_candidate  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.rules.cty import CtyIndex  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

_CTY = """\
United States:5:8:NA:43.00:-87.90:0.0:K:
    K,W,N,AA;
Federal Republic of Germany:14:28:EU:51.00:10.00:0.0:DL:
    DL,DA;
Italy:15:28:EU:42.00:12.00:0.0:I:
    I;
"""


def _qso(call, band, grid, mode, *, state=None, dxcc=None, confirmed=False, qid=None):
    return LoggedQso(
        id=qid or f"{call}-{band}-{mode}-{grid or ''}-{state or ''}-{int(confirmed)}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp="",
        operator="", rover_location=None, source="test",
        state=state, dxcc=dxcc, confirmed=confirmed,
    )


def _store(items, rows, *, cty=True, count_unconfirmed=True, award=None):
    store = LogStore(":memory:")
    lookup = (lambda call: {"K1ABC": "United States", "W1AW": "United States",
                            "I1ABC": "Italy"}.get((call or "").upper()))
    if award:
        store.rules = AwardRules(
            award, dxcc_lookup=lookup, log_label="the log",
            count_unconfirmed=count_unconfirmed,
        )
    else:
        store.rules = ChecklistRules(
            items, title="Checklist",
            cty=CtyIndex.parse(_CTY) if cty else None,
            log_label="the log",
            count_unconfirmed=count_unconfirmed,
        )
    for row in rows:
        store.upsert(row)
    return store


class _Decode:
    def __init__(self, call, grid, mode="FT8"):
        self.dx_call = call
        self.grid = grid
        self.mode = mode
        self.id = "6m"
        self.snr = -10
        self.is_cq = True


def test_new_grid_stays_needed():
    store = _store({"grid": {"enabled": True, "scope": "band"}}, [])
    fresh = store.classify("N1NEW", "6m", "FN31", "FT8")
    assert fresh.is_dupe is False and fresh.is_new_mult is True
    assert fresh.chase == "needed"
    assert "FN31" in fresh.need_reason
    assert "unconfirmed" not in fresh.need_reason
    cand = build_candidate(_Decode("N1NEW", "FN31"), "6m", store)
    assert cand.chase == "needed" and cand.is_dupe is False


def test_worked_confirmed_grid_is_not_needed():
    store = _store(
        {"grid": {"enabled": True, "scope": "overall"}},
        [_qso("K1ABC", "6m", "FN42", "FT8", confirmed=True)],
    )
    again = store.classify("W1AW", "2m", "FN42", "FT8")
    assert again.is_dupe is True and again.is_new_mult is False
    assert again.chase == ""
    assert "FN42" in again.need_reason
    assert "unconfirmed" not in again.need_reason


def test_worked_unconfirmed_new_station_is_unconfirmed():
    store = _store(
        {"grid": {"enabled": True, "scope": "band"}},
        [_qso("K1ABC", "6m", "FN42", "FT8", confirmed=False)],
    )
    other = store.classify("W1AW", "6m", "FN42", "FT8")
    assert other.chase == "unconfirmed"
    assert other.is_dupe is False and other.is_new_mult is False
    assert "FN42" in other.need_reason
    assert "6m" in other.need_reason
    assert "worked but not confirmed" in other.need_reason
    assert row_visible(
        is_needed=not other.is_dupe, is_cq=True, message_tail="", mode="needed",
    )
    assert row_visible(
        is_needed=not other.is_dupe, is_cq=True, message_tail="", mode="needed-cq",
    )
    cand = build_candidate(_Decode("W1AW", "FN42"), "6m", store)
    assert cand.chase == "unconfirmed" and cand.is_dupe is False


def test_worked_unconfirmed_same_station_stays_not_needed():
    store = _store(
        {"grid": {"enabled": True, "scope": "band"}},
        [_qso("K1ABC", "6m", "FN42", "FT8")],
    )
    same = store.classify("K1ABC", "6m", "FN42", "FT8")
    assert same.is_dupe is True and same.chase == ""
    assert "unconfirmed" not in same.need_reason
    assert row_visible(
        is_needed=not same.is_dupe, is_cq=True, message_tail="73", mode="needed-73",
    ) is False


def test_per_band_unconfirmed_does_not_cover_another_band():
    rows = [_qso("K1ABC", "6m", "FN42", "FT8")]
    store = _store({"grid": {"enabled": True, "scope": "band"}}, rows)
    other_band = store.classify("W1AW", "2m", "FN42", "FT8")
    assert other_band.chase == "needed" and other_band.is_dupe is False
    assert "2m" in other_band.need_reason
    same_band = store.classify("W1AW", "6m", "FN42", "FT8")
    assert same_band.chase == "unconfirmed"
    # Confirmed on 6 m does not finish 2 m when the line is per band.
    done = _store(
        {"grid": {"enabled": True, "scope": "band"}},
        [_qso("K1ABC", "6m", "FN42", "FT8", confirmed=True)],
    )
    assert done.classify("W1AW", "6m", "FN42", "FT8").is_dupe is True
    still = done.classify("W1AW", "2m", "FN42", "FT8")
    assert still.chase == "needed" and still.is_dupe is False
    # Overall: one confirmed contact finishes the square on every band.
    overall = _store(
        {"grid": {"enabled": True, "scope": "overall"}},
        [_qso("K1ABC", "6m", "FN42", "FT8", confirmed=True)],
    )
    assert overall.classify("W1AW", "2m", "FN42", "FT8").is_dupe is True


def test_each_place_flags_a_new_station_when_unconfirmed():
    cases = (
        ("dxcc", "I1ABC", "JN45", None, "Italy"),
        ("state", "N1NEW", "FN20", "NH", "New Hampshire"),
        ("continent", "I1ABC", "JN45", None, "Europe"),
        ("cq", "DL1ABC", "JO62", None, "CQ zone 14"),
        ("itu", "DL1ABC", "JO62", None, "ITU zone 28"),
    )
    # Seed the "have" side with one unconfirmed US / Massachusetts / NA contact.
    seed = [_qso("K1ABC", "6m", "FN42", "FT8", state="MA", dxcc="291")]
    for kind, call, grid, state, words in cases:
        store = _store({kind: {"enabled": True, "scope": "overall"}}, seed)
        hit = store.classify(call, "6m", grid, "FT8", state=state)
        assert hit.chase == "needed", kind
        assert words in hit.need_reason
    # The seeded place itself, heard from someone else, is unconfirmed.
    heard = (
        ("dxcc", "W1AW", "FN31", None, "United States"),
        ("state", "K1ZZ", "FN42", "MA", "Massachusetts"),
        ("continent", "N1NEW", "FN20", None, "North America"),
        ("cq", "W1AW", "FN42", None, "CQ zone 5"),
        ("itu", "W1AW", "FN42", None, "ITU zone 8"),
        ("grid", "W1AW", "FN42", None, "FN42"),
    )
    for kind, call, grid, state, words in heard:
        store = _store({kind: {"enabled": True, "scope": "overall"}}, seed)
        hit = store.classify(call, "20m", grid, "FT8", state=state)
        assert hit.chase == "unconfirmed", (kind, hit.need_reason)
        assert words in hit.need_reason
        assert "worked but not confirmed" in hit.need_reason
        same = store.classify("K1ABC", "20m", "FN42", "FT8", state="MA")
        assert same.is_dupe is True and same.chase == "", kind


def test_awards_use_the_same_confirmation_rule():
    dxcc = _store(None, [_qso("K1ABC", "6m", "FN42", "FT8", dxcc="291")], award="dxcc")
    fresh = dxcc.classify("I1ABC", "6m", "JN45", "FT8")
    assert fresh.chase == "needed" and "Italy" in fresh.need_reason
    open_us = dxcc.classify("W1AW", "2m", "FN31", "FT8")
    assert open_us.chase == "unconfirmed"
    assert "United States" in open_us.need_reason
    assert dxcc.classify("K1ABC", "2m", "FN42", "FT8").is_dupe is True
    done = _store(
        None,
        [_qso("K1ABC", "6m", "FN42", "FT8", dxcc="291", confirmed=True)],
        award="dxcc",
    )
    assert done.classify("W1AW", "6m", "FN31", "FT8").is_dupe is True

    was = _store(None, [_qso("K1ABC", "6m", "FN42", "FT8", state="MA")], award="was")
    assert was.classify("K1ZZ", "6m", "FN42", "FT8", state="MA").chase == "unconfirmed"
    assert was.classify("N2NEW", "6m", "FN20", "FT8", state="NH").chase == "needed"

    vucc = _store(None, [_qso("K1ABC", "6m", "FN42", "FT8")], award="vucc")
    assert vucc.classify("W1AW", "2m", "FN42", "FT8").chase == "unconfirmed"
    assert vucc.classify("W1AW", "2m", "FN31", "FT8").chase == "needed"


def test_toggle_off_hides_unconfirmed_from_needed():
    store = _store(
        {"grid": {"enabled": True, "scope": "band"}},
        [_qso("K1ABC", "6m", "FN42", "FT8")],
        count_unconfirmed=False,
    )
    other = store.classify("W1AW", "6m", "FN42", "FT8")
    assert other.chase == "unconfirmed" and other.is_dupe is True
    assert row_visible(
        is_needed=not other.is_dupe, is_cq=True, message_tail="", mode="needed",
    ) is False
    assert row_visible(
        is_needed=not other.is_dupe, is_cq=False, message_tail="", mode="all",
    )
    # A brand-new square is still needed when the toggle is off.
    fresh = store.classify("W1AW", "6m", "FN31", "FT8")
    assert fresh.chase == "needed" and fresh.is_dupe is False
    choice = shape_choice({
        "schema": 5, "goal": "operating", "goal_id": "checklist", "explicit": True,
        "count_unconfirmed": False,
    })
    assert choice["count_unconfirmed"] is False
    missing = shape_choice({"schema": 5, "goal": "award", "goal_id": "vucc", "explicit": True})
    assert missing["count_unconfirmed"] is True


def test_new_call_is_not_an_unconfirmed_place():
    store = _store(
        {"call": {"enabled": True, "scope": "overall"}},
        [_qso("K1ABC", "6m", "FN42", "FT8")],
    )
    assert store.classify("K1ABC", "2m", "FN42", "FT8").is_dupe is True
    other = store.classify("W1AW", "6m", "FN42", "FT8")
    assert other.chase == "needed" and other.is_dupe is False


def test_setup_copy_names_the_toggle_and_the_roster_word():
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(encoding="utf-8")
    html = (ROOT / "src" / "wims" / "server" / "static" / "ops.html").read_text(encoding="utf-8")
    assert "Count worked but not confirmed as needed" in js
    assert "badge unconfirmed" in js or 'class="badge ' in js
    assert ">unconfirmed</span>" in js or "unconfirmed" in js
    assert "data-value=\"needed\"" in html
    assert "data-value=\"needed-cq\"" in html
    assert "data-value=\"needed-73\"" in html
    assert "data-value=\"all\"" in html
    for blob in (js, html):
        assert "python -m" not in blob
        assert "QSL_RCVD" not in blob
        assert "LOTW_QSL" not in blob


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
