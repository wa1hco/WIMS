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

"""Amateur band labels from frequency — shared by WSJT-X and N1MM paths.

WSJT-X reports dial frequency in Hz; N1MM reports band as MHz (e.g. 14.0). Both
normalize to a single band label ("20m", "6m", ...) so decodes and logged QSOs key
on the same band.
"""

from __future__ import annotations

# (lower edge Hz, label); pick the largest lower-bound <= freq.
_BANDS = [
    (1_800_000, "160m"), (3_500_000, "80m"), (5_330_000, "60m"), (7_000_000, "40m"),
    (10_100_000, "30m"), (14_000_000, "20m"), (18_068_000, "17m"), (21_000_000, "15m"),
    (24_890_000, "12m"), (28_000_000, "10m"), (50_000_000, "6m"), (70_000_000, "4m"),
    (144_000_000, "2m"), (222_000_000, "1.25m"), (420_000_000, "70cm"),
    (902_000_000, "33cm"), (1_240_000_000, "23cm"), (2_300_000_000, "13cm"),
]


BAND_ORDER = [name for _, name in _BANDS]   # low -> high frequency (160m … 13cm)


def band_sort_key(label: str) -> int:
    """Frequency-order index for a band label ("6m" < "2m" < "70cm"); unknown last."""
    return BAND_ORDER.index(label) if label in BAND_ORDER else len(BAND_ORDER)


def band_label(freq_hz: float) -> str:
    label = "?"
    for low, name in _BANDS:
        if freq_hz >= low:
            label = name
        else:
            break
    return label


def band_label_mhz(mhz: float) -> str:
    """N1MM-style band in MHz (14.0) -> label."""
    return band_label(int(round(mhz * 1_000_000)))
