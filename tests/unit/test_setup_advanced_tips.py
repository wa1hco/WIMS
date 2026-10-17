# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Setup → Advanced controls each carry a plain-language tooltip and a ? hint."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "wims" / "server" / "static"

# id on the control → key in ADV_TIPS. The six color boxes share one template.
_CONTROLS = {
    "color-by-mode": "highlightByMode",
    "color-fields": "onlyFields",
    "color-save": "saveColors",
    "color-reset": "resetColors",
    "st-state": "stationState",
    "st-county": "stationCounty",
    "st-save": "saveStation",
    "shared-log": "sharedLog",
    "shared-save": "saveShared",
    "custom-scope": "dupeScope",
    "custom-county": "dupeReset",
    "custom-ft8": "banFt8",
    "custom-ft4": "banFt4",
    "custom-rover": "rover",
    "custom-save": "saveCustom",
    "udc-path": "udcPath",
    "udc-import": "udcImport",
    "logs-check": "checkLogs",
}

_COLOR_KEYS = (
    "new_dxcc",
    "new_dxcc_band",
    "new_grid",
    "new_grid_band",
    "new_call",
    "new_call_band",
)

_TOPICS = (
    "WSJT-X Colors ${tipBtn(ADV_TIPS.colors)}",
    "Contest rules ${tipBtn(ADV_TIPS.rules)}",
    "Mode groups ${tipBtn(ADV_TIPS.modeGroups)}",
    "Points ${tipBtn(ADV_TIPS.points)}",
    "Multipliers ${tipBtn(ADV_TIPS.multipliers)}",
)

# Operator tips must stay free of programmer language.
_JARGON = (
    re.compile(r"python\s*-m", re.IGNORECASE),
    re.compile(r"\bpython3?\b", re.IGNORECASE),
    re.compile(r"PYTHONPATH"),
    re.compile(r"WIMS_[A-Z0-9_]+"),
    re.compile(r"(?<![\w])--[A-Za-z]"),
    re.compile(r"\bschema\b", re.IGNORECASE),
    re.compile(r"\bjson\b", re.IGNORECASE),
    re.compile(r"environment variable", re.IGNORECASE),
    re.compile(r"\bcli\b", re.IGNORECASE),
    re.compile(r"dupe_scope|dupe_reset|mode_groups|ban_list|fallback"),
)


def _tips(js: str) -> dict[str, str]:
    start = js.index("const ADV_TIPS = {")
    end = js.index("\n};", start)
    body = js[start:end]
    found = dict(re.findall(r"(\w+)\s*:\s*\"((?:\\.|[^\"\\])*)\"", body))
    return found


def _advanced_fn(js: str) -> str:
    start = js.index("function renderContestAdvanced")
    end = js.index("function renderSeatMarks")
    return js[start:end]


def _control_tags(src: str) -> list[str]:
    """Opening tags of real controls, skipping ${ ... } so a `>` inside JS is not the end."""
    tags = []
    for m in re.finditer(r"<(input|select|button|textarea)\b", src):
        i = m.start()
        j = i
        depth = 0
        while j < len(src):
            if src.startswith("${", j):
                depth += 1
                j += 2
                continue
            if depth and src[j] == "}":
                depth -= 1
                j += 1
                continue
            if depth == 0 and src[j] == ">":
                j += 1
                break
            j += 1
        tags.append(src[i:j])
    return tags


def _sentences(text: str) -> int:
    return len([p for p in re.split(r"[.!?]+", text) if p.strip()])


class AdvancedTooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "wims.js").read_text(encoding="utf-8")
        cls.html = (STATIC / "setup.html").read_text(encoding="utf-8")
        cls.css = (STATIC / "wims.css").read_text(encoding="utf-8")
        cls.tips = _tips(cls.js)
        cls.fn = _advanced_fn(cls.js)

    def test_each_advanced_control_has_a_tooltip_and_a_hint(self):
        tags = _control_tags(self.fn)
        self.assertGreaterEqual(len(tags), len(_CONTROLS) + 1, tags)
        for tag in tags:
            self.assertIn("title=", tag, tag)
            self.assertNotIn('title=""', tag, tag)
            self.assertNotIn("tabindex=\"-1\"", tag, tag)
        for cid, key in _CONTROLS.items():
            idx = self.fn.find(f'id="{cid}"')
            self.assertGreater(idx, 0, cid)
            window = self.fn[max(0, idx - 220):idx + 800]
            self.assertIn(
                f'title="${{escAttr(ADV_TIPS.{key})}}"',
                window,
                cid,
            )
            self.assertIn(f"tipBtn(ADV_TIPS.{key})", window, cid)
            self.assertIn(key, self.tips, cid)

        # The six WSJT-X color boxes are one template. Each named color has a tip.
        color = self.fn[self.fn.find("data-color=") - 180:self.fn.find("data-color=") + 420]
        self.assertIn('title="${t}"', color)
        self.assertIn("tipBtn(tip)", color)
        self.assertIn("ADV_TIPS[k]", self.fn)
        for key in _COLOR_KEYS:
            self.assertIn(key, self.tips, key)

        for snippet in _TOPICS:
            self.assertIn(snippet, self.fn, snippet)

    def test_hint_button_is_keyboard_focusable(self):
        start = self.js.index("function tipBtn")
        end = self.js.index("function wireTipButtons")
        fn = self.js[start:end]
        self.assertIn('type="button"', fn)
        self.assertIn('class="tipbtn"', fn)
        self.assertIn("title=", fn)
        self.assertIn('aria-label="Help.', fn)
        self.assertIn('role="tooltip"', fn)
        self.assertNotIn('tabindex="-1"', fn)
        self.assertIn("wireTipButtons();", self.js)
        # Focus shows the same words, not only a hover title.
        self.assertIn(".tipbtn:focus", self.css)
        self.assertIn(".tipbtn:focus-visible + .tiptxt", self.css)

    def test_advanced_summary_has_the_same_tip(self):
        start = self.html.index('id="contest-advanced"')
        end = self.html.index('id="contest-advanced-body"')
        block = self.html[start:end]
        summary = self.tips["summary"]
        self.assertIn(f'title="{summary}"', block)
        self.assertIn('class="tipbtn"', block)
        self.assertIn('type="button"', block)
        self.assertIn(f'aria-label="Help. {summary}"', block)
        self.assertNotIn('tabindex="-1"', block)

    def test_tips_are_short_plain_language(self):
        self.assertGreaterEqual(len(self.tips), len(_CONTROLS) + len(_COLOR_KEYS) + 5)
        for key, text in self.tips.items():
            self.assertTrue(text.strip(), key)
            self.assertGreaterEqual(_sentences(text), 1, key)
            self.assertLessEqual(_sentences(text), 2, f"{key}: {text}")
            self.assertLessEqual(len(text), 240, key)
            for rx in _JARGON:
                self.assertIsNone(rx.search(text), f"{key}: {rx.pattern} in {text!r}")


if __name__ == "__main__":
    unittest.main()
