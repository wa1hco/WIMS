# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Band labels, N1MM kHz vs 10 Hz units, and opt-in 222/432 IF seats."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.core.bands import (  # noqa: E402
    band_label, band_label_mhz, format_band, if_mapping_enabled, n1mm_raw_to_hz,
    rf_band, rf_hz,
)
from wims.core.if_seats import reports_if, set_reports_if  # noqa: E402


class _IsolatedIfFile(unittest.TestCase):
    """Point if_seats.json at an empty temp file and clear WIMS_TRANSVERTER."""

    def setUp(self):
        self._patch = mock.patch.dict(os.environ, {}, clear=False)
        self._patch.start()
        os.environ.pop("WIMS_TRANSVERTER", None)
        self._tmp = tempfile.TemporaryDirectory()
        self._if_path = Path(self._tmp.name) / "if_seats.json"
        os.environ["WIMS_IF_SEATS_FILE"] = str(self._if_path)

    def tearDown(self):
        self._tmp.cleanup()
        self._patch.stop()

    def mark_if(self, *ids: str) -> None:
        for i in ids:
            set_reports_if(i, True, self._if_path)


class FormatBandTests(unittest.TestCase):
    def test_meters_capital_m(self):
        self.assertEqual(format_band("6m"), "6M")
        self.assertEqual(format_band("2m"), "2M")
        self.assertEqual(format_band("1.25m"), "1.25M")
        self.assertEqual(format_band("20m"), "20M")
        self.assertEqual(format_band("6M"), "6M")

    def test_cm_unchanged(self):
        self.assertEqual(format_band("70cm"), "70cm")
        self.assertEqual(format_band("3cm"), "3cm")

    def test_not_instance_ids(self):
        self.assertEqual(format_band("ROY-6m"), "ROY-6m")
        self.assertEqual(format_band("?"), "?")


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


class TransverterIfTests(_IsolatedIfFile):
    def test_default_28mhz_is_10m(self):
        # Flex / SmartSDR XVTR reports RF. 28.074 MHz is 10m until a seat opts in.
        self.assertFalse(if_mapping_enabled(None))
        self.assertFalse(if_mapping_enabled("FLEX-10M"))
        self.assertEqual(rf_hz(28_074_000), 28_074_000)
        self.assertEqual(band_label(28_074_000), "10m")
        self.assertEqual(band_label(28_074_000, instance="FLEX-10M"), "10m")
        self.assertEqual(rf_band("10m"), "10m")
        self.assertEqual(rf_band("10m", instance="FLEX-10M"), "10m")
        self.assertEqual(n1mm_raw_to_hz("2807400"), 28_074_000)
        self.assertEqual(band_label(n1mm_raw_to_hz("2807400")), "10m")
        self.assertEqual(band_label(21_174_000, instance="FLEX-10M"), "15m")

    def test_configured_if_seat_maps_432_and_222(self):
        self.mark_if("ROY-432", "MGEF-222")
        self.assertTrue(reports_if("ROY-432"))
        self.assertTrue(reports_if("WSJT-X - ROY-432"))
        self.assertEqual(rf_hz(28_174_000, instance="ROY-432"), 432_174_000)
        self.assertEqual(band_label(28_174_000, instance="ROY-432"), "70cm")
        self.assertEqual(band_label(28_074_000, instance="WSJT-X - ROY-432"), "70cm")
        self.assertEqual(rf_band("10m", instance="ROY-432"), "70cm")
        self.assertEqual(n1mm_raw_to_hz("2817400", instance="ROY-432"), 432_174_000)
        self.assertEqual(rf_hz(21_174_000, instance="MGEF-222"), 222_174_000)
        self.assertEqual(band_label(21_174_000, instance="MGEF-222"), "1.25m")
        self.assertEqual(rf_band("15m", instance="MGEF-222"), "1.25m")
        self.assertEqual(n1mm_raw_to_hz("2117400", instance="MGEF-222"), 222_174_000)
        # A second instance on the same server is not mapped.
        self.assertEqual(band_label(28_074_000, instance="FLEX-10M"), "10m")
        self.assertEqual(rf_band("15m", instance="FLEX-10M"), "15m")

    def test_already_rf_not_double_offset(self):
        self.mark_if("ROY-432", "ROY-222")
        self.assertEqual(rf_hz(222_174_000, instance="ROY-222"), 222_174_000)
        self.assertEqual(rf_hz(432_174_000, instance="ROY-432"), 432_174_000)
        self.assertEqual(rf_hz(10_368_090_000, instance="ROY-432"), 10_368_090_000)

    def test_env_on_forces_every_seat(self):
        with mock.patch.dict(os.environ, {"WIMS_TRANSVERTER": "1"}):
            self.assertEqual(rf_hz(28_174_000), 432_174_000)
            self.assertEqual(band_label(28_174_000), "70cm")
            self.assertEqual(rf_band("15m"), "1.25m")
            self.assertEqual(n1mm_raw_to_hz("2117400"), 222_174_000)

    def test_env_off_blocks_configured_seat(self):
        self.mark_if("ROY-432")
        with mock.patch.dict(os.environ, {"WIMS_TRANSVERTER": "0"}):
            self.assertEqual(rf_hz(28_174_000, instance="ROY-432"), 28_174_000)
            self.assertEqual(band_label(28_174_000, instance="ROY-432"), "10m")
            self.assertEqual(rf_band("15m", instance="ROY-432"), "15m")

    def test_clear_if_seat(self):
        self.mark_if("ROY-432")
        set_reports_if("WSJT-X - ROY-432", False, self._if_path)
        self.assertFalse(reports_if("ROY-432"))
        self.assertEqual(band_label(28_174_000, instance="ROY-432"), "10m")


class N1mmUnitsTests(_IsolatedIfFile):
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

    def test_if_radioinfo_10hz_units_only_when_configured(self):
        self.assertEqual(n1mm_raw_to_hz("2117400"), 21_174_000)
        self.assertEqual(n1mm_raw_to_hz("2817400"), 28_174_000)
        self.assertEqual(band_label(n1mm_raw_to_hz("2817400")), "10m")
        self.mark_if("MGEF-432", "MGEF-222")
        self.assertEqual(
            n1mm_raw_to_hz("2117400", instance="MGEF-222"), 222_174_000)
        self.assertEqual(
            n1mm_raw_to_hz("2817400", instance="MGEF-432"), 432_174_000)


if __name__ == "__main__":
    unittest.main()
