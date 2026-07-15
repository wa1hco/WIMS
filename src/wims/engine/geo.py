"""Maidenhead grid geometry — pure helpers for antenna pointing (plan §3.14 / §2.2).

The roster's "az" column is the great-circle **initial bearing** from the receiving
instance's own grid (WSJT-X `de_grid`) to the DX station's grid. Both come straight off
the WSJT-X messages, so nothing here needs station config. Keep these pure and
unit-testable: grid text in, degrees out, `None` when a grid is missing/malformed.
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


def bearing(from_grid: str | None, to_grid: str | None) -> float | None:
    """Great-circle initial bearing from `from_grid` to `to_grid`, degrees true
    [0, 360), or None if either grid is missing/malformed."""
    a = grid_to_latlon(from_grid)
    b = grid_to_latlon(to_grid)
    if a is None or b is None:
        return None
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
