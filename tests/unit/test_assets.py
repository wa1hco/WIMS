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
    INTENT_N1MM,
    INTENT_SERVER,
    INTENT_SSB_CW,
    INTENT_WSJT,
    AssetSnapshot,
    agents_for_intent,
    load_seat_intent,
    save_seat_intent,
)


class SeatIntentTests(unittest.TestCase):
    def test_agents_for_intent_mapping(self):
        a = agents_for_intent({
            INTENT_N1MM: True,
            INTENT_WSJT: True,
            INTENT_SSB_CW: False,
            INTENT_SERVER: False,
        })
        self.assertTrue(a[AGENT_LOG])
        self.assertTrue(a[AGENT_WSJT])
        self.assertFalse(a[AGENT_KEY])
        self.assertFalse(a[AGENT_SERVER])

    def test_ssb_cw_starts_key_agent(self):
        a = agents_for_intent({INTENT_SSB_CW: True})
        self.assertTrue(a[AGENT_KEY])

    def test_save_load_intent(self):
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "seat_intent.json"
            with mock.patch.dict("os.environ", {"WIMS_SEAT_INTENT": str(pref)}):
                save_seat_intent({
                    INTENT_N1MM: True,
                    INTENT_WSJT: False,
                    INTENT_SSB_CW: True,
                    INTENT_SERVER: False,
                })
                got = load_seat_intent()
                self.assertTrue(got[INTENT_N1MM])
                self.assertFalse(got[INTENT_WSJT])
                self.assertTrue(got[INTENT_SSB_CW])
                self.assertFalse(got[INTENT_SERVER])

    def test_snapshot_wsjt_names(self):
        snap = AssetSnapshot(
            wsjt_running=True,
            wsjt_running_names=["IC9700", "flexA"],
        )
        self.assertTrue(snap.wsjt_running)
        self.assertEqual(len(snap.wsjt_running_names), 2)


if __name__ == "__main__":
    unittest.main()
