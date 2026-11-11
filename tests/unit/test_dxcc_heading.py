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

"""Approximate Az DX from a DXCC entity centroid when no grid is known."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.contest_rules import load_builtin  # noqa: E402
from wims.lotw import use_paths  # noqa: E402
from wims.engine.geo import (  # noqa: E402
    aim, bearing, bearing_latlon, bearing_to_latlon, distance_km,
    distance_km_latlon, grid_to_latlon,
)
from wims.engine.goal_rules import AwardRules, ChecklistRules  # noqa: E402
from wims.integrations.cluster.view import build_list  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.rules.cty import CtyIndex, _parse_primary  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

# Official country-file layout: longitude is positive west.
_CTY = """\
United States:            05:  08:  NA:   37.60:    91.87:     5.0:  K:
    K,W,N,AA,K1,W1,N1;
England:                  14:  27:  EU:   52.77:     1.47:     0.0:  G:
    G,G4,M;
Japan:                    25:  45:  AS:   36.40:  -138.38:    -9.0:  JA:
    JA,JE,JF,JG,JH,JI,JJ,JK,JL,JM,JN,JO,JP,JQ,JR,JS;
Canada:                   05:  09:  NA:   44.35:    78.75:     5.0:  VE:
    VE,VA,VO,VY;
"""

HOME = "FN42"
NOW = 1_700_000_000.0

use_paths([])


def _cty():
    return CtyIndex.parse(_CTY)


def test_parse_primary_positive_west_longitude():
    # United States in the official file is 91.87 west → 91.87°W, lon east -91.87.
    ent = _parse_primary(
        "United States:            05:  08:  NA:   37.60:    91.87:     5.0:  K:"
    )
    assert ent is not None
    assert abs(ent.lat - 37.60) < 1e-9
    assert abs(ent.lon_west - 91.87) < 1e-9
    # Japan is written negative, meaning east of Greenwich.
    jp = _parse_primary(
        "Japan:                    25:  45:  AS:   36.40:  -138.38:    -9.0:  JA:"
    )
    assert jp is not None
    assert abs(jp.lat - 36.40) < 1e-9
    assert abs(jp.lon_west - (-138.38)) < 1e-9
    # A short line with no coordinates still parses.
    short = _parse_primary("United States:5:8:NA:")
    assert short is not None and short.lat is None and short.lon_west is None


def test_centroid_flips_west_positive_longitude():
    idx = _cty()
    us = idx.centroid("K1ABC")
    assert us is not None
    assert abs(us[0] - 37.60) < 1e-9
    assert abs(us[1] - (-91.87)) < 1e-9
    en = idx.centroid("G4ABC")
    assert en is not None
    assert abs(en[0] - 52.77) < 1e-9
    assert abs(en[1] - (-1.47)) < 1e-9
    jp = idx.centroid("JA1ABC")
    assert jp is not None
    assert abs(jp[0] - 36.40) < 1e-9
    assert abs(jp[1] - 138.38) < 1e-9
    assert idx.centroid("ZZ9ZZ") is None
    assert idx.centroid("") is None


def test_bearing_from_fn42_to_known_entities():
    idx = _cty()
    expected = {
        "K1ABC": 259.896,
        "G4ABC": 51.922,
        "JA1ABC": 336.573,
        "VE3ABC": 290.834,
    }
    for call, want in expected.items():
        lat, lon = idx.centroid(call)
        az = bearing_to_latlon(HOME, lat, lon)
        assert az is not None
        assert abs(az - want) < 0.05, (call, az, want)


def test_aim_order_grid_then_heard_then_dxcc():
    idx = _cty()
    latlon = idx.centroid("G4ABC")
    az, km, src = aim(HOME, "FN20")
    assert src == "grid"
    assert az == bearing(HOME, "FN20")
    assert km == distance_km(HOME, "FN20")
    az, km, src = aim(HOME, None, heard_grid="FN20")
    assert src == "heard"
    assert az == bearing(HOME, "FN20")
    az, km, src = aim(HOME, "FN20", remembered=True)
    assert src == "heard"
    assert az == bearing(HOME, "FN20")
    az, km, src = aim(HOME, "JO01", heard_grid="FN20", remembered=True)
    assert src == "heard"
    assert az == bearing(HOME, "FN20")
    az, km, src = aim(HOME, None, entity_latlon=latlon)
    assert src == "dxcc"
    assert abs(az - 51.922) < 0.05
    assert km is not None and km > 4000
    # No home grid: stay blank, even when a centroid is known.
    assert aim(None, None, entity_latlon=latlon) == (None, None, None)
    assert aim("", None, entity_latlon=latlon) == (None, None, None)
    # Missing country file / no centroid: blank heading, still no grid invented.
    assert aim(HOME, None, entity_latlon=None) == (None, None, None)


def test_bearing_latlon_matches_grid_helpers():
    a = grid_to_latlon("FN42")
    b = grid_to_latlon("FN52")
    assert abs(bearing_latlon(a[0], a[1], b[0], b[1]) - bearing("FN42", "FN52")) < 1e-9
    assert abs(distance_km_latlon(a[0], a[1], b[0], b[1]) - distance_km("FN42", "FN52")) < 1e-9


def _hear(live, message, now, *, mid="SIM-20M", hz=14_074_000, grid="FN42"):
    live.observe_wsjtx(
        M.parse(E.build_status(mid, hz, mode="FT8", de_call="W1XX", de_grid=grid)),
        now, "127.0.0.1", 2237,
    )
    live.observe_wsjtx(
        M.parse(E.build_decode(
            mid, time_ms=1000, snr=-8, delta_time=0.2, delta_frequency=1200,
            message=message,
        )),
        now, "127.0.0.1", 2237,
    )


def test_roster_no_grid_uses_entity_heading_and_keeps_grid_empty():
    live = LiveFleet()
    idx = _cty()
    live._country_index = lambda: idx
    now = time.time()
    _hear(live, "CQ G4ABC", now)
    row = next(c for c in live.snapshot(now)["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row["grid"] in (None, "")
    assert row["grid_remembered"] is False
    assert row["grid_assumed"] is False
    assert row["bearing_source"] == "dxcc"
    assert row["az"] == 52  # 51.922 rounded
    assert row["distance_km"] is not None
    assert "est_grid" not in row
    # A real grid still wins and is not marked approximate.
    _hear(live, "CQ G4ABC JO01", now + 1)
    row = next(c for c in live.snapshot(now + 1)["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row["grid"] == "JO01"
    assert row["bearing_source"] == "grid"
    assert row["az"] == round(bearing(HOME, "JO01"))


def test_roster_heard_grid_beats_entity_centroid():
    live = LiveFleet()
    idx = _cty()
    live._country_index = lambda: idx
    now = time.time()
    live._heard.note("G4ABC", "JO01", "20m", now - 30)
    _hear(live, "W1XX G4ABC R-10", now)
    row = next(c for c in live.snapshot(now)["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row["grid"] == "JO01"
    assert row["grid_remembered"] is True
    assert row["bearing_source"] == "heard"
    assert row["az"] == round(bearing(HOME, "JO01"))


def test_roster_blank_heading_without_cty_or_home_grid():
    live = LiveFleet()
    live._country_index = lambda: None
    now = time.time()
    _hear(live, "CQ G4ABC", now)
    row = next(c for c in live.snapshot(now)["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row["grid"] in (None, "")
    assert row["az"] is None
    assert row["bearing_source"] is None
    live2 = LiveFleet()
    live2._country_index = lambda: _cty()
    _hear(live2, "CQ G4ABC", now, grid="")
    row2 = next(c for c in live2.snapshot(now)["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row2["az"] is None
    assert row2["bearing_source"] is None
    assert row2["grid"] in (None, "")


def test_classify_and_need_label_unchanged_without_a_centroid_grid():
    idx = _cty()
    store = LogStore(":memory:")
    dxcc = AwardRules("dxcc", dxcc_lookup=idx.entity_name, log_label="the log")
    vucc = AwardRules("vucc", log_label="the log")
    checks = ChecklistRules(
        {
            "dxcc": {"enabled": True, "scope": "overall"},
            "grid": {"enabled": True, "scope": "overall"},
        },
        title="Checklist", cty=idx, log_label="the log",
    )
    contest = load_builtin("arrl-vhf")

    # DXCC can need a station with no grid. The verdict must not invent one.
    v = dxcc.classify(store, "G4ABC", "20m", "FT8", None)
    assert v.is_dupe is False and v.chase == "needed" and v.need_label == "DXCC"
    # VUCC cannot.
    v = vucc.classify(store, "G4ABC", "2m", "FT8", None)
    assert v.is_dupe is True and not v.is_new_mult
    assert "No grid" in (v.need_reason or "")
    # Checklist: DXCC is still needed; grid stays unknown, not a fake square.
    v = checks.classify(store, "G4ABC", "20m", "FT8", None)
    assert v.chase == "needed" and v.need_label == "DXCC"
    assert v.is_new_mult is True
    # Contest grid multiplier is not new without a square.
    new_mult, reason = contest._new_mult(store, "2m", None, None)
    assert new_mult is False
    assert "No grid" in reason
    # A later grid still classifies the same as before this feature.
    v = vucc.classify(store, "K1NEW", "2m", "FT8", "FN31")
    assert v.chase == "needed" and v.need_label == "grid"


def test_cluster_shows_needed_dxcc_spot_without_inventing_a_grid():
    idx = _cty()
    store = LogStore(":memory:")
    store.rules = AwardRules("dxcc", dxcc_lookup=idx.entity_name, log_label="the log")
    seen = []

    def classify(call, band, grid, mode):
        seen.append(grid)
        return store.classify(call, band, grid, mode)

    from wims.integrations.cluster.parse import parse_spot
    from wims.integrations.cluster.view import SpotBook

    book = SpotBook()
    book.add(parse_spot("DX de K1TTT: 14074.0 G4ABC 1734Z"), NOW)
    rows, drops = build_list(
        book.rows(), now=NOW, ttl_s=15 * 60, our_grid=HOME, allowed=None,
        operations=[], classify=classify, entity_latlon=idx.centroid,
    )
    assert seen == [None]
    assert drops["no_grid"] == 0
    assert len(rows) == 1
    row = rows[0]
    assert row["call"] == "G4ABC"
    assert row["grid"] is None
    assert row["bearing_source"] == "dxcc"
    assert row["az"] == 52
    assert row["need_label"] == "DXCC"
    assert row["chase"] == "needed"
    assert "est_grid" not in row
    # A far VHF centroid must not be dropped as out of range.
    book2 = SpotBook()
    book2.add(parse_spot("DX de K1TTT: 144174.0 JA1ABC 1734Z"), NOW)
    far, far_drops = build_list(
        book2.rows(), now=NOW, ttl_s=15 * 60, our_grid=HOME, allowed=None,
        operations=[], classify=classify, entity_latlon=idx.centroid,
    )
    assert far_drops["range"] == 0
    assert far and far[0]["bearing_source"] == "dxcc"
    assert far[0]["grid"] is None


def test_cluster_still_drops_no_grid_under_vucc_and_contest():
    idx = _cty()
    vucc = LogStore(":memory:")
    vucc.rules = AwardRules("vucc", log_label="the log")
    contest = LogStore(":memory:")
    contest.rules = load_builtin("arrl-vhf")
    grid_only = LogStore(":memory:")
    grid_only.rules = ChecklistRules(
        {"grid": {"enabled": True, "scope": "overall"}},
        title="Checklist", cty=idx, log_label="the log",
    )
    from wims.integrations.cluster.parse import parse_spot
    from wims.integrations.cluster.view import SpotBook

    def _run(store):
        book = SpotBook()
        book.add(parse_spot("DX de K1TTT: 144174.0 G4ABC 1734Z"), NOW)
        return build_list(
            book.rows(), now=NOW, ttl_s=15 * 60, our_grid=HOME, allowed=None,
            operations=[], classify=store.classify, entity_latlon=idx.centroid,
        )

    for store in (vucc, contest, grid_only):
        rows, drops = _run(store)
        assert rows == [], store.rules
        assert drops["no_grid"] == 1
        assert drops["range"] == 0


def test_point_rotator_sets_approximate_flag():
    live = LiveFleet()
    idx = _cty()
    live._country_index = lambda: idx
    live._rotators.ensure_sim("ROT-20M", az=30, instances=["SIM-20M"])
    now = time.time()
    _hear(live, "CQ G4ABC", now, mid="SIM-20M")
    snap = live.snapshot(now)
    row = next(c for c in snap["roster"]["candidates"] if c["call"] == "G4ABC")
    assert row["bearing_source"] == "dxcc"
    result = live.point_rotator(row_id=row["id"])
    assert result["ok"]
    assert result.get("approximate") is True
    assert result.get("bearing_source") == "dxcc"
    assert result.get("az") == 52
    assert "Approximate heading from England" in (result.get("detail") or "")
    # A real grid is not marked approximate.
    _hear(live, "CQ K1ABC FN31", now + 1, mid="SIM-20M")
    snap = live.snapshot(now + 1)
    keyed = next(c for c in snap["roster"]["candidates"] if c["call"] == "K1ABC")
    result = live.point_rotator(row_id=keyed["id"])
    assert result["ok"]
    assert result.get("approximate") is False
    assert result.get("bearing_source") == "grid"


def test_js_marks_approximate_heading():
    root = Path(__file__).resolve().parents[2]
    js = (root / "src/wims/server/static/wims.js").read_text(encoding="utf-8")
    assert 'bearing_source === "dxcc"' in js
    assert 'function azText' in js
    assert '? "~"' in js or "? '~'" in js
    assert 'Approximate " + what + " from' in js or "Approximate heading from" in js
    assert "(country file)" in js
    assert "function rosKm" in js


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
