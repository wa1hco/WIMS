# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Banner update button: one obvious action per kind of install."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.update_check import (  # noqa: E402
    UpdateInfo,
    banner_update_action,
)


def _info(**kwargs) -> UpdateInfo:
    defaults = dict(
        available=True,
        local_sha="aaa",
        remote_sha="bbb",
        remote_subject="WS Hub 1.0.21",
        detail="update available",
    )
    defaults.update(kwargs)
    return UpdateInfo(**defaults)


class BannerUpdateActionTests(unittest.TestCase):
    def test_linux_tarball_installs_newest_release(self):
        action = banner_update_action(
            _info(is_git=False, source="release", release_tag="v1.0.21"),
            windows=False,
        )
        self.assertEqual(action.kind, "install")
        self.assertEqual(action.install_tag, "v1.0.21")
        self.assertEqual(action.button_label, "Install\nv1.0.21")
        self.assertIn("Click Install v1.0.21 to replace this copy.", action.how)
        self.assertNotIn("Open Updates", action.how)
        self.assertNotIn("Install this update", action.how)
        self.assertIn("in place", action.tooltip.lower())

    def test_linux_tarball_without_tag_says_install_update(self):
        action = banner_update_action(
            _info(is_git=False, source="release", release_tag=""),
            windows=False,
        )
        self.assertEqual(action.kind, "install")
        self.assertEqual(action.button_label, "Install\nupdate")
        self.assertIn("Click Install update to replace this copy.", action.how)

    def test_git_clone_still_pulls(self):
        action = banner_update_action(
            _info(is_git=True, source="git", dirty=False),
            windows=False,
        )
        self.assertEqual(action.kind, "pull")
        self.assertEqual(action.button_label, "Update\nWS Hub")
        self.assertIn("Click Update WS Hub to pull GitHub main.", action.how)
        self.assertNotIn("WIMS", action.button_label)
        self.assertNotIn("WIMS", action.how)

    def test_git_clone_dirty_mentions_local_edits(self):
        action = banner_update_action(
            _info(is_git=True, source="git", dirty=True),
            windows=True,
        )
        self.assertEqual(action.kind, "pull")
        self.assertEqual(action.button_label, "Update\nWS Hub")
        self.assertIn("local edits present", action.how)

    def test_git_clone_with_release_can_still_pick_in_updates(self):
        action = banner_update_action(
            _info(is_git=True, source="release", release_tag="v1.0.21"),
            windows=False,
        )
        self.assertEqual(action.kind, "pull")
        self.assertIn("Click Update WS Hub to pull", action.how)
        self.assertIn("v1.0.21", action.how)
        self.assertIn("Updates", action.how)

    def test_windows_zip_opens_releases(self):
        action = banner_update_action(
            _info(is_git=False, source="release", release_tag="v1.0.21"),
            windows=True,
        )
        self.assertEqual(action.kind, "download")
        self.assertEqual(action.button_label, "Download\nupdate")
        self.assertIn("Click Download update to open GitHub Releases.", action.how)
        self.assertNotIn("Install", action.button_label)

    def test_tag_without_v_prefix_still_shows_v(self):
        action = banner_update_action(
            _info(is_git=False, source="release", release_tag="1.0.21"),
            windows=False,
        )
        self.assertEqual(action.button_label, "Install\nv1.0.21")
        self.assertIn("Install v1.0.21", action.how)
        self.assertEqual(action.install_tag, "1.0.21")

    def test_launcher_source_has_no_old_button_label(self):
        app = (ROOT / "src" / "wims" / "launcher" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("Update\\nWIMS", app)
        self.assertNotIn("Click Update WIMS", app)
        self.assertNotIn("Open Updates and click Install this update", app)
        self.assertIn("banner_update_action", app)
        self.assertIn("_start_release_install", app)


if __name__ == "__main__":
    unittest.main()
