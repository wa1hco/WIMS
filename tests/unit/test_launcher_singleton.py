# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class LauncherSingletonTests(unittest.TestCase):
    def test_second_acquire_fails(self):
        import wims.launcher.singleton as sing

        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "launcher.lock"
            with mock.patch.dict("os.environ", {"WIMS_LAUNCHER_LOCK": str(lock)}):
                # Reset module lock state for isolated test.
                sing._lock_fp = None
                self.assertTrue(sing.try_acquire_launcher_lock())
                # Simulate second process: clear in-process holder, keep OS lock via dup.
                held = sing._lock_fp
                sing._lock_fp = None
                self.assertFalse(sing.try_acquire_launcher_lock())
                sing._lock_fp = held
                sing._release_launcher_lock()


if __name__ == "__main__":
    unittest.main()
