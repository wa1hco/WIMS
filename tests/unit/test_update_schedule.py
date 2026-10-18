# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update list, schedule, and install-only-when-asked."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone, tzinfo
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
    _bucket_commits,
    _local_dates,
    _note_spans,
    _published_day,
    apply_release,
    clamp_check_interval,
    clear_release_note_cache,
    gather_updates,
    list_github_releases,
    notes_from_subjects,
    notes_tooltip,
    releases_from_payload,
    rollback_release,
    seconds_until_next_check,
    summarize_notes,
)


def _local_day(iso: str) -> str:
    """Calendar day in the process time zone, independent of the list code."""
    text = iso[:-1] + "+00:00" if iso.endswith(("Z", "z")) else iso
    return datetime.fromisoformat(text).astimezone().strftime("%Y-%m-%d")


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


def _release(tag: str, body: str = "Notes.", day: str = "2026-09-12T00:00:00Z") -> dict:
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": day,
        "body": body,
        "html_url": f"https://example.test/{tag}",
        "prerelease": False,
    }


def _tag(name: str, sha: str) -> dict:
    return {"name": name, "commit": {"sha": sha}}


def _commit(sha: str, message: str, day: str) -> dict:
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "committer": {"date": day},
        },
    }


class ReleaseListTests(unittest.TestCase):
    def tearDown(self):
        clear_release_note_cache()
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
        self.assertEqual(rows[0].published, _local_day("2026-10-01T08:00:00Z"))
        self.assertIn("available", rows[0].line())
        self.assertIn("Fixed the roster", rows[0].summary())
        tip = notes_tooltip(rows[0])
        self.assertIn("Fixed the roster", tip)
        self.assertIn(_local_day("2026-10-01T08:00:00Z"), tip)
        self.assertTrue(tip.splitlines()[0].endswith(("AM", "PM")))
        self.assertEqual(rows[1].relation, "current")
        self.assertIn("this copy", rows[1].line())
        self.assertIn(_local_day("2026-09-13T12:00:00Z"), rows[1].line())

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

    def test_a_raised_lookup_stays_quiet(self):
        with mock.patch(
            "wims.launcher.update_check.github_get",
            side_effect=OSError("network down"),
        ):
            rows, notice, wait = list_github_releases(ROOT)
        self.assertEqual(rows, ())
        self.assertEqual(notice, "offline")
        self.assertEqual(wait, 0.0)

    def test_pages_keep_versions_past_the_first_page(self):
        page1 = [_release(f"v1.0.{i}") for i in range(100)]
        page2 = [_release("v2.0.0", body="Newest."), _release("v0.9.0", body="Old.")]

        def fake(url, timeout=8.0):
            if "/tags?" in url:
                return HttpResult(data=[])
            if "&page=2" in url:
                return HttpResult(data=page2)
            if "&page=1" in url:
                return HttpResult(data=page1)
            return HttpResult(data=[])

        with mock.patch("wims.launcher.update_check.github_get", side_effect=fake):
            rows, notice, wait = list_github_releases(ROOT)
        tags = [row.tag for row in rows]
        self.assertEqual(notice, "")
        self.assertEqual(wait, 0.0)
        self.assertEqual(tags[0], "v2.0.0")
        self.assertIn("v1.0.0", tags)
        self.assertIn("v0.9.0", tags)
        self.assertEqual(len(tags), 102)

    def test_tags_without_a_release_join_the_list(self):
        calls = []

        def fake(url, timeout=8.0):
            calls.append(url)
            if "/releases?" in url:
                return HttpResult(data=[
                    _release("v1.0.10", body="Published notes for 1.0.10."),
                    _release("v1.0.0", body="First release."),
                ])
            if "/tags?" in url:
                return HttpResult(data=[
                    _tag("v1.0.16", "b" * 40),
                    _tag("v1.0.15", "c" * 40),
                    _tag("v1.0.10", "d" * 40),
                    _tag("v1.0.0", "e" * 40),
                    _tag("not-a-version", "f" * 40),
                ])
            if "/compare/" in url:
                self.assertIn("v1.0.10...v1.0.16", url)
                return HttpResult(data={
                    "total_commits": 3,
                    "commits": [
                        _commit("a" * 40, "Prep the next tag.\n\nDetail.", "2026-09-13T00:00:00Z"),
                        _commit("c" * 40, "Release 1.0.15: N1MM operator.", "2026-09-13T12:00:00Z"),
                        _commit("b" * 40, "Release 1.0.16: Halt stays live.", "2026-09-14T03:04:22Z"),
                    ],
                })
            return HttpResult(data=None, error="unexpected")

        with mock.patch("wims.launcher.update_check._local_version", return_value="1.0.16"):
            with mock.patch("wims.launcher.update_check.github_get", side_effect=fake):
                rows, notice, _wait = list_github_releases(ROOT)
        self.assertEqual(notice, "")
        tags = [row.tag for row in rows]
        self.assertEqual(tags, ["v1.0.16", "v1.0.15", "v1.0.10", "v1.0.0"])
        self.assertEqual(rows[0].relation, "current")
        self.assertIn("this copy", rows[0].line())
        self.assertIn(_local_day("2026-09-14T03:04:22Z"), rows[0].line())
        self.assertIn("Halt stays live", rows[0].summary())
        self.assertIn("N1MM operator", rows[1].summary())
        self.assertEqual(rows[0].published, _local_day("2026-09-14T03:04:22Z"))
        tip = notes_tooltip(rows[0])
        self.assertIn(_local_day("2026-09-14T03:04:22Z"), tip)
        self.assertTrue(tip.splitlines()[0].endswith(("AM", "PM")))
        self.assertIn("Published notes", rows[2].summary())
        self.assertEqual(sum(1 for url in calls if "/compare/" in url), 1)

        calls.clear()
        with mock.patch("wims.launcher.update_check._local_version", return_value="1.0.16"):
            with mock.patch("wims.launcher.update_check.github_get", side_effect=fake):
                again, notice, _wait = list_github_releases(ROOT)
        self.assertEqual(notice, "")
        self.assertEqual([row.tag for row in again], tags)
        self.assertFalse(any("/compare/" in url for url in calls))

    def test_compare_offline_still_lists_the_tag(self):
        def fake(url, timeout=8.0):
            if "/releases?" in url:
                return HttpResult(data=[_release("v1.0.10", body="Shipped.")])
            if "/tags?" in url:
                return HttpResult(data=[
                    _tag("v1.0.16", "b" * 40),
                    _tag("v1.0.10", "d" * 40),
                ])
            return HttpResult(data=None, error="timed out", status=0)

        with mock.patch("wims.launcher.update_check._local_version", return_value="1.0.10"):
            with mock.patch("wims.launcher.update_check.github_get", side_effect=fake):
                rows, notice, _wait = list_github_releases(ROOT)
        self.assertEqual(notice, "")
        self.assertEqual([row.tag for row in rows], ["v1.0.16", "v1.0.10"])
        self.assertIn("this copy", rows[1].line())
        self.assertIn("No notes", rows[0].summary())

    def test_commit_buckets_follow_the_tags(self):
        span = [("v1.0.11", "aaa1111"), ("v1.0.12", "bbb2222")]
        commits = [
            _commit("1111111", "before\n\nmore", "2026-09-13T00:00:00Z"),
            _commit("aaa1111", "Release 1.0.11: install", "2026-09-13T01:00:00Z"),
            _commit("bbb2222", "Release 1.0.12: n1mm", "2026-09-14T00:00:00Z"),
        ]
        subjects, dates, matched = _bucket_commits(commits, span)
        self.assertEqual(matched, {"v1.0.11", "v1.0.12"})
        self.assertIn("before", notes_from_subjects(subjects["v1.0.11"]))
        self.assertIn("install", notes_from_subjects(subjects["v1.0.11"]))
        self.assertEqual(notes_from_subjects(subjects["v1.0.12"]), "Release 1.0.12: n1mm")
        self.assertEqual(dates["v1.0.12"][:10], "2026-09-14")
        spans = _note_spans(
            [("v1.0.0", "a"), ("v1.0.1", "b"), ("v1.0.10", "c"), ("v1.0.16", "d")],
            {"v1.0.0", "v1.0.10"},
        )
        self.assertEqual(spans[0][0], "v1.0.0")
        self.assertEqual([name for name, _sha in spans[0][1]], ["v1.0.1"])
        self.assertEqual(spans[1][0], "v1.0.10")
        self.assertEqual([name for name, _sha in spans[1][1]], ["v1.0.16"])

    def _expect_late_evening(self, tz: tzinfo | None) -> None:
        """v1.0.16 at 2026-09-14 03:04 UTC is 2026-09-13 11:04 PM in UTC-4."""
        late = "2026-09-14T03:04:00Z"
        rows = releases_from_payload(
            [{
                "tag_name": "v1.0.16",
                "name": "v1.0.16",
                "published_at": late,
                "body": "Halt stays live.",
                "html_url": "https://example.test/1.0.16",
                "prerelease": False,
            }],
            local_version="1.0.16",
            tz=tz,
        )
        self.assertEqual(rows[0].published, "2026-09-13")
        self.assertIn("2026-09-13", rows[0].line())
        self.assertIn("this copy", rows[0].line())
        self.assertIn("2026-09-13 11:04 PM", notes_tooltip(rows[0]))

        def commit_only(url, timeout=8.0):
            if "/releases?" in url:
                return HttpResult(data=[])
            if "/tags?" in url:
                return HttpResult(data=[_tag("v1.0.16", "b" * 40)])
            if "/commits/" in url:
                return HttpResult(data=_commit(
                    "b" * 40, "Release 1.0.16: Halt stays live.", late,
                ))
            return HttpResult(data=None, error="unexpected")

        with mock.patch("wims.launcher.update_check._local_version", return_value="1.0.16"):
            with mock.patch("wims.launcher.update_check.github_get", side_effect=commit_only):
                tagged, notice, _wait = list_github_releases(ROOT, tz=tz)
        self.assertEqual(notice, "")
        self.assertEqual(tagged[0].tag, "v1.0.16")
        self.assertEqual(tagged[0].published, "2026-09-13")
        self.assertIn("this copy", tagged[0].line())
        self.assertIn("2026-09-13 11:04 PM", notes_tooltip(tagged[0]))
        clear_release_note_cache()

        def compared(url, timeout=8.0):
            if "/releases?" in url:
                return HttpResult(data=[_release("v1.0.10", body="Shipped.")])
            if "/tags?" in url:
                return HttpResult(data=[
                    _tag("v1.0.16", "b" * 40),
                    _tag("v1.0.10", "d" * 40),
                ])
            if "/compare/" in url:
                return HttpResult(data={
                    "total_commits": 1,
                    "commits": [
                        _commit("b" * 40, "Release 1.0.16: Halt stays live.", late),
                    ],
                })
            return HttpResult(data=None, error="unexpected")

        with mock.patch("wims.launcher.update_check._local_version", return_value="1.0.16"):
            with mock.patch("wims.launcher.update_check.github_get", side_effect=compared):
                merged, notice, _wait = list_github_releases(ROOT, tz=tz)
        self.assertEqual(notice, "")
        self.assertEqual(merged[0].tag, "v1.0.16")
        self.assertEqual(merged[0].published, "2026-09-13")
        self.assertIn("this copy", merged[0].line())
        self.assertIn("Halt stays live", merged[0].summary())
        self.assertIn("2026-09-13 11:04 PM", notes_tooltip(merged[0]))

    def test_late_evening_follows_the_process_time_zone(self):
        if not hasattr(time, "tzset"):
            self.skipTest("Windows has no time.tzset; the injected-zone test covers this")
        if not Path("/usr/share/zoneinfo/America/New_York").is_file():
            self.skipTest("America/New_York is not installed")
        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            shifted = datetime(2026, 9, 14, 3, 4, tzinfo=timezone.utc).astimezone()
            self.assertEqual(shifted.strftime("%Y-%m-%d %H:%M"), "2026-09-13 23:04")
            self._expect_late_evening(None)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_late_evening_with_an_injected_zone(self):
        self._expect_late_evening(timezone(timedelta(hours=-4)))

    def test_a_date_with_no_clock_stays_that_day(self):
        day, stamp = _local_dates("2026-09-14", tz=timezone(timedelta(hours=-4)))
        self.assertEqual(day, "2026-09-14")
        self.assertEqual(stamp, "2026-09-14")
        self.assertNotIn("PM", stamp)
        self.assertNotIn("AM", stamp)
        self.assertEqual(
            _published_day("2026-09-14T03:04:00Z", tz=timezone(timedelta(hours=-4))),
            "2026-09-13",
        )

    def test_unreadable_date_falls_back_without_raising(self):
        day, stamp = _local_dates("2026-09-14T99:99:99Z")
        self.assertEqual(day, "2026-09-14")
        self.assertEqual(stamp, "2026-09-14")
        day, stamp = _local_dates("not-a-timestamp")
        self.assertEqual(day, "not-a-time")
        self.assertEqual(stamp, day)
        fractional, frac_stamp = _local_dates(
            "2026-09-14T03:04:22.000Z",
            tz=timezone(timedelta(hours=-4)),
        )
        self.assertEqual(fractional, "2026-09-13")
        self.assertEqual(frac_stamp, "2026-09-13 11:04 PM")

        class Boom(tzinfo):
            def utcoffset(self, dt):
                raise RuntimeError("boom")

            def dst(self, dt):
                raise RuntimeError("boom")

            def tzname(self, dt):
                return "Boom"

        day, stamp = _local_dates("2026-09-14T03:04:00Z", tz=Boom())
        self.assertEqual(day, "2026-09-14")
        self.assertEqual(stamp, "2026-09-14")


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
