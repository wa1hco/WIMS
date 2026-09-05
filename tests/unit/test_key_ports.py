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

from wims.key.ports import LAB_DEVICES, list_key_devices
from wims.launcher.assets import load_key_device, save_key_device, save_seat_intent, load_seat_intent
from wims.launcher.assets import INTENT_N1MM, INTENT_SSB_CW, INTENT_SERVER, INTENT_WSJT


class KeyPortsTests(unittest.TestCase):
    def test_list_includes_lab_sims(self):
        ports = list_key_devices()
        for lab in LAB_DEVICES:
            self.assertIn(lab, ports)

    def test_save_load_key_device_preserves_intent(self):
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "seat_intent.json"
            with mock.patch.dict("os.environ", {"WIMS_SEAT_INTENT": str(pref)}, clear=False):
                os_env_clear_key = {"WIMS_KEY_DEVICE": ""}
                with mock.patch.dict("os.environ", os_env_clear_key):
                    # clear inherited device
                    import os
                    os.environ.pop("WIMS_KEY_DEVICE", None)
                    save_seat_intent({
                        INTENT_N1MM: True,
                        INTENT_WSJT: False,
                        INTENT_SSB_CW: True,
                        INTENT_SERVER: False,
                    })
                    save_key_device("COM7")
                    self.assertEqual(load_key_device(), "COM7")
                    intent = load_seat_intent()
                    self.assertTrue(intent[INTENT_N1MM])
                    self.assertTrue(intent[INTENT_SSB_CW])
                    raw = json.loads(pref.read_text(encoding="utf-8"))
                    self.assertEqual(raw.get("key_device"), "COM7")
                    self.assertGreaterEqual(int(raw.get("schema") or 0), 2)


if __name__ == "__main__":
    unittest.main()
