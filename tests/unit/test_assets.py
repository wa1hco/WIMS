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

from wims.launcher.assets import (
    AGENT_KEY,
    AGENT_LOG,
    AGENT_SERVER,
    AGENT_WSJT,
    AssetSnapshot,
    load_wanted_agents,
    save_wanted_agents,
    suggested_checks,
)


class AssetsTests(unittest.TestCase):
    def test_suggested_wsjt_and_n1mm(self):
        snap = AssetSnapshot(
            n1mm_running=True, wsjt_running=True, wsjt_ini_count=2,
        )
        s = suggested_checks(snap, {})
        self.assertTrue(s[AGENT_LOG])
        self.assertTrue(s[AGENT_WSJT])
        self.assertFalse(s[AGENT_KEY])
        self.assertFalse(s[AGENT_SERVER])

    def test_ini_alone_does_not_auto_check_seat(self):
        snap = AssetSnapshot(wsjt_running=False, wsjt_ini_count=6)
        s = suggested_checks(snap, {})
        self.assertFalse(s[AGENT_WSJT])
        # Prefs can still keep Seat wanted without a live process.
        s2 = suggested_checks(snap, {AGENT_WSJT: True})
        self.assertTrue(s2[AGENT_WSJT])

    def test_prefs_keep_key(self):
        snap = AssetSnapshot()
        s = suggested_checks(snap, {AGENT_KEY: True})
        self.assertTrue(s[AGENT_KEY])

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "boxes.json"
            with mock.patch.dict("os.environ", {"WIMS_AGENT_BOXES": str(pref)}):
                save_wanted_agents({AGENT_LOG: True, AGENT_WSJT: False})
                w = load_wanted_agents()
                self.assertTrue(w[AGENT_LOG])
                self.assertFalse(w.get(AGENT_WSJT, True))


if __name__ == "__main__":
    unittest.main()
