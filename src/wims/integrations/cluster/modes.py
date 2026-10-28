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

"""Mode of a spot, from the comment first, then the frequency.

A cluster spot does not carry a WSJT-X mode field. The comment often says
FT8, FT4, MSK144, Q65, CW, or SSB. When it does not, a known watering hole
wins, and otherwise the US band segment (CW low, phone high) is the guess.
The operator is in FN42, so the segments follow the US plan. They are a
choice, written down in ``docs/plan/scoring.md``.

Comment wins over the frequency. ``USB`` and ``LSB`` are shown as SSB.
"""

from __future__ import annotations

import re

# Longer tokens first so MSK144 wins over MSK and FST4W over FST4.
_COMMENT = (
    ("MSK144", "MSK144"),
    ("FST4W", "FST4"),
    ("PSK31", "PSK"),
    ("RTTY", "RTTY"),
    ("WSPR", "WSPR"),
    ("JT65", "JT65"),
    ("FST4", "FST4"),
    ("FT8", "FT8"),
    ("FT4", "FT4"),
    ("Q65", "Q65"),
    ("JT9", "JT9"),
    ("JS8", "JS8"),
    ("USB", "SSB"),
    ("LSB", "SSB"),
    ("SSB", "SSB"),
    ("PHONE", "SSB"),
    ("DATA", "data"),
    ("DIGI", "data"),
    ("MSK", "MSK144"),
    ("CW", "CW"),
    ("FM", "FM"),
)
_COMMENT_RE = [
    (re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE), mode)
    for token, mode in _COMMENT
]

# (mode, center Hz, half-width Hz). The closest center wins when two overlap.
# FT8 is ±2.5 kHz. FT4 and JT65 are narrower and sit beside it.
_HOLES = (
    ("FT8", 1_840_000, 2500),
    ("WSPR", 1_836_600, 200),
    ("FT8", 3_573_000, 2500),
    ("FT4", 3_575_000, 1500),
    ("WSPR", 3_568_600, 200),
    ("CW", 5_330_500, 2000),
    ("FT8", 5_357_000, 2500),
    ("FT4", 7_047_500, 1500),
    ("FT8", 7_074_000, 2500),
    ("JT65", 7_076_000, 1000),
    ("WSPR", 7_038_600, 200),
    ("FT8", 10_136_000, 2500),
    ("FT4", 10_140_000, 1500),
    ("WSPR", 10_138_700, 200),
    ("FT8", 14_074_000, 2500),
    ("JT65", 14_076_000, 1000),
    ("FT4", 14_080_000, 1500),
    ("WSPR", 14_095_600, 200),
    ("FT8", 18_100_000, 2500),
    ("FT4", 18_104_000, 1500),
    ("WSPR", 18_104_600, 200),
    ("FT8", 21_074_000, 2500),
    ("JT65", 21_076_000, 1000),
    ("FT4", 21_140_000, 1500),
    ("WSPR", 21_094_600, 200),
    ("FT8", 24_915_000, 2500),
    ("FT4", 24_919_000, 1500),
    ("WSPR", 24_924_600, 200),
    ("FT8", 28_074_000, 2500),
    ("JT65", 28_076_000, 1000),
    ("FT4", 28_180_000, 1500),
    ("WSPR", 28_124_600, 200),
    ("MSK144", 50_260_000, 5000),
    ("Q65", 50_275_000, 4000),
    ("FT8", 50_313_000, 2500),
    ("FT4", 50_318_000, 2000),
    ("WSPR", 50_293_000, 200),
    ("FM", 52_525_000, 15000),
    ("FT8", 70_154_000, 2500),
    ("MSK144", 144_150_000, 5000),
    ("Q65", 144_120_000, 4000),
    ("FT4", 144_170_000, 2000),
    ("FT8", 144_174_000, 2500),
    ("FM", 146_520_000, 15000),
    ("FT8", 222_174_000, 2500),
    ("MSK144", 222_150_000, 5000),
    ("MSK144", 432_150_000, 5000),
    ("FT8", 432_174_000, 2500),
    ("FM", 446_000_000, 15000),
    ("FT8", 902_174_000, 3000),
    ("FT8", 1_296_174_000, 3000),
)

# freq < cw_below → CW. freq >= phone_from → SSB. The gap between them is data.
# A watering hole above is checked first, so 14.074 is FT8, not data.
_SEGMENTS = {
    "160m": (1_840_000, 1_840_000),
    "80m": (3_570_000, 3_600_000),
    "60m": (5_340_000, 5_340_000),
    "40m": (7_040_000, 7_125_000),
    "30m": (10_130_000, 10_150_000),
    "20m": (14_070_000, 14_150_000),
    "17m": (18_095_000, 18_110_000),
    "15m": (21_070_000, 21_200_000),
    "12m": (24_910_000, 24_930_000),
    "10m": (28_070_000, 28_300_000),
    "6m": (50_100_000, 50_100_000),
    "4m": (70_100_000, 70_150_000),
    "2m": (144_100_000, 144_100_000),
    "1.25m": (222_100_000, 222_100_000),
    "70cm": (432_100_000, 432_100_000),
}


def mode_from_comment(comment: str | None) -> str | None:
    text = comment or ""
    for pattern, mode in _COMMENT_RE:
        if pattern.search(text):
            return mode
    return None


def mode_from_frequency(freq_hz: int) -> str | None:
    best = None
    best_d = None
    for mode, center, tol in _HOLES:
        delta = abs(int(freq_hz) - center)
        if delta <= tol and (best_d is None or delta < best_d):
            best = mode
            best_d = delta
    return best


def mode_from_segment(band: str, freq_hz: int) -> str | None:
    edges = _SEGMENTS.get(band or "")
    if edges is None:
        return None
    cw_below, phone_from = edges
    if freq_hz < cw_below:
        return "CW"
    if freq_hz >= phone_from:
        return "SSB"
    return "data"


def infer_mode(freq_hz: int, comment: str | None, band: str) -> str:
    """FT8, FT4, MSK144, Q65, CW, SSB, or another short label. Never blank."""
    found = mode_from_comment(comment)
    if found:
        return found
    found = mode_from_frequency(freq_hz)
    if found:
        return found
    found = mode_from_segment(band, freq_hz)
    if found:
        return found
    return "other"


def canonical_mode(mode: str | None) -> str:
    """WSJT-X Status mode, or a spot label, as one token."""
    text = (mode or "").strip().upper()
    if not text:
        return ""
    token = text.split()[0]
    mapped = {
        "USB": "SSB", "LSB": "SSB", "PHONE": "SSB",
        "MSK": "MSK144", "DIGI": "data", "DATA": "data",
    }
    return mapped.get(token, token)
