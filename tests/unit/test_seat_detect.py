# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for launcher seat-type detection."""

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

from wims.launcher.seat_detect import (
    SEAT_AMBIGUOUS,
    SEAT_N1MM,
    SEAT_WSJT,
    load_seat_type,
    probe_seat,
    save_seat_type,
)


class SeatDetectTests(unittest.TestCase):
    def test_env_wins(self):
        with mock.patch.dict(os.environ, {"WIMS_SEAT_TYPE": "wsjt"}, clear=False):
            p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_WSJT)
        self.assertEqual(p.source, "env")

    def test_wsjt_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(True, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(False, False),
                    ):
                        p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_WSJT)
        self.assertEqual(p.source, "detect")

    def test_n1mm_running_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(False, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, True),
                    ):
                        p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_N1MM)

    def test_windows_n1mm_data_without_process(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(False, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, False),
                    ):
                        with mock.patch("sys.platform", "win32"):
                            p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_N1MM)

    def test_both_running_defaults_n1mm(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(True, True),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, True),
                    ):
                        p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_N1MM)

    def test_linux_leftover_n1mm_docs_with_wsjt_is_wsjt(self):
        """Documents/N1MM Logger+ without N1MM process must not force N1MM home."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(True, True),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, False),  # data found, not running
                    ):
                        with mock.patch("sys.platform", "linux"):
                            p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_WSJT)
        self.assertIn("leftover", p.detail)

    def test_stale_linux_n1mm_pref_overridden(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch(
                "wims.launcher.seat_detect.load_seat_type",
                return_value=SEAT_N1MM,
            ):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(True, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, False),
                    ):
                        with mock.patch("sys.platform", "linux"):
                            with mock.patch(
                                "wims.launcher.seat_detect.save_seat_type",
                            ) as save:
                                p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_WSJT)
        save.assert_called_once_with(SEAT_WSJT)

    def test_neither_ambiguous(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WIMS_SEAT_TYPE", None)
            with mock.patch("wims.launcher.seat_detect.load_seat_type", return_value=None):
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(False, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(False, False),
                    ):
                        p = probe_seat()
        self.assertEqual(p.seat_type, SEAT_AMBIGUOUS)

    def test_pref_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "seat_type.json"
            with mock.patch.dict(os.environ, {"WIMS_SEAT_TYPE_FILE": str(pref)}, clear=False):
                os.environ.pop("WIMS_SEAT_TYPE", None)
                save_seat_type(SEAT_WSJT)
                self.assertEqual(load_seat_type(), SEAT_WSJT)
                with mock.patch(
                    "wims.launcher.seat_detect._wsjt_signals",
                    return_value=(False, False),
                ):
                    with mock.patch(
                        "wims.launcher.seat_detect._n1mm_signals",
                        return_value=(True, False),
                    ):
                        p = probe_seat()
                self.assertEqual(p.seat_type, SEAT_WSJT)
                self.assertEqual(p.source, "pref")


if __name__ == "__main__":
    unittest.main()
