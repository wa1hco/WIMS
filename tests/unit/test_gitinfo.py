# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision identity: git checkout, release tree with stamp, release without."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims import __version__  # noqa: E402
from wims.gitinfo import (  # noqa: E402
    STAMP_FILENAME,
    collect_build_identity,
    git_stamp,
    git_stamp_fresh,
    read_build_stamp,
    write_build_stamp,
)


def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "WS Hub Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "WS Hub Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args],
        text=True,
        env=env,
        stderr=subprocess.DEVNULL,
    ).strip()


def _init_repo(path: Path, message: str = "init") -> str:
    _git(path, "init")
    _git(path, "config", "user.name", "WS Hub Test")
    _git(path, "config", "user.email", "test@example.com")
    (path / "README").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README")
    _git(path, "commit", "-m", message)
    return _git(path, "log", "-1", "--format=%h %ci")


class GitinfoTests(unittest.TestCase):
    def tearDown(self):
        git_stamp.cache_clear()

    def test_git_tree_uses_head_not_a_stamp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = _init_repo(root)
            write_build_stamp(
                root, version="9.9.9", commit="deadbeef" * 5,
                stamp="deadbee 2020-01-01 00:00:00 +0000",
            )
            git_stamp.cache_clear()
            got = git_stamp_fresh(root)
            self.assertEqual(got, expected)
            self.assertNotIn("deadbee", got)
            self.assertTrue(got.split()[0])
            self.assertNotEqual(got, "?")

    def test_release_tree_with_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamp = "abc1234 2026-11-12 00:08:15 -0500"
            write_build_stamp(
                root,
                version="1.0.20",
                commit="abc1234fffffffffffffffffffffffffffffff",
                stamp=stamp,
            )
            git_stamp.cache_clear()
            self.assertEqual(git_stamp_fresh(root), stamp)
            fields = read_build_stamp(root)
            self.assertEqual(fields["version"], "1.0.20")
            self.assertTrue(fields["commit"].startswith("abc1234"))
            self.assertEqual((root / STAMP_FILENAME).name, "BUILD_STAMP")

    def test_release_tree_without_stamp_falls_back_to_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_stamp.cache_clear()
            self.assertEqual(git_stamp_fresh(root), __version__)
            self.assertNotEqual(git_stamp_fresh(root), "?")

    def test_parent_git_repo_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            expected = _init_repo(parent)
            release = parent / "share" / "ws-hub"
            release.mkdir(parents=True)
            git_stamp.cache_clear()
            # No .git and no stamp in the release folder: version, not parent SHA.
            self.assertEqual(git_stamp_fresh(release), __version__)
            self.assertNotEqual(git_stamp_fresh(release), expected)
            stamp = "c0ffee0 2026-11-12 01:00:00 -0500"
            write_build_stamp(release, version="1.0.20", commit="c0ffee0", stamp=stamp)
            git_stamp.cache_clear()
            self.assertEqual(git_stamp_fresh(release), stamp)

    def test_collect_identity_from_this_checkout(self):
        ident = collect_build_identity(ROOT, "1.0.20")
        self.assertEqual(ident["version"], "1.0.20")
        self.assertEqual(len(ident["commit"]), 40)
        self.assertTrue(ident["stamp"].startswith(ident["commit"][:7]))


if __name__ == "__main__":
    unittest.main()
