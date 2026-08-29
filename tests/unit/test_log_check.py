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

from wims.agent.n1mm_probe import _parse_wsjt_udp_reader_from_ini, probe_wsjt_udp_reader
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


class WsjtUdpReaderIniTests(unittest.TestCase):
    def test_reader_off(self):
        text = "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n"
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertFalse(rows[0]["enabled"])

    def test_reader_on_defaults_2237(self):
        text = (
            "[ExternalProgramInput]\n"
            "EnableWSJTJTDXUDPReader=True\n"
            "WSJTJTDXUDPIP=224.0.0.73\n"
        )
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["port"], 2237)

    def test_reader_on_2333_not_fleet(self):
        text = (
            "[ExternalProgramInput]\n"
            "EnableWSJTJTDXUDPReader=True\n"
            "WSJTJTDXUDPPort=2333\n"
        )
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["port"], 2333)

    def test_ini_true_without_runtime_is_not_conflict(self):
        """Stale ini Enable=True must not yellow-warn if N1MM is not bound."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\n"
                "EnableWSJTJTDXUDPReader=True\n"
                "WSJTJTDXUDPPort=2237\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertFalse(info["fleet_conflict"])
        self.assertIn("not bound", info["summary"].lower())

    def test_runtime_bind_is_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[{"port": 2237, "pid": 99, "local": "0.0.0.0:2237"}],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertTrue(info["fleet_conflict"])
        self.assertIn("2237", info["summary"])

    def test_probe_off_no_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertFalse(info["fleet_conflict"])
        self.assertIn("off", info["summary"].lower())


class CheckTests(unittest.TestCase):
    def test_waiting_for_band_is_warn(self):
        rep = run_checks(live_band=None, joined=None, tcp_probe=lambda h, p: False)
        self.assertEqual(rep.severity, "warn")
        self.assertTrue(any(i.id == "band" and i.severity == "warn" for i in rep.items))
        self.assertTrue(any("Waiting for N1MM" in i.message for i in rep.items))

    def test_joined_and_tcp_ok(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            with mock.patch("wims.log.check._wsjt_udp_reader_conflict") as c:
                from wims.log.check import CheckItem
                n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
                c.return_value = CheckItem("conflict", "ok", "reader off")
                rep = run_checks(
                    live_band="6m", joined=True, dry_run=False,
                    tcp_probe=lambda h, p: True,
                )
        self.assertEqual(rep.severity, "ok")
        self.assertTrue(any(i.id == "mcast" and i.severity == "ok" for i in rep.items))
        self.assertTrue(any(i.id == "delivery" and i.severity == "ok" for i in rep.items))
        text = "\n".join(rep.lines())
        text.encode("cp1252")

    def test_conflict_warn_only_when_detected(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            with mock.patch("wims.log.check._wsjt_udp_reader_conflict") as c:
                from wims.log.check import CheckItem
                n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
                c.return_value = CheckItem(
                    "conflict", "ok", "N1MM WSJT/JTDX UDP reader is off (Logger.ini).",
                )
                rep = run_checks(
                    live_band="6m", joined=True, dry_run=True,
                    tcp_probe=lambda h, p: True,
                )
        conflict = next(i for i in rep.items if i.id == "conflict")
        self.assertEqual(conflict.severity, "ok")

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
