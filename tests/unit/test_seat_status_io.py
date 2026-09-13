# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.seat.status_io import read_status, write_status  # noqa: E402


class SeatStatusIoTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "n1mm-seat-status.json"
            with mock.patch("wims.seat.status_io.status_path", return_value=path):
                write_status({
                    "ts": 1e12,
                    "do_log": True,
                    "do_key": False,
                    "status_rows": [("ok", "LOG", "2m")],
                })
                # max_age would expire 1e12-now; write a fresh ts
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(data["do_log"])
                self.assertEqual(data["status_rows"][0][1], "LOG")
                write_status({
                    "ts": __import__("time").time(),
                    "do_log": True,
                    "status_rows": [["ok", "BROADCAST", "up"]],
                })
                got = read_status()
                self.assertIsNotNone(got)
                self.assertEqual(got["status_rows"][0][1], "BROADCAST")


if __name__ == "__main__":
    unittest.main()
