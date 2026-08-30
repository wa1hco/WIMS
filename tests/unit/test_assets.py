# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
    live_checks,
    load_wanted_agents,
    save_wanted_agents,
    suggested_checks,
)


class AssetsTests(unittest.TestCase):
    def test_live_checks_from_running_apps(self):
        snap = AssetSnapshot(
            n1mm_running=True, wsjt_running=True, wsjt_ini_count=2,
        )
        s = live_checks(snap, site_reachable=False)
        self.assertTrue(s[AGENT_LOG])
        self.assertTrue(s[AGENT_WSJT])
        self.assertFalse(s[AGENT_KEY])
        self.assertFalse(s[AGENT_SERVER])

    def test_ini_alone_does_not_auto_check_seat(self):
        snap = AssetSnapshot(wsjt_running=False, wsjt_ini_count=6)
        s = live_checks(snap)
        self.assertFalse(s[AGENT_WSJT])

    def test_site_reachable_checks_server_status(self):
        snap = AssetSnapshot()
        s = live_checks(snap, site_reachable=True)
        self.assertTrue(s[AGENT_SERVER])
        self.assertFalse(s[AGENT_KEY])

    def test_wanted_arg_ignored(self):
        snap = AssetSnapshot()
        s = suggested_checks(snap, {AGENT_KEY: True, AGENT_WSJT: True})
        self.assertFalse(s[AGENT_KEY])
        self.assertFalse(s[AGENT_WSJT])

    def test_prefs_are_noop(self):
        # Checkboxes are not remembered — API kept as no-op for old callers.
        save_wanted_agents({AGENT_LOG: True})
        self.assertEqual(load_wanted_agents(), {})


if __name__ == "__main__":
    unittest.main()
