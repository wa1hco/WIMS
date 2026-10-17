# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update list, schedule, and install-only-when-asked."""

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

from wims.launcher.update_check import (
    AUTO_INSTALL,
    DEFAULT_CHECK_INTERVAL_S,
    MIN_CHECK_INTERVAL_S,
    HttpResult,
    apply_release,
    clamp_check_interval,
    gather_updates,
    list_github_releases,
    notes_tooltip,
    releases_from_payload,
    rollback_release,
    seconds_until_next_check,
    summarize_notes,
)


class ScheduleTests(unittest.TestCase):
    def test_default_is_a_few_hours_and_the_floor_holds(self):
        self.assertGreaterEqual(DEFAULT_CHECK_INTERVAL_S, 2 * 60 * 60)
        self.assertEqual(clamp_check_interval(DEFAULT_CHECK_INTERVAL_S), DEFAULT_CHECK_INTERVAL_S)
        self.assertEqual(clamp_check_interval(10), MIN_CHECK_INTERVAL_S)
        self.assertEqual(clamp_check_interval("nope"), DEFAULT_CHECK_INTERVAL_S)

    def test_wait_after_a_look(self):
        self.assertEqual(
            seconds_until_next_check(elapsed_s=0, interval_s=DEFAULT_CHECK_INTERVAL_S),
            DEFAULT_CHECK_INTERVAL_S,
        )
        self.assertEqual(
            seconds_until_next_check(elapsed_s=DEFAULT_CHECK_INTERVAL_S, interval_s=DEFAULT_CHECK_INTERVAL_S),
            0.0,
        )
        # A too-small interval is raised to the floor before the wait is computed.
        self.assertEqual(
            seconds_until_next_check(elapsed_s=0, interval_s=10),
            MIN_CHECK_INTERVAL_S,
        )

    def test_check_now_does_not_wait(self):
        delay = seconds_until_next_check(
            elapsed_s=5,
            interval_s=DEFAULT_CHECK_INTERVAL_S,
            rate_limit_wait_s=3600,
            force=True,
        )
        self.assertEqual(delay, 0.0)

    def test_rate_limit_can_only_lengthen_the_wait(self):
        self.assertEqual(
            seconds_until_next_check(
                elapsed_s=0,
                interval_s=DEFAULT_CHECK_INTERVAL_S,
                rate_limit_wait_s=30,
            ),
            DEFAULT_CHECK_INTERVAL_S,
        )
        self.assertEqual(
            seconds_until_next_check(
                elapsed_s=DEFAULT_CHECK_INTERVAL_S,
                interval_s=DEFAULT_CHECK_INTERVAL_S,
                rate_limit_wait_s=120,
            ),
            120.0,
        )

    def test_background_look_does_not_install(self):
        self.assertFalse(AUTO_INSTALL)
        info = mock.Mock(available=True)
        with mock.patch("wims.launcher.update_check.check_for_update", return_value=info):
            with mock.patch(
                "wims.launcher.update_check.list_github_releases",
                return_value=((), "", 0.0),
            ):
                with mock.patch("wims.launcher.update_check.apply_release") as install:
                    with mock.patch("wims.launcher.update_check.rollback_release") as back:
                        snap = gather_updates(ROOT, fetch=False)
        install.assert_not_called()
        back.assert_not_called()
        self.assertTrue(snap.info.available)
        self.assertEqual(snap.releases, ())


class ReleaseListTests(unittest.TestCase):
    def test_rows_show_version_date_and_notes(self):
        payload = [
            {
                "tag_name": "v1.0.16",
                "name": "v1.0.16",
                "published_at": "2026-09-13T12:00:00Z",
                "body": "Halt stays live.\n\nMore detail.",
                "html_url": "https://example.test/1.0.16",
                "prerelease": False,
            },
            {
                "tag_name": "v1.2.0",
                "name": "September fixes",
                "published_at": "2026-10-01T08:00:00Z",
                "body": "Fixed the roster sort.",
                "html_url": "https://example.test/1.2.0",
                "prerelease": False,
            },
        ]
        rows = releases_from_payload(payload, local_version="1.0.16")
        self.assertEqual(rows[0].tag, "v1.2.0")
        self.assertEqual(rows[0].relation, "newer")
        self.assertEqual(rows[0].published, "2026-10-01")
        self.assertIn("available", rows[0].line())
        self.assertIn("Fixed the roster", rows[0].summary())
        self.assertIn("Fixed the roster", notes_tooltip(rows[0]))
        self.assertEqual(rows[1].relation, "current")
        self.assertIn("this copy", rows[1].line())

    def test_empty_notes(self):
        self.assertIn("No notes", summarize_notes(""))
        self.assertTrue(summarize_notes("x" * 500).endswith("..."))

    def test_offline_and_rate_limit_are_quiet(self):
        offline = HttpResult(data=None, error="timed out", status=0)
        with mock.patch("wims.launcher.update_check.github_get", return_value=offline):
            rows, notice, wait = list_github_releases(ROOT)
        self.assertEqual(rows, ())
        self.assertEqual(notice, "offline")
        self.assertEqual(wait, 0.0)

        limited = HttpResult(
            data=None, error="rate limit", status=403,
            rate_limited=True, retry_after_s=90,
        )
        with mock.patch("wims.launcher.update_check.github_get", return_value=limited):
            rows, notice, wait = list_github_releases(ROOT)
        self.assertEqual(notice, "rate_limit")
        self.assertEqual(wait, 90.0)
        self.assertNotIn("ERROR", notice)


class ApplyReleaseTests(unittest.TestCase):
    def test_refuses_a_non_git_tree(self):
        with tempfile.TemporaryDirectory() as td:
            ok, msg = apply_release(Path(td), "v1.2.0")
        self.assertFalse(ok)
        self.assertIn("not installed from git", msg)
        self.assertNotIn("python", msg.lower())

    def test_refuses_local_edits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            with mock.patch("wims.launcher.update_check._git", return_value=(0, " M file")):
                ok, msg = apply_release(root, "v1.2.0")
        self.assertFalse(ok)
        self.assertIn("local edits", msg)
        self.assertIn("unchanged", msg)

    def test_saves_a_way_back_then_switches(self):
        calls = []

        def fake_git(repo, args, timeout=30.0):
            calls.append(list(args))
            if args[:2] == ["status", "--porcelain"]:
                return 0, ""
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                return 0, "main"
            if args[:2] == ["rev-parse", "HEAD"]:
                return 0, "abc123"
            if args[0] == "fetch":
                return 0, ""
            if args[0] == "checkout":
                return 0, ""
            return 1, "unexpected"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            remembered = Path(td) / "back.json"
            progress = []
            with mock.patch("wims.launcher.update_check._git", side_effect=fake_git):
                ok, msg = apply_release(
                    root, "v1.2.0",
                    rollback_file=remembered,
                    on_progress=progress.append,
                )
            self.assertTrue(ok, msg)
            self.assertIn("v1.2.0", msg)
            self.assertTrue(remembered.is_file())
            self.assertIn("abc123", remembered.read_text(encoding="utf-8"))
            self.assertTrue(any(c[0] == "checkout" for c in calls))
            self.assertTrue(progress)

    def test_go_back_without_a_saved_copy(self):
        with tempfile.TemporaryDirectory() as td:
            ok, msg = rollback_release(
                Path(td), rollback_file=Path(td) / "missing.json",
            )
        self.assertFalse(ok)
        self.assertIn("no saved previous copy", msg)

    def test_go_back_checks_out_the_saved_branch(self):
        calls = []

        def fake_git(repo, args, timeout=30.0):
            calls.append(list(args))
            if args[:2] == ["status", "--porcelain"]:
                return 0, ""
            if args[:2] == ["rev-parse", "main"]:
                return 0, "abc123"
            if args[0] == "checkout":
                return 0, ""
            return 1, "unexpected"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            remembered = Path(td) / "back.json"
            remembered.write_text(
                '{"schema": 1, "sha": "abc123", "branch": "main", "tag": "v9.9.9"}\n',
                encoding="utf-8",
            )
            with mock.patch("wims.launcher.update_check._git", side_effect=fake_git):
                ok, msg = rollback_release(root, rollback_file=remembered)
        self.assertTrue(ok)
        self.assertIn("previous copy", msg)
        self.assertIn(["checkout", "main"], calls)


if __name__ == "__main__":
    unittest.main()
