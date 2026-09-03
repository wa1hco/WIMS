# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the merged seat agent status model (log + key in one GUI)."""

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
        # Banner still names the seat + band, not the device error.
        self.assertIn("Seat", model.banner_text)
        self.assertIn("2m", model.banner_text)
        self.assertIn("key device missing", model.banner_text)
        # The remedy lives on the fix line.
        self.assertIn("WIMS_KEY_DEVICE", model.fix_text)
        # Both halves show a fact line.
        self.assertTrue(any(f.startswith("Log ") for f in model.fact_lines))
        self.assertTrue(any(f.startswith("Key ") for f in model.fact_lines))

    def test_key_device_ok_seat_ready(self):
        key = _StubKeyRuntime(device="sim:up", keyed=True)
        model = _status_model(_log_state(), key, do_log=True, do_key=True)
        self.assertEqual(model.banner_level, "ok")
        self.assertEqual(model.banner_text, "Seat ready — 2m")
        key_fact = next(f for f in model.fact_lines if f.startswith("Key "))
        self.assertIn("device sim:up", key_fact)
        self.assertIn("Key DOWN", key_fact)

    def test_log_only_banner(self):
        model = _status_model(_log_state(), None, do_log=True, do_key=False)
        self.assertEqual(model.banner_text, "Log ready — 2m")

    def test_no_band_still_waits(self):
        key = _StubKeyRuntime(device="sim:down")
        model = _status_model(_log_state(band=None), key, do_log=True, do_key=True)
        self.assertEqual(model.banner_level, "warn")
        self.assertIn("Waiting for N1MM band", model.banner_text)
        self.assertIn("224.0.0.73:12060", model.fix_text)


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
