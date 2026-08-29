# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for log helper scoped config checks + RadioInfo band."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.check import pin_from_hostname, resolve_pin, run_checks
from wims.log.radioinfo import band_from_radioinfo_xml, n1mm_freq_units_to_hz


class PinTests(unittest.TestCase):
    def test_hostname_suffix(self):
        self.assertEqual(pin_from_hostname("wims-test-50"), "6m")
        self.assertEqual(pin_from_hostname("TRAILER-144"), "2m")
        self.assertIsNone(pin_from_hostname("desktop-jeff"))

    def test_resolve_band_arg(self):
        self.assertEqual(resolve_pin("2m", env={}, hostname="x"), "2m")

    def test_resolve_env(self):
        self.assertEqual(
            resolve_pin(None, env={"WIMS_BAND": "70cm"}, hostname="x"),
            "70cm",
        )


class RadioInfoTests(unittest.TestCase):
    def test_freq_units(self):
        self.assertEqual(n1mm_freq_units_to_hz("5012345"), 50_123_450)
        self.assertEqual(n1mm_freq_units_to_hz("14417400"), 144_174_000)

    def test_parse_radioinfo_6m(self):
        xml = """<?xml version="1.0"?>
        <RadioInfo>
          <RadioNr>1</RadioNr>
          <Freq>5017400</Freq>
          <TXFreq>5017400</TXFreq>
          <Mode>USB</Mode>
          <ActiveRadioNr>1</ActiveRadioNr>
        </RadioInfo>
        """
        band, meta = band_from_radioinfo_xml(xml)
        self.assertEqual(band, "6m")
        self.assertEqual(meta["freq_hz"], 50_174_000)

    def test_ignore_contactinfo(self):
        xml = "<contactinfo><band>50</band><call>K1ABC</call></contactinfo>"
        band, meta = band_from_radioinfo_xml(xml)
        self.assertIsNone(band)
        self.assertEqual(meta, {})


class CheckTests(unittest.TestCase):
    def test_waiting_for_band_is_warn(self):
        rep = run_checks(live_band=None, joined=None, tcp_probe=lambda h, p: False)
        self.assertEqual(rep.severity, "warn")
        self.assertTrue(any(i.id == "band" and i.severity == "warn" for i in rep.items))
        self.assertTrue(any("Waiting for N1MM" in i.message for i in rep.items))

    def test_joined_and_tcp_ok(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            from wims.log.check import CheckItem
            n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
            rep = run_checks(
                live_band="6m", joined=True, dry_run=False,
                tcp_probe=lambda h, p: True,
            )
        self.assertIn(rep.severity, ("ok", "warn"))
        self.assertTrue(any(i.id == "mcast" and i.severity == "ok" for i in rep.items))
        self.assertTrue(any(i.id == "delivery" and i.severity == "ok" for i in rep.items))
        text = "\n".join(rep.lines())
        text.encode("cp1252")

    def test_expect_mismatch_warns(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            from wims.log.check import CheckItem
            n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
            rep = run_checks(
                live_band="2m", expect_band="6m", joined=True,
                tcp_probe=lambda h, p: True,
            )
        self.assertTrue(any(i.id == "expect" and i.severity == "warn" for i in rep.items))

    def test_tcp_missing_warns(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            from wims.log.check import CheckItem
            n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
            rep = run_checks(
                live_band="6m", joined=True,
                tcp_probe=lambda h, p: False,
            )
        delivery = next(i for i in rep.items if i.id == "delivery")
        self.assertEqual(delivery.severity, "warn")
        self.assertIn("52001", delivery.message)


if __name__ == "__main__":
    unittest.main()
