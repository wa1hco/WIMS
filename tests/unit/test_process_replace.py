# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for safe seat-agent replace (no real process kills)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.process_replace import (
    classify_argv,
    find_procs_by_kind,
    hide_console_windows_for_pids,
    hide_own_console_if_redirected,
    iter_wims_procs,
    list_process_table,
    other_agent_running,
    replace_seat_agents,
    windows_hidden_popen_kwargs,
)


class ClassifyTests(unittest.TestCase):
    def test_log_module(self):
        self.assertEqual(
            classify_argv(["python", "-u", "-m", "wims.log"]),
            "log",
        )

    def test_seat_daemon_only(self):
        self.assertEqual(
            classify_argv([
                "python3", "-u", "-m", "wims.agent",
                "--daemon", "--local-port", "8790",
            ]),
            "seat",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims.agent", "--once"]),
            "other",
        )

    def test_key_daemon_not_selftest(self):
        self.assertEqual(
            classify_argv(["python", "-m", "wims.key", "daemon", "--no-gui"]),
            "key",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims.key", "selftest"]),
            "other",
        )

    def test_n1mm_seat_module(self):
        self.assertEqual(
            classify_argv(["python", "-m", "wims.seat", "--log", "--key"]),
            "n1mm_seat",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims", "seat", "--log"]),
            "n1mm_seat",
        )

    def test_server_protected_class(self):
        self.assertEqual(
            classify_argv(["python", "-u", "-m", "wims.server.app"]),
            "server",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims.server"]),
            "server",
        )

    def test_launcher_not_killed(self):
        self.assertEqual(classify_argv(["python", "-m", "wims"]), "other")
        self.assertEqual(classify_argv(["python", "-m", "wims.launcher"]), "other")
        self.assertEqual(classify_argv(["python", "-m", "wims", "gui"]), "other")

    def test_top_level_cli_roles(self):
        self.assertEqual(
            classify_argv(["python", "-m", "wims", "log", "--no-gui"]),
            "log",
        )
        self.assertEqual(
            classify_argv([
                "python", "-m", "wims", "agent", "--daemon", "--local-port", "8790",
            ]),
            "seat",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims", "key", "daemon"]),
            "key",
        )
        self.assertEqual(
            classify_argv(["python", "-m", "wims", "server"]),
            "server",
        )


class ReplaceTests(unittest.TestCase):
    def test_replace_kills_seat_only(self):
        table = [
            (101, ["python", "-m", "wims.log"]),
            (102, ["python", "-m", "wims.agent", "--daemon"]),
            (103, ["python", "-m", "wims.key", "daemon"]),
            (104, ["python", "-m", "wims.server.app"]),
            (105, ["python", "-m", "wims.agent", "--once"]),
            (106, ["/home/jeff/ham/wsjtx-inhibit/build/wsjtx"]),
        ]
        killed: list[int] = []

        def fake_stop(pid, **_kw):
            killed.append(pid)

        report = replace_seat_agents(table=table, stop=fake_stop, exclude_pids=())
        self.assertEqual(sorted(killed), [101, 102, 103])
        self.assertEqual({p.kind for p in report.stopped}, {"log", "seat", "key"})
        self.assertEqual(len(report.skipped_server), 1)
        self.assertEqual(report.skipped_server[0].pid, 104)
        # one-shot agent and wsjtx never classified into found as seat/log/key/server
        kinds = {p.kind for p in report.found}
        self.assertNotIn("other", kinds)
        self.assertEqual(kinds, {"log", "seat", "key", "server"})

    def test_exclude_own_pid(self):
        table = [
            (999, ["python", "-m", "wims.log"]),
            (1000, ["python", "-m", "wims.agent", "--daemon"]),
        ]
        procs = iter_wims_procs(table, exclude_pids=(999,))
        self.assertEqual([p.pid for p in procs], [1000])

    def test_dry_run_does_not_call_stop(self):
        table = [(50, ["python", "-m", "wims.log"])]
        calls = []
        report = replace_seat_agents(
            table=table,
            stop=lambda pid, **kw: calls.append(pid),
            dry_run=True,
        )
        self.assertEqual(calls, [])
        self.assertEqual(len(report.stopped), 1)

    def test_find_procs_by_kind(self):
        table = [
            (10, ["python", "-m", "wims.log"]),
            (11, ["python", "-m", "wims.agent", "--daemon"]),
            (12, ["python", "-m", "wims.server.app"]),
        ]
        logs = find_procs_by_kind("log", table=table)
        self.assertEqual([p.pid for p in logs], [10])
        seats = find_procs_by_kind("seat", table=table)
        self.assertEqual([p.pid for p in seats], [11])

    def test_other_agent_running_with_table(self):
        from unittest import mock
        table = [(42, ["python", "-m", "wims.agent", "--daemon", "--local-port", "8790"])]
        with mock.patch(
            "wims.launcher.process_replace.iter_wims_procs",
            return_value=find_procs_by_kind("seat", table=table),
        ):
            other = other_agent_running("seat")
        self.assertIsNotNone(other)
        self.assertEqual(other.pid, 42)


class ProcessTableCacheTests(unittest.TestCase):
    def test_list_process_table_uses_ttl_cache(self):
        import time
        from unittest import mock
        import wims.launcher.process_replace as pr

        fake = [(7, ["python", "-m", "wims.log"])]
        pr._proc_table = fake
        pr._proc_table_ts = time.monotonic()
        with mock.patch.object(
            pr, "_windows_powershell_table", side_effect=AssertionError("cache miss")
        ):
            with mock.patch.object(
                pr, "_windows_wmic_table", side_effect=AssertionError("cache miss")
            ):
                with mock.patch.object(
                    pr, "_linux_proc_table", side_effect=AssertionError("cache miss")
                ):
                    rows = list_process_table()
        self.assertEqual(rows, fake)

    def test_list_process_table_fresh_bypasses_cache(self):
        import time
        from unittest import mock
        import wims.launcher.process_replace as pr

        pr._proc_table = [(1, ["stale"])]
        pr._proc_table_ts = time.monotonic()
        with mock.patch.object(pr, "os") as osmod:
            osmod.name = "posix"
            with mock.patch.object(pr, "_linux_proc_table", return_value=[(2, ["fresh"])]):
                with mock.patch.object(pr, "_linux_ps_table", return_value=[]):
                    rows = list_process_table(fresh=True)
        self.assertEqual(rows, [(2, ["fresh"])])


class HiddenConsoleTests(unittest.TestCase):
    def test_hide_empty_pids(self):
        self.assertEqual(hide_console_windows_for_pids([]), 0)

    def test_hide_noop_on_posix(self):
        from unittest import mock
        with mock.patch("wims.launcher.process_replace.os.name", "posix"):
            self.assertEqual(hide_console_windows_for_pids([1, 2]), 0)
            self.assertEqual(windows_hidden_popen_kwargs(), {})
            self.assertFalse(hide_own_console_if_redirected())

    def test_keep_console_env(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {"WIMS_KEEP_CONSOLE": "1"}):
            with mock.patch("wims.launcher.process_replace.os.name", "nt"):
                self.assertFalse(hide_own_console_if_redirected())

    def test_keep_console_when_tty(self):
        from unittest import mock
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch("wims.launcher.process_replace.os.name", "nt"):
            with mock.patch.dict("os.environ", {"WIMS_KEEP_CONSOLE": ""}, clear=False):
                with mock.patch("wims.launcher.process_replace.sys.stdout", tty):
                    self.assertFalse(hide_own_console_if_redirected())

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows only")
    def test_windows_hidden_popen_kwargs(self):
        kw = windows_hidden_popen_kwargs()
        self.assertIn("creationflags", kw)
        self.assertTrue(kw["creationflags"])
        self.assertIn("startupinfo", kw)


if __name__ == "__main__":
    unittest.main()
