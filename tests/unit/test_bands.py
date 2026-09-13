# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Band labels, N1MM kHz vs 10 Hz units, and 222/432 IF transverters."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.core.bands import (  # noqa: E402
    band_label, band_label_mhz, n1mm_raw_to_hz, rf_band, rf_hz,
)


class BandLabelTests(unittest.TestCase):
    def test_hf_and_vhf_unchanged(self):
        self.assertEqual(band_label(14_074_000), "20m")
        self.assertEqual(band_label(50_313_000), "6m")
        self.assertEqual(band_label(144_174_000), "2m")
        self.assertEqual(band_label(222_174_000), "1.25m")
        self.assertEqual(band_label(432_174_000), "70cm")

    def test_microwave_from_n1mm_band_mhz(self):
        # DXLOG / Network Status Band column is MHz (10000 = 10 GHz).
        self.assertEqual(band_label_mhz(50), "6m")
        self.assertEqual(band_label_mhz(21), "15m")  # FD 15m, not 222 IF
        self.assertEqual(band_label_mhz(28), "10m")  # FD 10m, not 432 IF
        self.assertEqual(band_label_mhz(222), "1.25m")
        self.assertEqual(band_label_mhz(420), "70cm")
        self.assertEqual(band_label_mhz(1240), "23cm")
        self.assertEqual(band_label_mhz(2300), "13cm")
        self.assertEqual(band_label_mhz(3300), "9cm")
        self.assertEqual(band_label_mhz(5650), "6cm")
        self.assertEqual(band_label_mhz(10000), "3cm")

    def test_10ghz_rf_hz(self):
        self.assertEqual(band_label(10_368_090_000), "3cm")
        self.assertEqual(band_label(3_456_100_000), "9cm")
        self.assertEqual(band_label(5_760_100_000), "6cm")


class TransverterIfTests(unittest.TestCase):
    def test_222_21mhz_if(self):
        self.assertEqual(rf_hz(21_174_000), 222_174_000)
        self.assertEqual(band_label(21_174_000), "1.25m")
        self.assertEqual(rf_band("15m"), "1.25m")

    def test_432_28mhz_if(self):
        self.assertEqual(rf_hz(28_174_000), 432_174_000)
        self.assertEqual(band_label(28_174_000), "70cm")
        self.assertEqual(rf_band("10m"), "70cm")

    def test_already_rf_not_double_offset(self):
        self.assertEqual(rf_hz(222_174_000), 222_174_000)
        self.assertEqual(rf_hz(432_174_000), 432_174_000)
        self.assertEqual(rf_hz(10_368_090_000), 10_368_090_000)

    def test_disable_env(self):
        with mock.patch.dict(os.environ, {"WIMS_TRANSVERTER": "0"}):
            self.assertEqual(rf_hz(28_174_000), 28_174_000)
            self.assertEqual(band_label(28_174_000), "10m")
            self.assertEqual(rf_band("15m"), "15m")


class N1mmUnitsTests(unittest.TestCase):
    def test_radioinfo_10hz_units(self):
        self.assertEqual(n1mm_raw_to_hz("5031300"), 50_313_000)
        self.assertEqual(n1mm_raw_to_hz("14417400"), 144_174_000)
        self.assertEqual(n1mm_raw_to_hz("22217400"), 222_174_000)

    def test_network_status_10ghz_khz(self):
        # N1MM Network Status / DXLOG: Band 10000, Freq 10368090.00 (kHz).
        self.assertEqual(n1mm_raw_to_hz("10368090"), 10_368_090_000)
        self.assertEqual(n1mm_raw_to_hz("10368090.00"), 10_368_090_000)
        self.assertEqual(band_label(n1mm_raw_to_hz("10368090")), "3cm")

    def test_radioinfo_10ghz_10hz_units(self):
        # 10368.090 MHz in RadioInfo 10 Hz units.
        self.assertEqual(n1mm_raw_to_hz("1036809000"), 10_368_090_000)
        self.assertEqual(band_label(n1mm_raw_to_hz("1036809000")), "3cm")

    def test_if_radioinfo_10hz_units(self):
        self.assertEqual(n1mm_raw_to_hz("2117400"), 222_174_000)
        self.assertEqual(n1mm_raw_to_hz("2817400"), 432_174_000)


if __name__ == "__main__":
    unittest.main()
