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

from wims.launcher.update_check import (
    UpdateInfo,
    check_for_update,
    check_git_update,
    check_github_release,
)


class UpdateCheckTests(unittest.TestCase):
    def test_not_git(self):
        with tempfile.TemporaryDirectory() as td:
            info = check_git_update(Path(td), fetch=False)
        self.assertFalse(info.is_git)
        self.assertFalse(info.available)

    def test_behind_available(self):
        def fake_git(repo, args, timeout=30.0):
            a = list(args)
            if a[:2] == ["rev-parse", "HEAD"]:
                return 0, "aaa1111localsha"
            if a[:2] == ["status", "--porcelain"]:
                return 0, ""
            if a and a[0] == "fetch":
                return 0, ""
            if a[:2] == ["rev-parse", "origin/main"]:
                return 0, "bbb2222remotesha"
            if a[:2] == ["merge-base", "--is-ancestor"]:
                return 0, ""
            if a and a[0] == "log":
                return 0, "Fix launcher update"
            return 1, "unexpected " + " ".join(a)

        with mock.patch("wims.launcher.update_check._git", side_effect=fake_git):
            info = check_git_update(ROOT, fetch=True)
        self.assertTrue(info.is_git)
        self.assertTrue(info.available)
        self.assertEqual(info.local_short, "aaa1111")
        self.assertEqual(info.remote_short, "bbb2222")
        self.assertIn("Fix launcher", info.remote_subject)

    def test_up_to_date(self):
        def fake_git(repo, args, timeout=30.0):
            a = list(args)
            if a[:2] == ["rev-parse", "HEAD"]:
                return 0, "same000abcdef"
            if a[:2] == ["status", "--porcelain"]:
                return 0, ""
            if a and a[0] == "fetch":
                return 0, ""
            if a[:2] == ["rev-parse", "origin/main"]:
                return 0, "same000abcdef"
            return 1, "no"

        with mock.patch("wims.launcher.update_check._git", side_effect=fake_git):
            info = check_git_update(ROOT, fetch=True)
        self.assertTrue(info.is_git)
        self.assertFalse(info.available)
        self.assertEqual(info.detail, "up to date")

    def test_fetch_fail_soft(self):
        def fake_git(repo, args, timeout=30.0):
            a = list(args)
            if a[:2] == ["rev-parse", "HEAD"]:
                return 0, "abc"
            if a[:2] == ["status", "--porcelain"]:
                return 0, ""
            if a and a[0] == "fetch":
                return 1, "network down"
            return 1, "no"

        with mock.patch("wims.launcher.update_check._git", side_effect=fake_git):
            info = check_git_update(ROOT, fetch=True)
        self.assertFalse(info.available)
        self.assertIn("fetch failed", info.detail)

    def test_update_info_shorts(self):
        u = UpdateInfo(available=True, local_sha="abcdef0123", remote_sha="fedcba9876")
        self.assertEqual(u.local_short, "abcdef0")
        self.assertEqual(u.remote_short, "fedcba9")


class GitHubReleaseCheckTests(unittest.TestCase):
    def test_zip_tree_newer_release(self):
        def fake_http(url, timeout=8.0):
            if url.endswith("/releases/latest"):
                return {
                    "tag_name": "v1.1.0",
                    "html_url": "https://github.com/wa1hco/WIMS/releases/tag/v1.1.0",
                    "name": "WIMS 1.1.0",
                    "published_at": "2026-09-11T00:00:00Z",
                }, ""
            if "/commits/" in url:
                return {"sha": "b" * 40}, ""
            if "/compare/" in url:
                return {"status": "behind"}, ""
            return None, "unexpected " + url

        with tempfile.TemporaryDirectory() as td:
            Path(td, "manifest.json").write_text(
                json.dumps({"version": "1.0.0", "git_sha": "a" * 40}),
                encoding="utf-8",
            )
            with mock.patch("wims.launcher.update_check._http_json", side_effect=fake_http):
                info = check_github_release(Path(td))
        self.assertTrue(info.available)
        self.assertEqual(info.source, "release")
        self.assertEqual(info.release_tag, "v1.1.0")
        self.assertFalse(info.is_git)

    def test_same_release_sha_not_available(self):
        sha = "c" * 40

        def fake_http(url, timeout=8.0):
            if url.endswith("/releases/latest"):
                return {
                    "tag_name": "v1.0.0",
                    "html_url": "https://github.com/wa1hco/WIMS/releases/tag/v1.0.0",
                    "name": "WIMS 1.0.0",
                    "published_at": "2026-09-07T00:00:00Z",
                }, ""
            if "/commits/" in url:
                return {"sha": sha}, ""
            return None, "unexpected " + url

        with tempfile.TemporaryDirectory() as td:
            Path(td, "manifest.json").write_text(
                json.dumps({"version": "1.0.0", "git_sha": sha}),
                encoding="utf-8",
            )
            with mock.patch("wims.launcher.update_check._http_json", side_effect=fake_http):
                info = check_github_release(Path(td))
        self.assertFalse(info.available)
        self.assertIn("up to date", info.detail)

    def test_version_only_when_compare_unknown(self):
        def fake_http(url, timeout=8.0):
            if url.endswith("/releases/latest"):
                return {
                    "tag_name": "v1.2.0",
                    "html_url": "https://example.test/rel",
                    "name": "WIMS 1.2.0",
                    "published_at": "2026-09-11T00:00:00Z",
                }, ""
            if "/commits/" in url:
                return {"sha": ""}, ""
            return None, "no"

        with tempfile.TemporaryDirectory() as td:
            Path(td, "manifest.json").write_text(
                json.dumps({"version": "1.0.0"}),
                encoding="utf-8",
            )
            with mock.patch("wims.launcher.update_check._http_json", side_effect=fake_http):
                info = check_github_release(Path(td))
        self.assertTrue(info.available)
        self.assertEqual(info.release_tag, "v1.2.0")

    def test_check_for_update_prefers_git_when_behind_main(self):
        git_info = UpdateInfo(
            available=True, is_git=True, source="git",
            local_sha="aaa", remote_sha="bbb", detail="update available",
        )
        rel_info = UpdateInfo(
            available=False, source="release", detail="up to date with GitHub Release",
        )
        with mock.patch("wims.launcher.update_check.check_git_update", return_value=git_info):
            with mock.patch(
                "wims.launcher.update_check.check_github_release", return_value=rel_info,
            ):
                info = check_for_update(ROOT, fetch=False)
        self.assertTrue(info.available)
        self.assertEqual(info.source, "git")

    def test_check_for_update_uses_release_when_not_git(self):
        git_info = UpdateInfo(
            available=False, is_git=False, detail="not a git checkout",
        )
        rel_info = UpdateInfo(
            available=True, is_git=False, source="release",
            release_tag="v1.1.0", remote_sha="b" * 40, detail="update available",
        )
        with mock.patch("wims.launcher.update_check.check_git_update", return_value=git_info):
            with mock.patch(
                "wims.launcher.update_check.check_github_release", return_value=rel_info,
            ):
                info = check_for_update(Path("."), fetch=False)
        self.assertTrue(info.available)
        self.assertEqual(info.source, "release")
        self.assertEqual(info.release_tag, "v1.1.0")


if __name__ == "__main__":
    unittest.main()
