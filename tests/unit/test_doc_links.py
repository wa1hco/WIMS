# WS Hub (formerly WIMS) — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every relative link in the Markdown docs points at a file (and heading) that exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
_SKIP_DIRS = {".git", "scratch", "node_modules", "dist", "build"}
_FENCE = re.compile(r"(?ms)^```.*?^```")
_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"(?m)^#{1,6}\s+(.*?)\s*#*\s*$")


def _md_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT)
        if rel.parts and rel.parts[0] in _SKIP_DIRS:
            continue
        out.append(p)
    return out


def _slug(heading: str) -> str:
    h = re.sub(r"<[^>]+>", "", heading.strip()).lower()
    h = re.sub(r"[`*_~\[\]()]", "", h)
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def _anchors(path: Path, cache: dict) -> set[str]:
    if path not in cache:
        text = _FENCE.sub("", path.read_text(encoding="utf-8", errors="replace"))
        seen: dict[str, int] = {}
        found = set()
        for m in _HEADING.finditer(text):
            base = _slug(m.group(1))
            n = seen.get(base, 0)
            seen[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
        found.update(re.findall(r'(?:id|name)="([^"]+)"', text))
        cache[path] = found
    return cache[path]


class DocLinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        cache: dict = {}
        broken = []
        for md in _md_files():
            text = md.read_text(encoding="utf-8", errors="replace")
            text = _CODE.sub("", _FENCE.sub("", text))
            for m in _LINK.finditer(text):
                url = m.group(1)
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
                    continue
                path, _, frag = url.partition("#")
                target = (md.parent / unquote(path)).resolve() if path else md.resolve()
                rel = md.relative_to(ROOT).as_posix()
                if path and not target.exists():
                    broken.append(f"{rel}: {url}")
                elif frag and target.suffix == ".md" and frag.lower() not in _anchors(target, cache):
                    broken.append(f"{rel}: {url} (no such heading)")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
