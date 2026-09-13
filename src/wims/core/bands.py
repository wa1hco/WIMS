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

WSJT-X reports dial frequency in Hz; N1MM reports band as MHz (e.g. 14.0, 10000
for 10 GHz). Both normalize to a single band label ("20m", "6m", "3cm", ...) so
decodes and logged QSOs key on the same band.

N1MM Network Status / DXLOG ``Freq`` is **kHz** (10 GHz calling = 10368090.00 →
10368.090 MHz). RadioInfo ``<Freq>`` is **10 Hz units**. ``n1mm_raw_to_hz``
accepts both.

Roy 222 / 432 seats may report the radio IF, not RF: 222 is a 21 MHz radio, 432
is a 28 MHz radio behind a transverter. ``rf_hz`` maps those IFs to 222 / 432.
Frequencies already on VHF/UHF/microwave (N1MM transverter offset on, as on
MGEF-10-UP at 10368.090 MHz) pass through. Disable IF mapping with
``WIMS_TRANSVERTER=0``.
"""

from __future__ import annotations

import os

# (lower edge Hz, label); pick the largest lower-bound <= freq.
_BANDS = [
    (1_800_000, "160m"), (3_500_000, "80m"), (5_330_000, "60m"), (7_000_000, "40m"),
    (10_100_000, "30m"), (14_000_000, "20m"), (18_068_000, "17m"), (21_000_000, "15m"),
    (24_890_000, "12m"), (28_000_000, "10m"), (50_000_000, "6m"), (70_000_000, "4m"),
    (144_000_000, "2m"), (222_000_000, "1.25m"), (420_000_000, "70cm"),
    (902_000_000, "33cm"), (1_240_000_000, "23cm"), (2_300_000_000, "13cm"),
    (3_300_000_000, "9cm"), (5_650_000_000, "6cm"), (10_000_000_000, "3cm"),
    (24_000_000_000, "1.2cm"),
]


BAND_ORDER = [name for _, name in _BANDS]   # low -> high frequency (160m … 1.2cm)

# Approximate amateur windows — used to reject a bad RadioInfo unit guess.
_HAM_WINDOWS = (
    (1_800_000, 2_000_000), (3_500_000, 4_000_000), (5_330_000, 5_450_000),
    (7_000_000, 7_300_000), (10_100_000, 10_150_000), (14_000_000, 14_350_000),
    (18_068_000, 18_168_000), (21_000_000, 21_450_000), (24_890_000, 24_990_000),
    (28_000_000, 29_700_000), (50_000_000, 54_000_000), (70_000_000, 71_000_000),
    (144_000_000, 148_000_000), (222_000_000, 225_000_000),
    (420_000_000, 450_000_000), (902_000_000, 928_000_000),
    (1_240_000_000, 1_300_000_000), (2_300_000_000, 2_450_000_000),
    (3_300_000_000, 3_500_000_000), (5_650_000_000, 5_925_000_000),
    (10_000_000_000, 10_500_000_000), (24_000_000_000, 24_250_000_000),
)

# (if_lo_hz, if_hi_hz, lo_offset_hz) — radio CAT / WSJT dial in this window is IF.
# 222: 21 MHz radio, LO 201 MHz → 222–225.
# 432: 28 MHz radio + transverter, LO 404 MHz → 432–433.7 (10m IF).
# 10 GHz (MGEF-10-UP) already reports RF 10368 MHz in N1MM — not mapped here.
_IF_RANGES = (
    (21_000_000, 24_000_000, 201_000_000),
    (28_000_000, 29_700_000, 404_000_000),
)

# ADIF / Status band tags that occupy those IFs.
_IF_BAND = {
    "15m": "1.25m",
    "10m": "70cm",
}


def transverter_enabled() -> bool:
    v = (os.environ.get("WIMS_TRANSVERTER") or "1").strip().lower()
    return v not in ("0", "off", "false", "no")


def rf_hz(freq_hz: float) -> int:
    """Map radio IF Hz to RF Hz; already-RF values are unchanged."""
    try:
        hz = int(freq_hz)
    except (TypeError, ValueError):
        return 0
    if hz <= 0 or not transverter_enabled():
        return hz
    for lo, hi, offset in _IF_RANGES:
        if lo <= hz < hi:
            return hz + offset
    return hz


def rf_band(label: str) -> str:
    """Map IF band labels (10m / 15m) to RF; other labels pass through."""
    key = (label or "").strip().lower()
    if not key or not transverter_enabled():
        return label
    return _IF_BAND.get(key, label)


def in_ham_band(freq_hz: float) -> bool:
    """True if Hz falls in a recognized amateur allocation (pre-IF-map)."""
    try:
        hz = int(freq_hz)
    except (TypeError, ValueError):
        return False
    return any(lo <= hz < hi for lo, hi in _HAM_WINDOWS)


def n1mm_raw_to_hz(raw: str | int | float) -> int | None:
    """N1MM frequency to Hz.

    RadioInfo ``<Freq>`` is 10 Hz units (14417400 → 144.174 MHz). Network Status
    / DXLOG ``Freq`` is kHz (10368090.00 → 10368.090 MHz on 10 GHz). Try 10 Hz
    units first; if that is not in a ham band, try kHz. Then apply IF→RF.
    """
    try:
        n = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    ten_hz = n * 10
    if in_ham_band(ten_hz):
        return rf_hz(ten_hz)
    khz = n * 1_000
    if in_ham_band(khz) or in_ham_band(rf_hz(khz)):
        return rf_hz(khz)
    return rf_hz(ten_hz)


def band_sort_key(label: str) -> int:
    """Frequency-order index for a band label ("6m" < "2m" < "70cm"); unknown last."""
    return BAND_ORDER.index(label) if label in BAND_ORDER else len(BAND_ORDER)


def band_label(freq_hz: float, *, apply_if: bool = True) -> str:
    """Label a dial frequency in Hz. IF mapping is on for radio/WSJT dials.

    N1MM's Band *column* is a band number (21 = 15m, 10000 = 10 GHz), not an IF
    dial — use ``band_label_mhz`` so Field Day 15m/10m is not mapped to 222/432.
    """
    hz = rf_hz(freq_hz) if apply_if else int(freq_hz or 0)
    label = "?"
    for low, name in _BANDS:
        if hz >= low:
            label = name
        else:
            break
    return label


def band_label_mhz(mhz: float) -> str:
    """N1MM Band column in MHz (14.0, 222, 10000) -> label. Not an IF dial."""
    return band_label(int(round(mhz * 1_000_000)), apply_if=False)
