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

"""Maidenhead grid geometry — pure helpers for antenna pointing (plan §3.14 / §2.2).

The roster **Az DX** column is the great-circle **initial bearing** from the receiving
instance's own grid (WSJT-X `de_grid`) to the DX station. The first choice is a
real or remembered Maidenhead grid. When no grid is known, the heading may fall
back to the DXCC entity centroid from the country file. That heading is
approximate. This module never invents a grid square. **km** / **Δaz** helpers
live here too. Keep pure and unit-testable: `None` when missing or malformed.
"""

from __future__ import annotations

import math


def grid_to_latlon(grid: str | None) -> tuple[float, float] | None:
    """Center of a 4- or 6-char Maidenhead grid as (lat, lon) in degrees, else None.

    Returns the center of the square (4-char) or subsquare (6-char) so bearings are
    stable rather than pinned to a corner."""
    if not grid:
        return None
    g = grid.strip().upper()
    if len(g) < 4 or not (g[0].isalpha() and g[1].isalpha()
                          and g[2].isdigit() and g[3].isdigit()):
        return None
    lon = (ord(g[0]) - ord("A")) * 20.0 - 180.0 + int(g[2]) * 2.0
    lat = (ord(g[1]) - ord("A")) * 10.0 - 90.0 + int(g[3]) * 1.0
    if len(g) >= 6 and g[4].isalpha() and g[5].isalpha():
        lon += (ord(g[4]) - ord("A")) * (2.0 / 24.0) + (2.0 / 24.0) / 2.0
        lat += (ord(g[5]) - ord("A")) * (1.0 / 24.0) + (1.0 / 24.0) / 2.0
    else:                                   # center of the 2°×1° square
        lon += 1.0
        lat += 0.5
    return lat, lon


def _pair(lat, lon) -> tuple[float, float] | None:
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def bearing_latlon(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle initial bearing, degrees true [0, 360), or None if a value is bad.

    Longitudes are degrees east, the usual convention. A country-file longitude
    is positive-west and must be sign-flipped before it is passed here.
    """
    a = _pair(lat1, lon1)
    b = _pair(lat2, lon2)
    if a is None or b is None:
        return None
    phi1, lam1 = math.radians(a[0]), math.radians(a[1])
    phi2, lam2 = math.radians(b[0]), math.radians(b[1])
    dlon = lam2 - lam1
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def distance_km_latlon(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle distance in kilometres between two lat/lon points, or None."""
    a = _pair(lat1, lon1)
    b = _pair(lat2, lon2)
    if a is None or b is None:
        return None
    phi1, lam1 = math.radians(a[0]), math.radians(a[1])
    phi2, lam2 = math.radians(b[0]), math.radians(b[1])
    dlat = phi2 - phi1
    dlon = lam2 - lam1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlon / 2) ** 2)
    return 6371.0 * 2.0 * math.asin(min(1.0, math.sqrt(h)))


def bearing(from_grid: str | None, to_grid: str | None) -> float | None:
    """Great-circle initial bearing from `from_grid` to `to_grid`, degrees true
    [0, 360), or None if either grid is missing/malformed."""
    a = grid_to_latlon(from_grid)
    b = grid_to_latlon(to_grid)
    if a is None or b is None:
        return None
    return bearing_latlon(a[0], a[1], b[0], b[1])


def distance_km(from_grid: str | None, to_grid: str | None) -> float | None:
    """Great-circle distance between grid centers in kilometres, or None if bad grid."""
    a = grid_to_latlon(from_grid)
    b = grid_to_latlon(to_grid)
    if a is None or b is None:
        return None
    return distance_km_latlon(a[0], a[1], b[0], b[1])


def bearing_to_latlon(from_grid: str | None, lat, lon) -> float | None:
    """Bearing from a Maidenhead grid to a lat/lon (degrees east)."""
    a = grid_to_latlon(from_grid)
    if a is None:
        return None
    return bearing_latlon(a[0], a[1], lat, lon)


def distance_km_to_latlon(from_grid: str | None, lat, lon) -> float | None:
    """Distance in kilometres from a Maidenhead grid to a lat/lon (degrees east)."""
    a = grid_to_latlon(from_grid)
    if a is None:
        return None
    return distance_km_latlon(a[0], a[1], lat, lon)


def aim(de_grid: str | None, dx_grid: str | None = None, *,
        heard_grid: str | None = None,
        entity_latlon: tuple[float, float] | None = None,
        remembered: bool = False) -> tuple[float | None, float | None, str | None]:
    """Resolve Az DX and distance from the home grid.

    Order: a real DX grid, then a remembered or heard grid, then a DXCC entity
    centroid, then none. The third value is ``grid``, ``heard``, or ``dxcc``.
    A missing or unusable home grid returns all None. This never invents a
    grid square.
    """
    if grid_to_latlon(de_grid) is None:
        return None, None, None
    real = None if remembered else dx_grid
    heard = heard_grid if heard_grid else (dx_grid if remembered else None)
    if real:
        az = bearing(de_grid, real)
        if az is not None:
            return az, distance_km(de_grid, real), "grid"
    if heard:
        az = bearing(de_grid, heard)
        if az is not None:
            return az, distance_km(de_grid, heard), "heard"
    if entity_latlon is not None and len(entity_latlon) >= 2:
        az = bearing_to_latlon(de_grid, entity_latlon[0], entity_latlon[1])
        if az is not None:
            return (
                az,
                distance_km_to_latlon(de_grid, entity_latlon[0], entity_latlon[1]),
                "dxcc",
            )
    return None, None, None


def base_call(call: str | None) -> str:
    """Uppercase call with compound suffix stripped (``WA1HCO/R`` → ``WA1HCO``)."""
    if not call:
        return ""
    s = str(call).upper().replace("<", "").replace(">", "").strip()
    if not s or s in ("CQ", "QRZ", "DE"):
        return s
    return s.split("/", 1)[0]


def delta_az(az_ant: float | None, az_dx: float | None) -> float | None:
    """Shortest-arc absolute difference between antenna and DX azimuths, degrees [0, 180].

    Used as roster **Δaz** (how far off the beam is from the station).
    """
    if az_ant is None or az_dx is None:
        return None
    try:
        a = float(az_ant) % 360.0
        b = float(az_dx) % 360.0
    except (TypeError, ValueError):
        return None
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d
