# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The needed badge names one place. The mult badge stays mult.

Priority, most specific first: grid, state, DXCC, CQ zone, ITU zone,
continent, call. A new call is last because it is not a multiplier.
The score adds the new-mult weight once.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.goal_rules import (  # noqa: E402
    NEED_LABEL,
    NEED_LABEL_PRIORITY,
    AwardRules,
    ChecklistRules,
)
from wims.engine.scoring import Context, build_candidate, get_strategy  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.lotw import use_paths  # noqa: E402
from wims.rules.cty import CtyIndex  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.udp import encode as E, messages as M  # noqa: E402

use_paths([])

ROOT = Path(__file__).resolve().parents[2]

# A small country file. Not a copy of cty.dat.
_CTY = """\
United States:5:8:NA:43.00:-87.90:0.0:K:
    K,W,N,AA;
Italy:15:28:EU:42.00:12.00:0.0:I:
    I;
Federal Republic of Germany:14:28:EU:51.00:10.00:0.0:DL:
    DL,DA;
"""

_ALL = {
    "grid": {"enabled": True, "scope": "overall"},
    "state": {"enabled": True, "scope": "overall"},
    "dxcc": {"enabled": True, "scope": "overall"},
    "continent": {"enabled": True, "scope": "overall"},
    "cq": {"enabled": True, "scope": "overall"},
    "itu": {"enabled": True, "scope": "overall"},
    "call": {"enabled": True, "scope": "overall"},
}


def _cty():
    return CtyIndex.parse(_CTY)


def _qso(call, band, grid, mode="FT8", *, state=None, confirmed=True):
    return LoggedQso(
        id=f"{call}-{band}-{mode}-{grid or ''}-{state or ''}-{int(confirmed)}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp="",
        operator="", rover_location=None, source="test",
        state=state, confirmed=confirmed,
    )


def _store(items, rows, *, cty=True):
    store = LogStore(":memory:")
    store.rules = ChecklistRules(
        items, title="Checklist",
        cty=_cty() if cty else None,
        log_label="the log",
    )
    for row in rows:
        store.upsert(row)
    return store


def _decode(call, grid, mode="FT8", snr=-10):
    return M.parse(E.build_decode(
        "SIM-6M", time_ms=0, snr=snr, delta_time=0.1,
        delta_frequency=1500, mode=mode,
        message=f"CQ {call} {grid}",
    ))


def test_priority_is_specific_place_then_call():
    assert NEED_LABEL_PRIORITY == (
        "grid", "state", "dxcc", "cq", "itu", "continent", "call",
    )
    assert NEED_LABEL["grid"] == "grid"
    assert NEED_LABEL["state"] == "state"
    assert NEED_LABEL["dxcc"] == "DXCC"
    assert NEED_LABEL["cq"] == "CQ zone"
    assert NEED_LABEL["itu"] == "ITU zone"
    assert NEED_LABEL["continent"] == "continent"
    assert NEED_LABEL["call"] == "call"
    assert NEED_LABEL["was"] == "state"
    assert NEED_LABEL["vucc"] == "grid"
    # County and prefix are not computed, so they are not labels.
    assert "county" not in NEED_LABEL_PRIORITY
    assert "prefix" not in NEED_LABEL_PRIORITY


def test_several_new_places_show_grid_only():
    store = _store(_ALL, [])
    hit = store.classify("DL1ABC", "6m", "JO62", "FT8")
    assert hit.chase == "needed"
    assert hit.need_label == "grid"
    assert hit.is_new_mult is True
    assert "JO62" in hit.need_reason
    assert "JO62" in hit.mult_reason
    for other in ("Germany", "Europe", "CQ zone", "ITU zone", "new call"):
        assert other not in hit.need_reason, other
        assert other not in hit.mult_reason, other


def test_state_wins_when_the_grid_is_already_worked():
    store = _store(
        {
            "grid": {"enabled": True, "scope": "overall"},
            "state": {"enabled": True, "scope": "overall"},
            "dxcc": {"enabled": True, "scope": "overall"},
            "call": {"enabled": True, "scope": "overall"},
        },
        [_qso("K1ABC", "6m", "FN42", state="MA")],
    )
    hit = store.classify("N1NEW", "6m", "FN42", "FT8", state="NH")
    assert hit.need_label == "state"
    assert hit.chase == "needed"
    assert hit.is_new_mult is True
    assert "New Hampshire" in hit.need_reason
    assert "new call" not in hit.need_reason
    assert "United States" not in hit.need_reason


def test_dxcc_wins_over_zone_continent_and_call():
    store = _store(
        {
            "dxcc": {"enabled": True, "scope": "overall"},
            "continent": {"enabled": True, "scope": "overall"},
            "cq": {"enabled": True, "scope": "overall"},
            "itu": {"enabled": True, "scope": "overall"},
            "call": {"enabled": True, "scope": "overall"},
        },
        [],
    )
    hit = store.classify("I1ABC", "20m", "JN45", "FT8")
    assert hit.need_label == "DXCC"
    assert hit.is_new_mult is True
    assert "Italy" in hit.need_reason
    assert "continent" not in hit.need_reason.lower()
    assert "CQ zone" not in hit.need_reason
    assert "new call" not in hit.need_reason


def test_call_is_the_label_when_every_place_is_worked():
    assert _cty().entity_name("DL2ABC") == "Federal Republic of Germany"
    store = _store(_ALL, [_qso("DL1ABC", "6m", "JO62")])
    hit = store.classify("DL2ABC", "6m", "JO62", "FT8")
    assert hit.need_label == "call"
    assert hit.chase == "needed"
    assert hit.is_dupe is False
    assert hit.is_new_mult is False
    assert hit.mult_reason == ""
    assert "DL2ABC" in hit.need_reason


def test_per_band_and_per_mode_pick_the_line_that_is_new_there():
    banded = _store(
        {
            "grid": {"enabled": True, "scope": "band"},
            "state": {"enabled": True, "scope": "overall"},
        },
        [_qso("K1ABC", "6m", "FN42", state="MA")],
    )
    other_band = banded.classify("N1NEW", "2m", "FN42", "FT8", state="MA")
    assert other_band.need_label == "grid"
    assert "2m" in other_band.need_reason
    assert "Massachusetts" not in other_band.need_reason
    same_band = banded.classify("N1NEW", "6m", "FN42", "FT8", state="VT")
    assert same_band.need_label == "state"
    assert "Vermont" in same_band.need_reason
    assert "6m" not in same_band.need_reason

    modes = _store(
        {"call": {"enabled": True, "scope": "mode"}},
        [_qso("K1ABC", "6m", "FN42", "FT8")],
        cty=False,
    )
    other_mode = modes.classify("K1ABC", "6m", "FN42", "FT4")
    assert other_mode.need_label == "call"
    assert "FT4" in other_mode.need_reason
    same_mode = modes.classify("K1ABC", "6m", "FN42", "FT8")
    assert same_mode.chase == ""
    assert same_mode.need_label == ""
    assert same_mode.is_dupe is True


def test_awards_use_their_one_category():
    dxcc = LogStore(":memory:")
    dxcc.rules = AwardRules("dxcc", dxcc_lookup=lambda c: {
        "I1ABC": "Italy", "K1ABC": "United States", "W1AW": "United States",
    }.get((c or "").upper()), log_label="the log")
    fresh = dxcc.classify("I1ABC", "6m", "JN45", "FT8")
    assert fresh.need_label == "DXCC" and fresh.chase == "needed"
    dxcc.upsert(_qso("K1ABC", "6m", "FN42", confirmed=False))
    open_us = dxcc.classify("W1AW", "2m", "FN31", "FT8")
    assert open_us.chase == "unconfirmed"
    assert open_us.need_label == ""

    was = LogStore(":memory:")
    was.rules = AwardRules("was", log_label="the log")
    state = was.classify("N1NEW", "6m", "FN20", "FT8", state="NH")
    assert state.need_label == "state" and state.chase == "needed"

    vucc = LogStore(":memory:")
    vucc.rules = AwardRules("vucc", log_label="the log")
    grid = vucc.classify("N1NEW", "2m", "FN31", "FT8")
    assert grid.need_label == "grid" and grid.chase == "needed"


def test_unconfirmed_keeps_its_word():
    store = _store(
        {"grid": {"enabled": True, "scope": "overall"}},
        [_qso("K1ABC", "6m", "FN42", confirmed=False)],
        cty=False,
    )
    hit = store.classify("W1AW", "20m", "FN42", "FT8")
    assert hit.chase == "unconfirmed"
    assert hit.need_label == ""


def test_score_adds_new_mult_once():
    wide = _store(_ALL, [])
    grid_only = _store({"grid": {"enabled": True, "scope": "overall"}}, [])
    dec = _decode("DL1ABC", "JO62")
    many = build_candidate(dec, "6m", wide)
    one = build_candidate(dec, "6m", grid_only)
    assert many.need_label == "grid" and one.need_label == "grid"
    assert many.is_new_mult is True and one.is_new_mult is True
    strat = get_strategy()
    ctx = Context()
    scored_many = strat.score(many, ctx)
    scored_one = strat.score(one, ctx)
    assert scored_many.excluded is False and scored_one.excluded is False
    assert scored_many.total == scored_one.total
    assert sum(1 for f in scored_many.factors if f.name == "new_mult") == 1
    assert sum(1 for f in scored_one.factors if f.name == "new_mult") == 1

    worked = _store(_ALL, [_qso("DL1ABC", "6m", "JO62")])
    call_only = build_candidate(_decode("DL2ABC", "JO62"), "6m", worked)
    assert call_only.need_label == "call"
    assert call_only.is_new_mult is False
    scored_call = strat.score(call_only, ctx)
    assert scored_many.total > scored_call.total
    assert not any(f.name == "new_mult" for f in scored_call.factors)


def test_contest_row_leaves_the_place_badge_off():
    store = LogStore(":memory:")
    assert store.rules.id == "arrl-vhf"
    hit = store.classify("N1NEW", "6m", "FN31", "FT8")
    assert hit.is_dupe is False
    assert hit.is_new_mult is True
    assert hit.chase == ""
    assert hit.need_label == ""
    assert "FN31" in hit.mult_reason


def test_roster_json_carries_one_label():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status(
        "SIM-6M", 50_313_000, mode="FT8", de_call="WA1HCO", de_grid="FN31",
        decoding=True,
    )), now=1.0, src_ip="10.0.0.8")
    live.observe_wsjtx(M.parse(E.build_decode(
        "SIM-6M", time_ms=0, snr=-8, delta_time=0.2,
        delta_frequency=800, mode="FT8", message="CQ K1ABC FN42",
    )), now=1.1, src_ip="10.0.0.8")
    contest = next(c for c in live.snapshot(2.0)["roster"]["candidates"] if c["call"] == "K1ABC")
    assert contest["is_new_mult"] is True
    assert contest["chase"] == ""
    assert contest["need_label"] == ""

    live._log.rules = ChecklistRules(
        {
            "grid": {"enabled": True, "scope": "band"},
            "state": {"enabled": True, "scope": "overall"},
            "dxcc": {"enabled": True, "scope": "band"},
            "call": {"enabled": True, "scope": "band"},
        },
        title="Checklist",
        log_label="the log",
    )
    row = next(c for c in live.snapshot(2.5)["roster"]["candidates"] if c["call"] == "K1ABC")
    assert row["chase"] == "needed"
    assert row["need_label"] == "grid"
    assert row["is_new_mult"] is True
    assert "FN42" in row["need_reason"]
    assert sum(1 for f in row["factors"] if f["name"] == "new_mult") == 1


def test_badge_text_uses_the_label_and_mult_stays_mult():
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(encoding="utf-8")
    call = js.split("function rosCall", 1)[1].split("function rosChase", 1)[0]
    assert ">mult</span>" in call
    assert "need_label" not in call
    chase = js.split("function rosChase", 1)[1].split("function rosCountryTip", 1)[0]
    assert "need_label" in chase
    assert "unconfirmed" in chase
    assert '"needed"' in chase


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
