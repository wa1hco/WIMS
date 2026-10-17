# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Launcher path, scripts allowlist, and zero-knowledge wording."""

from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Operator text must not teach these. A Developer heading (## or ###) may.
_FORBIDDEN = (
    re.compile(r"PYTHONPATH", re.IGNORECASE),
    re.compile(r"python3?\s+-m\b", re.IGNORECASE),
    re.compile(
        r"""(?i)(?:^|[\s;`])set\s+"?[A-Za-z_][A-Za-z0-9_]*"?\s*=""",
    ),
)


def _user_facing(text: str) -> str:
    """Text before the first Developer heading. Missing heading = all of it."""
    parts = re.split(r"(?m)^#{2,3} Developer\s*$", text, maxsplit=1)
    return parts[0]


def _hits(label: str, text: str) -> list[str]:
    found = []
    for rx in _FORBIDDEN:
        m = rx.search(text)
        if m:
            found.append(f"{label}: {m.group(0)!r}")
    return found


class ScriptsAllowlistTests(unittest.TestCase):
    def test_scripts_tree_matches_readme(self):
        readme = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        start = readme.index("<!-- scripts-allowlist -->")
        end = readme.index("<!-- /scripts-allowlist -->")
        listed = []
        for line in readme[start:end].splitlines():
            m = re.match(r"- `([^`]+)`", line.strip())
            if m:
                listed.append(m.group(1))
        on_disk = []
        for path in (ROOT / "scripts").rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT / "scripts").as_posix()
            if rel == "README.md" or "__pycache__" in rel or path.suffix == ".pyc":
                continue
            on_disk.append(rel)
        self.assertEqual(sorted(listed), sorted(on_disk))
        self.assertEqual(len(listed), len(set(listed)))

    def test_obvious_launchers_point_at_the_real_entry(self):
        solo = ROOT / "scripts" / "start-wims-solo.sh"
        desk = ROOT / "scripts" / "add-wims-to-desktop.sh"
        bat = ROOT / "scripts" / "Add WIMS to Desktop.bat"
        cmd = ROOT / "scripts" / "windows" / "Start-WimsLauncher.cmd"
        ps1 = ROOT / "scripts" / "windows" / "Install-WimsDesktopShortcut.ps1"
        self.assertTrue(os.access(solo, os.X_OK), "start-wims-solo.sh is not executable")
        self.assertTrue(os.access(desk, os.X_OK), "add-wims-to-desktop.sh is not executable")
        self.assertIn("wims.solo", solo.read_text(encoding="utf-8"))
        self.assertIn("wims.launcher", desk.read_text(encoding="utf-8"))
        self.assertIn("wims.launcher", cmd.read_text(encoding="utf-8"))
        self.assertIn("Install-WIMS-Desktop-Shortcut.cmd", bat.read_text(encoding="utf-8"))
        shortcut = ps1.read_text(encoding="utf-8")
        self.assertIn("WIMS.lnk", shortcut)
        self.assertIn("Start Menu", shortcut)


class ZeroKnowledgeWordingTests(unittest.TestCase):
    def test_operator_docs_and_launcher_help(self):
        chunks = {
            "README": _user_facing((ROOT / "README.md").read_text(encoding="utf-8")),
            "scripts/README.md": (ROOT / "scripts" / "README.md").read_text(encoding="utf-8"),
            "setup.html": (ROOT / "src" / "wims" / "server" / "static" / "setup.html").read_text(
                encoding="utf-8"
            ),
        }
        from wims.launcher.roles import ROLES

        help_bits = []
        for role in ROLES:
            help_bits.extend([role.title, role.summary, role.tooltip, role.button])
        proc = subprocess.run(
            [sys.executable, "-m", "wims.launcher", "--help"],
            cwd=ROOT,
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: WIMS", proc.stdout)
        chunks["launcher --help"] = proc.stdout + "\n" + "\n".join(help_bits)

        problems = []
        for label, text in chunks.items():
            problems.extend(_hits(label, text))
        self.assertEqual(problems, [])

    def test_desktop_entry_is_named_wims(self):
        from wims.launcher.app import linux_desktop_entry_text

        text = linux_desktop_entry_text()
        self.assertIn("Name=WIMS\n", text)
        self.assertIn("Icon=", text)

    def test_check_logs_launcher_is_obvious(self):
        script = ROOT / "scripts" / "Check logs.sh"
        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK), "Check logs.sh is not executable")
        self.assertIn("wims.logaudit.page", script.read_text(encoding="utf-8"))
        from wims.launcher.app import linux_check_logs_desktop_entry_text

        text = linux_check_logs_desktop_entry_text()
        self.assertIn("Name=Check logs\n", text)
        self.assertNotIn("python", text.lower())
        shortcut = (ROOT / "scripts" / "windows" / "Install-WimsDesktopShortcut.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Check logs.lnk", shortcut)

    def test_second_click_reopens_the_console(self):
        from wims.launcher.app import announce_already_running

        with mock.patch(
            "wims.launcher.app.probe_site_urls",
            return_value=(True, "http://127.0.0.1:8787"),
        ), mock.patch("wims.launcher.app.open_wims_url") as opened:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = announce_already_running()
        self.assertEqual(rc, 0)
        opened.assert_called_once_with("http://127.0.0.1:8787/")
        self.assertIn("already open", buf.getvalue().lower())
        self.assertEqual(_hits("already-running", buf.getvalue()), [])

    def test_second_click_without_a_console_names_the_window(self):
        from wims.launcher.app import announce_already_running

        with mock.patch(
            "wims.launcher.app.probe_site_urls",
            return_value=(False, ""),
        ), mock.patch("wims.launcher.app.open_wims_url") as opened:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = announce_already_running()
        self.assertEqual(rc, 0)
        opened.assert_not_called()
        self.assertIn("already on the screen", buf.getvalue())


class SoloLauncherPathTests(unittest.TestCase):
    def test_solo_starts_without_pythonpath(self):
        """The checkout shim serves /healthz and the Goal menu."""
        port = 18787
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.pop("WIMS_CONTEST_RULES", None)
        env.pop("WIMS_LOGS", None)
        with tempfile.TemporaryDirectory() as td:
            env["XDG_CONFIG_HOME"] = td
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "wims.solo",
                    "--no-open", "--no-check", "--no-seed",
                    "--http-port", str(port),
                    "--iface", "127.0.0.1",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                health = None
                deadline = time.time() + 20
                url = f"http://127.0.0.1:{port}/healthz"
                while time.time() < deadline:
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(url, timeout=0.5) as resp:
                            health = json.loads(resp.read().decode())
                        break
                    except Exception:
                        time.sleep(0.2)
                out = ""
                if health is None:
                    proc.terminate()
                    try:
                        out = proc.stdout.read() if proc.stdout else ""
                    except Exception:
                        out = ""
                self.assertIsNotNone(health, f"solo did not answer healthz:\n{out}")
                self.assertTrue(health.get("ok"))
                self.assertEqual(health.get("role"), "wims-site-server")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/setup", timeout=2
                ) as resp:
                    page = resp.read().decode()
                self.assertIn('id="goal-pick"', page)
                self.assertIn("Just operating (not a contest)", page)
                self.assertEqual(_hits("setup page", page), [])
            finally:
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=3)
                if proc.stdout:
                    proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
