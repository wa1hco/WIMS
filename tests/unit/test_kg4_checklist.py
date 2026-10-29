# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""KG4LDK on 10 m is not a new grid and not a new DXCC multiplier.

Just operating with DXCC per band and grid overall. The country file lists
the prefix KG4 under Guantanamo Bay. A three-letter suffix is a United
States call. EM85 is already in the log, on 10 m and on 6 m. The call line
is off. A single remembered square is not "grid assumed".
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.goal_rules import ChecklistRules  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.lotw import use_paths  # noqa: E402
from wims.rules.cty import CtyIndex  # noqa: E402
from wims.state.heard_grids import HeardGrids  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

use_paths([])

# Tiny country file. Not a copy of cty.dat. KG4V is an exact US call with a
# one-letter suffix. KG4NE is an exact Guantanamo call. KG4HZF is an exact
# call under another entity, so the three-letter rule must not steal it.
_CTY = """\
United States:5:8:NA:43.00:-87.90:0.0:K:
    K,W,N,AA,=KG4V(4)[8];
Guantanamo Bay:8:11:NA:20.00:-75.00:0.0:KG4:
    KG4,=KG4NE;
Alaska:1:1:NA:61.00:-150.00:0.0:KL:
    KL,=KG4HZF;
"""

# The field checklist: DXCC per band, grid overall, state per band, call off.
_ITEMS = {
    "dxcc": {"enabled": True, "scope": "band"},
    "grid": {"enabled": True, "scope": "overall"},
    "state": {"enabled": True, "scope": "band"},
    "call": {"enabled": False, "scope": "overall"},
}


def _qso(call, band, grid, mode="FT8"):
    return LoggedQso(
        id=f"{call}-{band}-{mode}-{grid}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="", timestamp="2023-07-09 02:04:15",
        operator="", rover_location=None, source="test",
    )


def _store():
    cty = CtyIndex.parse(_CTY)
    store = LogStore(":memory:")
    store.rules = ChecklistRules(
        _ITEMS, title="Checklist", cty=cty, log_label="the log",
    )
    # United States on 10 m, and EM85 on 10 m and on 6 m. KG4LKY is an
    # ordinary three-letter KG4 call, so it must count as the United States
    # and must not satisfy Guantanamo Bay.
    for row in (
        _qso("W1AW", "10m", "FN42"),
        _qso("KN4FLO", "10m", "EM85"),
        _qso("N0SIX", "6m", "EM85"),
        _qso("KG4LKY", "10m", "EM87"),
    ):
        store.upsert(row)
    return store


def test_three_letter_kg4_is_united_states():
    cty = CtyIndex.parse(_CTY)
    assert cty.entity_name("KG4LDK") == "United States"
    assert cty.entity_name("KG4LDK/P") == "United States"
    assert cty.entity_name("KG4AA") == "Guantanamo Bay"
    assert cty.entity_name("KG4NE") == "Guantanamo Bay"
    assert cty.entity_name("W1AW/KG4") == "Guantanamo Bay"
    assert cty.entity_name("KG4V") == "United States"
    assert cty.entity_name("KG4HZF") == "Alaska"
    us = cty.describe("KG4LDK", "FN42")
    assert us.continent == "NA" and us.cq == 5 and us.itu == 8
    gtmo = cty.describe("KG4AA", "FN42")
    assert gtmo.cq == 8 and gtmo.itu == 11


def test_kg4ldk_on_10m_is_not_a_new_mult_or_a_needed_grid():
    verdict = _store().classify("KG4LDK", "10m", "EM85", "FT8")
    assert verdict.is_new_mult is False
    assert verdict.chase != "needed"
    assert verdict.mult_reason == ""
    text = f"{verdict.need_reason} {verdict.mult_reason}"
    assert "Guantanamo" not in text
    assert "new grid" not in text.lower()
    assert "EM85" not in verdict.mult_reason
    # The United States on 10 m is in the log and not confirmed, so the
    # badge is unconfirmed. It is not a new entity and not a new grid.
    assert verdict.chase == "unconfirmed"
    assert "United States" in verdict.need_reason
    assert "10m" in verdict.need_reason

    # A six-character square is the same four-character grid.
    finer = _store().classify("KG4LDK", "10m", "EM85xx", "FT8")
    assert finer.is_new_mult is False
    assert finer.chase != "needed"
    assert "new grid" not in finer.need_reason.lower()


def test_short_kg4_on_10m_is_still_guantanamo():
    # EM85 is already in the log, so the badge is the new entity.
    # A new square would be the more specific label and would hide this.
    verdict = _store().classify("KG4AA", "10m", "EM85", "FT8")
    assert verdict.is_new_mult is True
    assert verdict.chase == "needed"
    assert verdict.need_label == "DXCC"
    assert "Guantanamo Bay" in verdict.need_reason
    assert "Guantanamo Bay" in verdict.mult_reason
    assert "10m" in verdict.mult_reason


def test_one_square_kg4ldk_is_not_grid_assumed():
    body = {
        "schema": 1,
        "calls": {
            "KG4LDK": {
                "history": [{
                    "grid": "EM85",
                    "first_utc": "2026-10-20T19:52:59Z",
                    "last_utc": "2026-10-27T20:05:26Z",
                    "first_band": "10m",
                    "last_band": "10m",
                }],
            },
        },
    }
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "heard_grids.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        store = HeardGrids(path)
    when = datetime(2026, 10, 27, 20, 5, 26, tzinfo=timezone.utc).timestamp()
    found = store.lookup("KG4LDK", when)
    assert found.grid == "EM85"
    assert found.remembered is True
    assert found.assumed is False
    assert "grid assumed" not in found.tip.lower()


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
