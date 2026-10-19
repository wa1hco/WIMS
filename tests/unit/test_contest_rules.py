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

"""Rules engine: NYQP, ARRL VHF (unchanged verdicts), WSJT-X Colors fallback."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.contest_rules import (  # noqa: E402
    WsjtxColors,
    default_color_categories,
    load_builtin,
    resolve,
    suggest_contest,
)
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402


def _qso(call, band, grid, mode, *, my_county="", qid=None):
    return LoggedQso(
        id=qid or f"{call}-{band}-{mode}-{my_county}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp="",
        operator="", rover_location=None, source="test",
        my_county=my_county or None,
    )


def test_arrl_vhf_still_dupes_fixed_and_frees_rover():
    store = LogStore(":memory:")
    assert store.rules.id == "arrl-vhf"
    store.upsert(_qso("K1ABC", "6m", "FN42", "FT8"))
    store.upsert(_qso("K1ROV/R", "6m", "FN42", "FT8", qid="rov"))
    assert store.is_dupe("K1ABC", "6m", "FN31") is True
    assert store.is_dupe("K1ABC", "2m", "FN42") is False
    assert store.is_dupe("K1ROV/R", "6m", "FN42") is True
    assert store.is_dupe("K1ROV/R", "6m", "FN31") is False
    assert store.is_new_mult("FN31", "6m") is True
    assert store.is_new_mult("FN42", "6m") is False


def test_nyqp_phone_and_digital_same_band_are_not_dupes():
    store = LogStore(":memory:")
    store.rules = load_builtin("nyqp")
    store.station_county = "ALBA"
    store.upsert(_qso("K1ABC", "6m", "FN42", "SSB", my_county="ALBA"))
    assert store.is_dupe("K1ABC", "6m", "FN42", mode="RTTY") is False
    assert store.is_dupe("K1ABC", "6m", "FN42", mode="USB") is True
    v = store.classify("K1ABC", "6m", "FN42", "RTTY")
    assert v.is_dupe is False
    assert "digital" in v.need_reason


def test_nyqp_two_digital_modes_on_one_band_are_a_dupe():
    store = LogStore(":memory:")
    store.rules = load_builtin("nyqp")
    store.upsert(_qso("K1ABC", "6m", "FN42", "RTTY", my_county="ALBA"))
    assert store.is_dupe("K1ABC", "6m", "FN42", mode="MSK144") is True
    assert store.is_dupe("K1ABC", "2m", "FN42", mode="RTTY") is False


def test_nyqp_ft8_is_banned_and_county_change_resets():
    store = LogStore(":memory:")
    store.rules = load_builtin("nyqp")
    store.station_county = "ALBA"
    store.upsert(_qso("K1ABC", "6m", "FN42", "SSB", my_county="ALBA"))
    banned = store.classify("N1NEW", "6m", "FN20", "FT8")
    assert banned.is_dupe is True
    assert banned.is_new_mult is False
    assert banned.points == 0
    assert "FT8 is not counted in NY QSO Party." in banned.need_reason
    assert store.classify("N1NEW", "6m", "FN20", "FT4").need_reason.startswith("FT4 is not counted")
    store.station_county = "ERIE"
    assert store.is_dupe("K1ABC", "6m", "FN42", mode="SSB") is False
    store.station_county = ""
    assert store.is_dupe("K1ABC", "6m", "FN42", mode="SSB") is True
    rules = load_builtin("nyqp")
    assert rules.qso_points("6m", "SSB")[0] == 1
    assert rules.qso_points("6m", "CW")[0] == 2
    assert rules.qso_points("6m", "RTTY")[0] == 3
    assert store.is_new_mult("FN20", "6m", call="N2NEW", mode="SSB") is False


def test_wsjtx_colors_highlight_by_mode_and_grid_mult():
    store = LogStore(":memory:")
    store.rules = WsjtxColors(
        categories={
            "new_call": False,
            "new_call_band": True,
            "new_grid": False,
            "new_grid_band": True,
            "new_dxcc": False,
            "new_dxcc_band": False,
        },
        highlight_by_mode=True,
        log_label="wsjtx_log.adi",
    )
    store.upsert(_qso("K1ABC", "6m", "FN20", "FT8"))
    worked = store.classify("K1ABC", "6m", "FN20", "FT8")
    assert worked.is_dupe is True
    assert "already in" in worked.need_reason
    assert "FN20" in worked.need_reason
    other_mode = store.classify("K1ABC", "6m", "FN20", "FT4")
    assert other_mode.is_dupe is False
    assert "New Call on Band" in other_mode.need_reason
    fresh = store.classify("N1NEW", "6m", "FN31", "FT8")
    assert fresh.is_dupe is False
    assert fresh.is_new_mult is True
    assert "New Grid on Band" in fresh.need_reason
    call_only = WsjtxColors(categories={
        "new_call": True, "new_call_band": False, "new_grid": False,
        "new_grid_band": False, "new_dxcc": False, "new_dxcc_band": False,
    })
    store.rules = call_only
    needed = store.classify("N1NEW", "6m", "FN31", "FT8")
    assert needed.is_dupe is False and needed.is_new_mult is False


def test_colors_fallback_without_cty_enables_call_and_grid():
    cats, note = default_color_categories(cty_ok=False)
    assert cats["new_dxcc"] is False
    assert cats["new_call"] is True and cats["new_grid_band"] is True
    assert "cty.dat was not found" in note
    factory, factory_note = default_color_categories(cty_ok=True)
    assert factory["new_dxcc"] is True and factory["new_call"] is False
    assert "default categories" in factory_note


def test_just_operating_stays_colors_on_any_log():
    # The log does not switch the rule. Colors is checked against the chosen log.
    n1mm = resolve({"contest": None, "explicit": True}, n1mm=True, cty_ok=False)
    assert n1mm.rules.id == "wsjtx-colors"
    assert n1mm.public["n1mm_authoritative"] is True
    assert "ARRL VHF" not in (n1mm.public.get("n1mm_line") or "")
    solo = resolve({"contest": None, "explicit": True}, n1mm=False, cty_ok=False)
    assert solo.rules.id == "wsjtx-colors"
    picked = resolve({"contest": "nyqp", "explicit": True}, n1mm=False)
    assert picked.rules.id == "nyqp"
    assert "once per band per mode group" in picked.public["summary"]


def test_suggestion_uses_alias_and_does_not_invent_a_date():
    sid, how = suggest_contest(["ARRLVHFJUN"])
    assert sid == "arrl-vhf" and how == "log"
    sid, how = suggest_contest(["NYQP"])
    assert sid == "nyqp" and how == "log"
    sid, how = suggest_contest([], today=__import__("datetime").date(2026, 9, 19))
    assert sid is None and how == ""
    kept = resolve(
        {"contest": None, "explicit": True},
        n1mm=True,
        contest_names=["NYQP"],
    )
    assert kept.rules.id == "wsjtx-colors"


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
