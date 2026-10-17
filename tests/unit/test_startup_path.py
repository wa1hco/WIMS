# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every front door opens the WIMS window. Operate shares one start."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.roles import role_by_id
from wims.launcher.startup import (
    LAUNCHER_MODULE,
    SOLO_IFACE,
    SOLO_MODULE,
    console_action,
    operate_banner,
    seat_sentence,
    solo_iface,
    startup_log_path,
)


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class EntryPointTests(unittest.TestCase):
    def test_front_doors_open_the_launcher(self):
        desktop = __import__(
            "wims.launcher.app", fromlist=["linux_desktop_entry_text"]
        ).linux_desktop_entry_text()
        self.assertIn("scripts/start-wims.sh", desktop.replace("\\", "/"))
        front = _text("scripts/start-wims.sh")
        win = _text("scripts/windows/Start-WimsLauncher.cmd")
        vbs = _text("scripts/windows/Start-WimsLauncher.vbs")
        self.assertIn(f"-m {LAUNCHER_MODULE}", front)
        self.assertIn(f"-m {LAUNCHER_MODULE}", win)
        self.assertIn("Start-WimsLauncher.cmd", vbs)
        self.assertIn("_resolve-python.sh", front)
        self.assertIn("_resolve-python.cmd", win)

    def test_operate_scripts_use_the_solo_module(self):
        linux = _text("scripts/start-wims-solo.sh")
        win = _text("scripts/windows/Start-Wims-Solo.cmd")
        self.assertIn(f"-m {SOLO_MODULE}", linux)
        self.assertIn(f"-m {SOLO_MODULE}", win)
        self.assertIn("_resolve-python.sh", linux)
        self.assertIn("_resolve-python.cmd", win)
        # The port check lives in the shared start, not a second copy in the shell.
        self.assertNotIn("healthz", linux.lower())
        self.assertNotIn("healthz", win.lower())

    def test_launcher_operate_role_matches_the_script(self):
        argv = role_by_id("solo").build_argv()
        self.assertEqual(argv, ["-m", SOLO_MODULE])
        self.assertNotIn("--no-check", argv)
        self.assertNotIn("--iface", argv)
        self.assertNotIn("--iface", role_by_id("server").build_argv())

    def test_no_args_opens_the_launcher(self):
        from wims.cli import main as cli_main
        with mock.patch("wims.launcher.app.main", return_value=0) as gui:
            code = cli_main([])
        self.assertEqual(code, 0)
        gui.assert_called_once_with([])

    def test_window_keeps_its_buttons_and_gains_the_list(self):
        app = _text("src/wims/launcher/app.py")
        home = _text("src/wims/launcher/home_panel.py")
        panel = _text("src/wims/launcher/updates_panel.py")
        self.assertIn("Update\\nWIMS", app)
        self.assertIn("Open site console", home)
        self.assertIn("Restart site server", home)
        self.assertIn("Check now", panel)
        self.assertIn("Install this update", panel)
        self.assertIn("Go back", panel)

    def test_log_path_matches_the_window(self):
        from wims.launcher.app import details_log_path
        self.assertEqual(details_log_path(), startup_log_path())


class OperatePlanTests(unittest.TestCase):
    def test_console_actions(self):
        self.assertEqual(console_action("free", port=8787), ("start", ""))
        action, message = console_action("wims", port=8787)
        self.assertEqual(action, "reuse")
        self.assertIn("already open", message.lower())
        action, message = console_action("busy", port=8787)
        self.assertEqual(action, "busy")
        self.assertIn("not WIMS", message)
        self.assertIn("http://localhost:8787/", message)

    def test_iface_and_banner(self):
        self.assertEqual(solo_iface(None), SOLO_IFACE)
        self.assertEqual(solo_iface(""), SOLO_IFACE)
        self.assertEqual(solo_iface("10.1.2.3"), "10.1.2.3")
        banner = operate_banner(
            http_port=8787,
            iface=SOLO_IFACE,
            seed=True,
            seat=seat_sentence("wsjt", "WSJT-X present, no N1MM running"),
        )
        self.assertIn("127.0.0.1", banner)
        self.assertIn("log and contest rules", banner)
        self.assertIn("WSJT-X seat", banner)
        empty = operate_banner(
            http_port=8787, iface=SOLO_IFACE, seed=False, seat=seat_sentence("ambiguous"),
        )
        self.assertIn("empty log", empty)
        self.assertIn("this PC", empty)

    def test_busy_port_does_not_start_the_server(self):
        import wims.solo as solo
        with mock.patch("wims.launcher.startup.probe_console", return_value="busy"):
            with mock.patch.object(solo.server, "main") as server:
                code = solo.main(["--no-open", "--no-check", "--http-port", "8787"])
        self.assertEqual(code, 1)
        server.assert_not_called()

    def test_already_open_reuses_the_console(self):
        import wims.solo as solo
        with mock.patch("wims.launcher.startup.probe_console", return_value="wims"):
            with mock.patch("wims.launcher.app.open_wims_url") as opened:
                with mock.patch.object(solo.server, "main") as server:
                    code = solo.main(["--http-port", "8787"])
        self.assertEqual(code, 0)
        server.assert_not_called()
        opened.assert_called_once_with("http://localhost:8787/")


if __name__ == "__main__":
    unittest.main()
