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
        front = ROOT / "scripts" / "start-wims.sh"
        desk = ROOT / "scripts" / "add-wims-to-desktop.sh"
        bat = ROOT / "scripts" / "Add WIMS to Desktop.bat"
        cmd = ROOT / "scripts" / "windows" / "Start-WimsLauncher.cmd"
        ps1 = ROOT / "scripts" / "windows" / "Install-WimsDesktopShortcut.ps1"
        self.assertTrue(os.access(solo, os.X_OK), "start-wims-solo.sh is not executable")
        self.assertTrue(os.access(front, os.X_OK), "start-wims.sh is not executable")
        self.assertTrue(os.access(desk, os.X_OK), "add-wims-to-desktop.sh is not executable")
        self.assertIn("wims.solo", solo.read_text(encoding="utf-8"))
        self.assertIn("wims.launcher", front.read_text(encoding="utf-8"))
        self.assertIn("start-wims.sh", desk.read_text(encoding="utf-8"))
        self.assertIn("wims.launcher", cmd.read_text(encoding="utf-8"))
        self.assertIn("Install-WIMS-Desktop-Shortcut.cmd", bat.read_text(encoding="utf-8"))
        shortcut = ps1.read_text(encoding="utf-8")
        self.assertIn("WS Hub.lnk", shortcut)
        # An older "WIMS" launcher icon is replaced, not left beside it.
        self.assertIn('"WIMS.lnk"', shortcut)
        self.assertIn("Start Menu", shortcut)


class ZeroKnowledgeWordingTests(unittest.TestCase):
    def test_operator_docs_and_launcher_help(self):
        chunks = {
            "README": _user_facing((ROOT / "README.md").read_text(encoding="utf-8")),
            "scripts/README.md": (ROOT / "scripts" / "README.md").read_text(encoding="utf-8"),
            "setup.html": (ROOT / "src" / "wims" / "server" / "static" / "setup.html").read_text(
                encoding="utf-8"
            ),
            "log.html": (ROOT / "src" / "wims" / "server" / "static" / "log.html").read_text(
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
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
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

    def test_desktop_entry_is_named_ws_hub(self):
        from wims.launcher.app import linux_desktop_entry_text

        text = linux_desktop_entry_text()
        self.assertIn("Name=WS Hub\n", text)
        self.assertIn("Icon=", text)
        self.assertIn("scripts/start-wims.sh", text.replace("\\", "/"))
        self.assertIn("/bin/bash", text)
        self.assertIn("StartupWMClass=ws-hub\n", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertNotIn("-m ", text)

    def test_check_logs_is_in_the_app_not_a_desktop_icon(self):
        self.assertFalse((ROOT / "scripts" / "Check logs.sh").exists())
        self.assertFalse((ROOT / "scripts" / "Check logs.bat").exists())
        self.assertFalse((ROOT / "scripts" / "windows" / "Check-Logs.cmd").exists())
        from wims.launcher import app as launcher_app
        from wims.launcher.home_panel import AgentHomePanel

        self.assertFalse(hasattr(launcher_app, "linux_check_logs_desktop_entry_text"))
        src = (ROOT / "src" / "wims" / "launcher" / "home_panel.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Check logs"', src)
        self.assertIn("on_check_logs", src)
        shortcut = (ROOT / "scripts" / "windows" / "Install-WimsDesktopShortcut.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Check logs.lnk", shortcut)
        self.assertIn("Test-OurCheckLogs", shortcut)
        self.assertNotIn(
            'CreateShortcut($checkLnk)',
            shortcut,
        )
        self.assertIn("Removed the Check logs icon", shortcut)
        # The constructor still accepts the existing callers; the new
        # callback is optional.
        self.assertIn("on_check_logs", AgentHomePanel.__init__.__code__.co_varnames)

    def test_start_local_log_check_runs_the_existing_page(self):
        from wims.launcher.app import start_local_log_check

        with mock.patch("subprocess.Popen") as popen:
            popen.return_value = mock.Mock()
            start_local_log_check()
        args, kwargs = popen.call_args
        cmd = args[0]
        self.assertEqual(cmd[-2:], ["-m", "wims.logaudit.page"])
        self.assertTrue(kwargs.get("start_new_session") or "creationflags" in kwargs)
        self.assertNotIn("WIMS_CAPTURED_LOG", kwargs["env"])

    def test_remove_check_logs_shortcuts_deletes_ours_only(self):
        from wims.launcher import app as launcher_app

        if sys.platform.startswith("win"):
            self.skipTest("Linux desktop entries")
        ours = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Check logs\n"
            "Exec=/bin/bash /home/me/.local/share/ws-hub/scripts/Check logs.sh\n"
            "Path=/home/me/.local/share/ws-hub\n"
        )
        foreign = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Check logs\n"
            "Exec=/usr/bin/some-other-log-tool\n"
        )
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            desk = home / "Desktop"
            menu = home / ".local" / "share" / "applications"
            desk.mkdir(parents=True)
            menu.mkdir(parents=True)
            ours_desk = desk / "Check logs.desktop"
            ours_menu = menu / "Check logs.desktop"
            other = desk / "Other logs.desktop"
            ours_desk.write_text(ours, encoding="utf-8")
            ours_menu.write_text(ours, encoding="utf-8")
            # A differently named file is left even when the Exec looks like ours.
            other.write_text(ours, encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=home), mock.patch(
                "wims.launcher.app._refresh_applications_menu"
            ):
                removed = launcher_app.remove_check_logs_shortcuts()
            self.assertFalse(ours_desk.exists())
            self.assertFalse(ours_menu.exists())
            self.assertTrue(other.exists())
            self.assertEqual(sorted(p.name for p in removed), [
                "Check logs.desktop",
                "Check logs.desktop",
            ])
            # Foreign Check logs.desktop is left alone.
            ours_desk.write_text(foreign, encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=home), mock.patch(
                "wims.launcher.app._refresh_applications_menu"
            ):
                removed = launcher_app.remove_check_logs_shortcuts()
            self.assertEqual(removed, [])
            self.assertEqual(ours_desk.read_text(encoding="utf-8"), foreign)

    def test_windows_check_logs_lnk_bytes_are_recognized(self):
        from wims.launcher.app import (
            check_logs_desktop_entry_is_ours,
            windows_check_logs_shortcut_is_ours,
        )

        self.assertTrue(
            check_logs_desktop_entry_is_ours(
                "Exec=/bin/bash /opt/ws-hub/scripts/Check logs.sh\n"
            )
        )
        self.assertFalse(
            check_logs_desktop_entry_is_ours("Exec=/usr/bin/other-tool\n")
        )
        ours = "C:\\WIMS\\scripts\\windows\\Check-Logs.cmd".encode("utf-16-le")
        self.assertTrue(windows_check_logs_shortcut_is_ours(ours))
        self.assertFalse(
            windows_check_logs_shortcut_is_ours("C:\\Tools\\other.cmd".encode("utf-16-le"))
        )

    def test_second_click_raises_the_window_and_stays_quiet(self):
        from wims.launcher.app import announce_already_running

        def _forbidden(*_a, **_k):
            raise AssertionError("second start opened the site console")

        with mock.patch(
            "wims.launcher.handoff.request_running_launcher", return_value=True,
        ), mock.patch(
            "wims.launcher.app.open_wims_url", side_effect=_forbidden,
        ), mock.patch(
            "wims.launcher.app.probe_site_urls", side_effect=_forbidden,
        ), mock.patch(
            "wims.launcher.app.show_operator_message",
        ) as shown:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = announce_already_running()
        self.assertEqual(rc, 0)
        shown.assert_not_called()
        self.assertEqual(buf.getvalue(), "")

    def test_second_click_explains_when_the_window_does_not_answer(self):
        from wims.launcher.app import (
            ALREADY_RUNNING_UNREACHABLE,
            announce_already_running,
        )

        def _forbidden(*_a, **_k):
            raise AssertionError("second start opened the site console")

        with mock.patch(
            "wims.launcher.handoff.request_running_launcher", return_value=False,
        ), mock.patch(
            "wims.launcher.app.open_wims_url", side_effect=_forbidden,
        ), mock.patch(
            "wims.launcher.app.probe_site_urls", side_effect=_forbidden,
        ), mock.patch(
            "wims.launcher.app.show_operator_message",
        ) as shown:
            rc = announce_already_running()
        self.assertEqual(rc, 1)
        shown.assert_called_once_with(ALREADY_RUNNING_UNREACHABLE)
        self.assertIn("did not come forward", ALREADY_RUNNING_UNREACHABLE)
        self.assertIn("double-click", ALREADY_RUNNING_UNREACHABLE)
        self.assertEqual(_hits("already-running", ALREADY_RUNNING_UNREACHABLE), [])

    def test_unreachable_message_prints_when_no_dialog(self):
        import builtins

        from wims.launcher.app import show_operator_message

        real_import = builtins.__import__

        def block_tk(name, *args, **kwargs):
            if name == "tkinter" or name.startswith("tkinter."):
                raise ImportError("no window library")
            return real_import(name, *args, **kwargs)

        buf = io.StringIO()
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        with mock.patch("builtins.__import__", side_effect=block_tk), mock.patch.dict(
            os.environ, env, clear=True
        ), mock.patch("sys.stdout", buf):
            show_operator_message("Click the WIMS window if you can see it.")
        self.assertIn("Click the WIMS window", buf.getvalue())


class SoloLauncherPathTests(unittest.TestCase):
    def test_solo_starts_from_checkout(self):
        """scripts/start-wims-solo.sh, with no PYTHONPATH, serves /healthz and the Goal menu."""
        port = 18787
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        # The script runs the first python3 on PATH; make that this interpreter.
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
        env.pop("WIMS_CONTEST_RULES", None)
        env.pop("WIMS_LOGS", None)
        with tempfile.TemporaryDirectory() as td:
            env["XDG_CONFIG_HOME"] = td
            proc = subprocess.Popen(
                [
                    "bash", str(ROOT / "scripts" / "start-wims-solo.sh"),
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
