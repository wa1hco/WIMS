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
    AGENT_N1MM_SEAT,
    AGENT_SERVER,
    AGENT_WSJT,
    INTENT_N1MM,
    INTENT_SERVER,
    INTENT_SSB_CW,
    INTENT_WSJT,
    AssetSnapshot,
    agents_for_intent,
    load_seat_intent,
    missing_intent_agent_labels,
    save_seat_intent,
    seat_intent_saved,
    seed_intent_from_assets,
)


class SeatIntentTests(unittest.TestCase):
    def test_agents_for_intent_mapping(self):
        a = agents_for_intent({
            INTENT_N1MM: True,
            INTENT_WSJT: True,
            INTENT_SSB_CW: False,
            INTENT_SERVER: False,
        })
        self.assertTrue(a[AGENT_N1MM_SEAT])
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

    def test_seat_intent_saved_false_until_written(self):
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "seat_intent.json"
            with mock.patch.dict("os.environ", {"WIMS_SEAT_INTENT": str(pref)}):
                self.assertFalse(seat_intent_saved())
                self.assertFalse(pref.is_file())
                save_seat_intent({INTENT_N1MM: False})
                self.assertTrue(seat_intent_saved())
                self.assertFalse(load_seat_intent()[INTENT_N1MM])

    def test_seed_intent_n1mm_pc_does_not_enable_wsjt_from_ini(self):
        snap = AssetSnapshot(
            n1mm_running=True,
            n1mm_found=True,
            wsjt_running=False,
            wsjt_ini_count=1,
        )
        got = seed_intent_from_assets(snap)
        self.assertTrue(got[INTENT_N1MM])
        self.assertFalse(got[INTENT_WSJT])
        self.assertFalse(got[INTENT_SSB_CW])
        self.assertFalse(got[INTENT_SERVER])

    def test_seed_intent_wsjt_pc_from_ini(self):
        snap = AssetSnapshot(
            n1mm_running=False,
            n1mm_found=False,
            wsjt_running=False,
            wsjt_ini_count=2,
        )
        got = seed_intent_from_assets(snap)
        self.assertFalse(got[INTENT_N1MM])
        self.assertTrue(got[INTENT_WSJT])

    def test_missing_n1mm_agent_label_no_keyerror(self):
        missing = missing_intent_agent_labels(
            {INTENT_N1MM: True, INTENT_WSJT: False,
             INTENT_SSB_CW: False, INTENT_SERVER: False},
            n1mm_seat_up=False,
            wsjt_up=False,
            server_up=False,
        )
        self.assertEqual(missing, ["N1MM agent"])
        missing_up = missing_intent_agent_labels(
            {INTENT_N1MM: True, INTENT_WSJT: False,
             INTENT_SSB_CW: True, INTENT_SERVER: False},
            n1mm_seat_up=True,
            wsjt_up=False,
            server_up=False,
        )
        self.assertEqual(missing_up, [])

    def test_snapshot_wsjt_names(self):
        snap = AssetSnapshot(
            wsjt_running=True,
            wsjt_running_names=["IC9700", "flexA"],
        )
        self.assertTrue(snap.wsjt_running)
        self.assertEqual(len(snap.wsjt_running_names), 2)


if __name__ == "__main__":
    unittest.main()
