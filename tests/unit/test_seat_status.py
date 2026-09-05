# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the N1MM agent status model (Broadcast / Log / KEY)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.app import LogState
from wims.seat.app import _status_model


class _StubKeyState:
    def __init__(self, **over):
        self._snap = {
            "targets": [],
            "keyed": False,
            "holding": False,
            "controller_id": "test-key",
            "cts_error": None,
            "discover_error": None,
            "discover_port": None,
            "last_emit": None,
        }
        self._snap.update(over)

    def snapshot(self):
        return dict(self._snap)


class _StubKeyRuntime:
    def __init__(self, device="", override=None, **state_over):
        self.device = device
        self.override = override
        self.state = _StubKeyState(**state_over)


def _log_state(band="2m"):
    state = LogState()
    state.live_band = band
    state.joined = True
    return state


class SeatStatusModelTests(unittest.TestCase):
    def test_missing_key_device_keeps_both_info_visible(self):
        key = _StubKeyRuntime(device="", cts_error="no KEY device configured")
        model = _status_model(_log_state(), key, do_log=True, do_key=True)
        self.assertEqual(model.banner_level, "warn")
        self.assertIn("N1MM agent", model.banner_text)
        self.assertIn("2m", model.banner_text)
        self.assertIn("key device missing", model.banner_text)
        self.assertIn("WIMS_KEY_DEVICE", model.fix_text)
        by_label = {name: (lvl, text) for lvl, name, text in model.status_rows}
        self.assertEqual(set(by_label), {"BROADCAST", "LOG", "KEY"})
        self.assertEqual(by_label["BROADCAST"][0], "ok")
        self.assertEqual(by_label["LOG"][0], "ok")
        self.assertEqual(by_label["KEY"][0], "err")
        self.assertIn("no KEY device", by_label["KEY"][1])

    def test_key_device_ok_agent_ready(self):
        key = _StubKeyRuntime(device="sim:up", keyed=True)
        model = _status_model(_log_state(), key, do_log=True, do_key=True)
        self.assertEqual(model.banner_level, "ok")
        self.assertEqual(model.banner_text, "N1MM agent ready — 2m")
        by_label = {name: (lvl, text) for lvl, name, text in model.status_rows}
        self.assertIn("BROADCAST", by_label)
        self.assertEqual(by_label["KEY"][0], "ok")
        self.assertIn("device sim:up", by_label["KEY"][1])
        self.assertIn("DOWN", by_label["KEY"][1])
        self.assertIn("FWD 0", by_label["LOG"][1])

    def test_log_only_banner(self):
        model = _status_model(_log_state(), None, do_log=True, do_key=False)
        self.assertEqual(model.banner_text, "N1MM agent ready — 2m")
        by_label = {name: (lvl, text) for lvl, name, text in model.status_rows}
        self.assertIn("BROADCAST", by_label)
        self.assertIn("LOG", by_label)
        self.assertNotIn("KEY", by_label)

    def test_no_band_still_waits(self):
        key = _StubKeyRuntime(device="sim:down")
        model = _status_model(_log_state(band=None), key, do_log=True, do_key=True)
        self.assertEqual(model.banner_level, "warn")
        self.assertIn("Broadcast", model.banner_text)
        self.assertIn("127.0.0.1:12060", model.fix_text)
        by_label = {name: (lvl, text) for lvl, name, text in model.status_rows}
        self.assertEqual(by_label["BROADCAST"][0], "warn")


class WinComPathTests(unittest.TestCase):
    def test_com_ports_get_device_prefix(self):
        from wims.key.cts import win_com_path
        self.assertEqual(win_com_path("COM5"), r"\\.\COM5")
        self.assertEqual(win_com_path("com10"), r"\\.\COM10")
        self.assertEqual(win_com_path(r"\\.\COM12"), r"\\.\COM12")
        self.assertEqual(win_com_path("/dev/ttyUSB0"), "/dev/ttyUSB0")
        self.assertEqual(win_com_path("sim:up"), "sim:up")


if __name__ == "__main__":
    unittest.main()
