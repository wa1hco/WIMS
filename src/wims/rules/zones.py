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

"""CQ and ITU zone from a Maidenhead grid. Stdlib only.

The boxes are the interior of a zone, not the legal boundary. A square whose
sample points are not all inside the same box is zone uncertain. WIMS then
does not claim that zone is needed.

Sources, for the published boundaries these boxes approximate:

- CQ Magazine, Worked All Zones map and country list:
  https://cq-amateur-radio.com/cq_awards/cq_waz_awards/
- ITU geographic zones as used in amateur radio, drawn by EI8IC from the
  ITU zone boundaries: https://www.mapability.com/ei8ic/maps/ituzone.php

Single-zone DXCC entities take the zone from ``cty.dat`` and do not use this
table. Multi-zone entities use it only when the grid is known.
"""

from __future__ import annotations

# (lat_min, lat_max, lon_min, lon_max, zone). Closed intervals. Boxes do not
# overlap; a gap is uncertain on purpose.
_CQ_BOXES = (
    # Eastern US, south of the Great Lakes. CQ zone 5.
    (25.0, 41.5, -80.0, -67.0, 5),
    # New England. CQ zone 5. Stays east of southern Ontario.
    (41.5, 47.0, -76.0, -67.0, 5),
    # Southern Ontario. CQ zone 4.
    (42.0, 46.0, -84.0, -77.0, 4),
    # Central US plains, east of the Rockies. CQ zone 4.
    (26.0, 49.0, -104.0, -90.0, 4),
    # US and Canadian west coast. CQ zone 3.
    (32.0, 52.0, -125.0, -116.0, 3),
    # Southeast Brazil. The country is CQ zone 11.
    (-30.0, -15.0, -55.0, -40.0, 11),
    # Western Australia. CQ zone 29.
    (-35.0, -20.0, 114.0, 126.0, 29),
    # Southeastern Australia. CQ zone 30.
    (-40.0, -25.0, 140.0, 152.0, 30),
    # Eastern China. CQ zone 24.
    (22.0, 45.0, 108.0, 125.0, 24),
    # Western China. CQ zone 23.
    (35.0, 48.0, 75.0, 95.0, 23),
    # European Russia. CQ zone 16.
    (48.0, 62.0, 28.0, 50.0, 16),
    # Central Siberia, Novosibirsk. CQ zone 18.
    (50.0, 60.0, 78.0, 95.0, 18),
)

_ITU_BOXES = (
    # Eastern US. ITU zone 8.
    (25.0, 41.5, -80.0, -67.0, 8),
    (41.5, 47.0, -76.0, -67.0, 8),
    # Southern Ontario. ITU zone 4.
    (42.0, 46.0, -84.0, -77.0, 4),
    # Central US. ITU zone 7.
    (26.0, 45.0, -104.0, -90.0, 7),
    # Western US. ITU zone 6. Stops south of Vancouver.
    (32.0, 48.0, -125.0, -116.0, 6),
    # Southwest British Columbia. ITU zone 2.
    (48.5, 55.0, -128.0, -120.0, 2),
    # Southeast Brazil. ITU zone 15.
    (-30.0, -15.0, -52.0, -40.0, 15),
    # Western Australia. ITU zone 58.
    (-35.0, -20.0, 114.0, 126.0, 58),
    # Southeastern Australia. ITU zone 59.
    (-40.0, -28.0, 140.0, 152.0, 59),
    # Eastern China. ITU zone 44.
    (30.0, 45.0, 110.0, 125.0, 44),
    # Western China. ITU zone 33.
    (35.0, 48.0, 75.0, 95.0, 33),
    # Moscow. ITU zone 29.
    (50.0, 60.0, 30.0, 48.0, 29),
    # Novosibirsk. ITU zone 31.
    (50.0, 60.0, 78.0, 95.0, 31),
)


def _square(grid: str | None) -> str | None:
    g = (grid or "").strip().upper()
    if len(g) < 4:
        return None
    if not (g[0].isalpha() and g[1].isalpha() and g[2].isdigit() and g[3].isdigit()):
        return None
    return g[:4]


def _samples(grid4: str) -> list[tuple[float, float]]:
    """Points inside the 2°×1° square, inset so a touching edge still counts."""
    lon0 = (ord(grid4[0]) - ord("A")) * 20.0 - 180.0 + int(grid4[2]) * 2.0
    lat0 = (ord(grid4[1]) - ord("A")) * 10.0 - 90.0 + int(grid4[3]) * 1.0
    eps = 0.02
    return [
        (lat0 + eps, lon0 + eps),
        (lat0 + eps, lon0 + 2.0 - eps),
        (lat0 + 1.0 - eps, lon0 + eps),
        (lat0 + 1.0 - eps, lon0 + 2.0 - eps),
        (lat0 + 0.5, lon0 + 1.0),
    ]


def _zone_at(lat: float, lon: float, boxes) -> int | None:
    hits = [
        zone
        for lat0, lat1, lon0, lon1, zone in boxes
        if lat0 <= lat <= lat1 and lon0 <= lon <= lon1
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def _from_grid(grid: str | None, boxes) -> int | None:
    """Zone when every sample of the square agrees. Otherwise None."""
    square = _square(grid)
    if not square:
        return None
    found: set[int] = set()
    for lat, lon in _samples(square):
        zone = _zone_at(lat, lon, boxes)
        if zone is None:
            return None
        found.add(zone)
    if len(found) == 1:
        return found.pop()
    return None


def cq_zone_from_grid(grid: str | None) -> int | None:
    """CQ zone, or None when the square is missing, in a gap, or on a boundary."""
    return _from_grid(grid, _CQ_BOXES)


def itu_zone_from_grid(grid: str | None) -> int | None:
    """ITU zone, or None when the square is missing, in a gap, or on a boundary."""
    return _from_grid(grid, _ITU_BOXES)
