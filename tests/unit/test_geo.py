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

"""Maidenhead grid geometry — grid center + great-circle bearing (engine/geo.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.geo import grid_to_latlon, bearing  # noqa: E402


def test_grid_center_4char():
    # FN42: field F/N, square 4/2 -> center of the 2x1 deg square.
    lat, lon = grid_to_latlon("FN42")
    assert abs(lat - 42.5) < 1e-9 and abs(lon - (-71.0)) < 1e-9


def test_grid_center_6char_within_square():
    lat, lon = grid_to_latlon("FN42ab")
    assert 42.0 <= lat <= 43.0 and -72.0 <= lon <= -70.0


def test_malformed_grid_is_none():
    for g in (None, "", "F", "FN", "12AB", "FNXY"):
        assert grid_to_latlon(g) is None
    assert bearing("FN42", None) is None and bearing(None, "FN42") is None


def test_bearing_due_east_same_latitude():
    # Same latitude, one square (2 deg lon) east -> initial bearing ~90 deg.
    az = bearing("FN42", "FN52")
    assert az is not None and abs(az - 90.0) < 2.0


def test_bearing_due_north():
    az = bearing("FN42", "FN44")   # same longitude, two squares north
    assert az is not None and (az < 1.0 or az > 359.0)


def test_bearing_range():
    az = bearing("FN31", "FN42")
    assert 0.0 <= az < 360.0


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
