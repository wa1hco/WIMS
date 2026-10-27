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

"""Plausible range from a station in FN42 (northeastern US).

These are "worth trying from here", not the theoretical horizon. Distance is
measured from the grid WSJT-X reports (FN42EV at this station). A spot past
``max_km`` is not listed. Inside the sweet spot the distance term is full.
MSK144 uses a meteor-scatter window: too close is as poor as too far.

The numbers are a choice for the operator to review. They are also written
in ``docs/plan/scoring.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BandRange:
    max_km: float
    sweet_lo: float
    sweet_hi: float
    min_km: float = 0.0


# HF skywave is long. VHF and UHF here are tropo, not EME.
RANGES = {
    "160m": BandRange(2500, 80, 1500),
    "80m": BandRange(5000, 150, 3000),
    "60m": BandRange(4000, 150, 2500),
    "40m": BandRange(12000, 400, 8000),
    "30m": BandRange(15000, 800, 12000),
    "20m": BandRange(18000, 1000, 16000),
    "17m": BandRange(18000, 1000, 16000),
    "15m": BandRange(18000, 1500, 16000),
    "12m": BandRange(16000, 1500, 14000),
    "10m": BandRange(16000, 1500, 14000),
    # 6000 km keeps a multi-hop Es path such as FN42 to IL18 (~5100 km,
    # Canary Islands) or IO91 (~5200 km). Central Europe (~6100 km) is past it.
    "6m": BandRange(6000, 400, 2500),
    "4m": BandRange(2500, 400, 1800),
    "2m": BandRange(900, 40, 600),
    "1.25m": BandRange(700, 30, 400),
    "70cm": BandRange(500, 20, 300),
    "33cm": BandRange(300, 10, 150),
    "23cm": BandRange(250, 5, 120),
    "13cm": BandRange(150, 5, 80),
}
DEFAULT_RANGE = BandRange(150, 5, 80)

# Meteor scatter. min_km drops a station that is too close for the mode.
MSK_RANGES = {
    "6m": BandRange(2200, 500, 1800, min_km=200),
    "2m": BandRange(2200, 400, 1600, min_km=200),
    "1.25m": BandRange(1800, 300, 1200, min_km=150),
    "70cm": BandRange(1500, 300, 1000, min_km=150),
}


def range_for(band: str, mode: str | None = None) -> BandRange:
    if (mode or "").upper() == "MSK144":
        found = MSK_RANGES.get(band)
        if found is not None:
            return found
    return RANGES.get(band, DEFAULT_RANGE)


def in_range(km: float | None, band: str, mode: str | None = None) -> bool:
    if km is None:
        return False
    spec = range_for(band, mode)
    return spec.min_km <= km <= spec.max_km


def distance_fit(km: float | None, band: str, mode: str | None = None) -> float:
    """1 inside the sweet spot, falling off toward the edges. 0 if unworkable."""
    if km is None:
        return 0.0
    spec = range_for(band, mode)
    if km < spec.min_km or km > spec.max_km:
        return 0.0
    if spec.sweet_lo <= km <= spec.sweet_hi:
        return 1.0
    if km < spec.sweet_lo:
        span = spec.sweet_lo - spec.min_km
        if span <= 0:
            return 1.0
        return 0.35 + 0.65 * ((km - spec.min_km) / span)
    span = spec.max_km - spec.sweet_hi
    if span <= 0:
        return 1.0
    return max(0.0, 1.0 - (km - spec.sweet_hi) / span)


def spotter_near_amount(km: float | None) -> float:
    """1 when the spotter is within 500 km of us, 0 at 2000 km and beyond."""
    if km is None:
        return 0.0
    if km <= 500:
        return 1.0
    if km >= 2000:
        return 0.0
    return (2000.0 - km) / 1500.0
