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
