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

from wims.launcher.assets import INTENT_N1MM, INTENT_SERVER, INTENT_WSJT
from wims.launcher.boot import (
    apply_boot_plan,
    load_seat_cmd_env,
    named_wsjtx_rigs,
    parse_cmd_sets,
    resolve_boot_plan,
)


class ParseCmdTests(unittest.TestCase):
    def test_parse_set_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "seat-common.cmd"
            p.write_text(
                '@echo off\r\n'
                'set "WIMS_SERVER=http://10.0.0.5:8787"\r\n'
                'set "WSJTX_EXE=C:\\WSJT\\wsjtx\\bin\\wsjtx.exe"\r\n'
                'set "SEAT_DEFAULT_RADIO=flex50"\r\n',
                encoding="utf-8",
            )
            got = parse_cmd_sets(p)
        self.assertEqual(got["WIMS_SERVER"], "http://10.0.0.5:8787")
        self.assertEqual(got["SEAT_DEFAULT_RADIO"], "flex50")

    def test_load_merges_radio_pack(self):
        with tempfile.TemporaryDirectory() as td:
            here = Path(td)
            (here / "seat-common.cmd").write_text(
                'set "SEAT_DEFAULT_RADIO=ic9700-144"\r\n'
                'set "WSJTX_EXE=C:\\WSJT\\wsjtx\\bin\\wsjtx.exe"\r\n',
                encoding="utf-8",
            )
            (here / "radio-ic9700-144.cmd").write_text(
                'set "WSJTX_RIG_NAME=WSJTX-144"\r\n',
                encoding="utf-8",
            )
            env = load_seat_cmd_env(here)
        self.assertEqual(env["WSJTX_RIG_NAME"], "WSJTX-144")


class BootPlanTests(unittest.TestCase):
    def test_saved_wsjt_intent_starts_wsjtx(self):
        fake_exe = Path(tempfile.gettempdir()) / "wsjtx-fake.exe"
        try:
            fake_exe.write_bytes(b"mz")
        except OSError:
            self.skipTest("cannot write temp exe")
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "seat_intent.json"
            with mock.patch.dict(os_environ(), {"WIMS_SEAT_INTENT": str(pref)}):
                from wims.launcher.assets import save_seat_intent
                save_seat_intent({
                    INTENT_WSJT: True,
                    INTENT_N1MM: False,
                    INTENT_SERVER: False,
                })
                with mock.patch("wims.launcher.boot.find_wsjtx_exe", return_value=fake_exe):
                    with mock.patch("wims.launcher.boot.named_wsjtx_rigs", return_value=["ForEW1"]):
                        with mock.patch("wims.launcher.boot.detect_assets"):
                            plan = resolve_boot_plan(cmd_env={})
        self.assertTrue(plan.start_wsjtx)
        self.assertFalse(plan.start_n1mm)
        self.assertTrue(plan.start_wims)
        self.assertEqual(plan.rig_names, ["ForEW1"])
        self.assertIn("saved", plan.intent_source)

    def test_dry_run_does_not_spawn(self):
        from wims.launcher.boot import BootPlan
        plan = BootPlan(
            intent={INTENT_WSJT: True},
            intent_source="test",
            start_wims=True,
            start_wsjtx=True,
            wsjtx_exe=r"C:\WSJT\wsjtx\bin\wsjtx.exe",
            rig_names=["X"],
        )
        with mock.patch("wims.launcher.boot._start_detached") as start:
            with mock.patch("wims.launcher.boot.subprocess.Popen") as popen:
                lines = apply_boot_plan(plan, dry_run=True)
        start.assert_not_called()
        popen.assert_not_called()
        self.assertTrue(any("would start WSJT-X" in ln for ln in lines))


def os_environ():
    import os
    return os.environ


class NamedRigTests(unittest.TestCase):
    def test_named_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "WSJT-X").mkdir()
            Path(td, "WSJT-X - ForEW1").mkdir()
            Path(td, "WSJT-X - 2M-EME").mkdir()
            with mock.patch.dict(os_environ(), {"LOCALAPPDATA": td}):
                names = named_wsjtx_rigs()
        self.assertEqual(names, ["2M-EME", "ForEW1"])


if __name__ == "__main__":
    unittest.main()
