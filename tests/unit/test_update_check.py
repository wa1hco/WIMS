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

from wims.launcher.update_check import UpdateInfo, check_git_update


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


if __name__ == "__main__":
    unittest.main()
