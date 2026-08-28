# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for top-level CLI + launcher role catalog (no GUI required)."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims import __version__
from wims.cli import main as cli_main
from wims.launcher.roles import (
    BAND_PORTS,
    DEFAULT_SOLO_PORT,
    ROLES,
    console_urls,
    role_by_id,
)


class RoleCatalogTests(unittest.TestCase):
    def test_recommended_solo_exists(self):
        solo = role_by_id("solo")
        self.assertIsNotNone(solo)
        assert solo is not None
        self.assertTrue(solo.recommended)
        self.assertTrue(solo.long_running)

    def test_solo_argv_includes_port(self):
        solo = role_by_id("solo")
        assert solo is not None
        argv = solo.build_argv(port=2238)
        self.assertIn("-m", argv)
        self.assertIn("wims.solo", argv)
        self.assertIn("--port", argv)
        i = argv.index("--port")
        self.assertEqual(argv[i + 1], "2238")

    def test_band_ports_skip_2240(self):
        ports = [p for _, p in BAND_PORTS]
        self.assertNotIn(2240, ports)
        self.assertEqual(DEFAULT_SOLO_PORT, 2237)

    def test_console_urls(self):
        urls = console_urls(8787)
        self.assertTrue(urls["operate"].endswith(":8787/"))
        self.assertIn("/status", urls["status"])
        self.assertIn("/setup", urls["setup"])

    def test_all_roles_have_tooltips(self):
        for role in ROLES:
            self.assertTrue(role.tooltip.strip(), msg=role.id)
            self.assertTrue(role.summary.strip(), msg=role.id)


class CliTests(unittest.TestCase):
    def test_version(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue().strip(), __version__)

    def test_help(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["help"])
        self.assertEqual(code, 0)
        out = buf.getvalue().lower()
        self.assertIn("solo", out)
        self.assertIn("gui", out)
        self.assertIn("desktop", out)

    def test_unknown_role(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code = cli_main(["not-a-role"])
        self.assertEqual(code, 2)

    def test_agent_dispatch(self):
        with mock.patch("wims.agent.app.main", return_value=0) as m:
            code = cli_main(["agent", "--solo"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(["--solo"])

    def test_key_dispatch(self):
        with mock.patch("wims.key.app.main", return_value=0) as m:
            code = cli_main(["key", "selftest"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(["selftest"])


class SoloPortFlagTests(unittest.TestCase):
    def test_solo_passes_port_to_server(self):
        # Import solo and capture the argv it would hand to server.main.
        import wims.solo as solo

        captured = {}

        def fake_server_main():
            captured["argv"] = list(sys.argv)

        with mock.patch.object(solo.server, "main", side_effect=fake_server_main):
            with mock.patch.object(sys, "argv", ["wims.solo", "--port", "2241", "--no-check", "--no-open"]):
                solo.main()
        self.assertIn("--ports", captured["argv"])
        i = captured["argv"].index("--ports")
        self.assertEqual(captured["argv"][i + 1], "2241")


if __name__ == "__main__":
    unittest.main()
