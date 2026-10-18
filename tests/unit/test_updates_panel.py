# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hovering an Updates row shows that row, not the selected one."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.update_check import ReleaseEntry  # noqa: E402
from wims.launcher.updates_panel import UpdatesPanel  # noqa: E402


def _entry(tag: str, body: str, *, stamp: str = "") -> ReleaseEntry:
    return ReleaseEntry(
        tag=tag,
        name=tag,
        published="2026-09-13" if stamp else "2026-09-14",
        body=body,
        html_url="",
        prerelease=False,
        relation="current" if stamp else "older",
        stamp=stamp,
    )


class _List:
    def nearest(self, y: int) -> int:
        return 0 if y < 20 else 1

    def bbox(self, index: int):
        return (0, index * 20, 120, 18)


class _Tip:
    def __init__(self) -> None:
        self.text = ""
        self.hidden = 0

    def set_text(self, text: str) -> None:
        self.text = text

    def hide(self) -> None:
        self.hidden += 1


class _Summary:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class HoverTests(unittest.TestCase):
    def _panel(self) -> UpdatesPanel:
        panel = UpdatesPanel.__new__(UpdatesPanel)
        panel._entries = [
            _entry("v1.0.16", "Halt stays live after Work."),
            _entry("v1.0.10", "Published notes for September."),
        ]
        panel._list = _List()
        panel._list_tip = _Tip()
        panel._summary = _Summary()
        panel._hover_index = None
        return panel

    def test_each_row_shows_its_own_notes(self):
        panel = self._panel()
        panel._on_list_motion(SimpleNamespace(y=5))
        self.assertIn("v1.0.16", panel._list_tip.text)
        self.assertIn("Halt stays live", panel._list_tip.text)
        panel._on_list_motion(SimpleNamespace(y=25))
        self.assertIn("v1.0.10", panel._list_tip.text)
        self.assertIn("September", panel._list_tip.text)
        self.assertNotIn("Halt stays live", panel._list_tip.text)

    def test_hover_shows_the_local_time(self):
        panel = self._panel()
        panel._entries[0] = _entry(
            "v1.0.16",
            "Halt stays live after Work.",
            stamp="2026-09-13 11:04 PM",
        )
        panel._on_list_motion(SimpleNamespace(y=5))
        self.assertIn("2026-09-13 11:04 PM", panel._list_tip.text)
        self.assertIn("v1.0.16", panel._list_tip.text)
        self.assertNotIn("2026-09-14", panel._list_tip.text)

    def test_leaving_the_list_hides_the_tip(self):
        panel = self._panel()
        panel._on_list_motion(SimpleNamespace(y=5))
        panel._on_list_motion(SimpleNamespace(y=80))
        self.assertGreater(panel._list_tip.hidden, 0)
        self.assertIsNone(panel._hover_index)
        panel._on_list_motion(SimpleNamespace(y=5))
        panel._on_list_leave()
        self.assertIsNone(panel._hover_index)

    def test_selection_keeps_the_summary_and_not_the_hover_tip(self):
        panel = self._panel()
        panel._on_list_motion(SimpleNamespace(y=25))
        hovered = panel._list_tip.text
        panel._show_entry(panel._entries[0])
        self.assertIn("Halt stays live", panel._summary.text)
        self.assertEqual(panel._list_tip.text, hovered)


if __name__ == "__main__":
    unittest.main()
