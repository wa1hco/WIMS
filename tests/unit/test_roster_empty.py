# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operate roster empty-state line: no decodes vs none needed / none match Show."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"
OPS = ROOT / "src" / "wims" / "server" / "static" / "ops.html"


def _js_funcs() -> str:
    js = JS.read_text(encoding="utf-8")
    start = js.find("function rosNormalizeNeed")
    keep_end = js.find("function rosSaveNeed")
    empty_start = js.find("function rosDecodeWord")
    empty_end = js.find("function rosDraw()")
    assert start >= 0 and keep_end > start, "rosNormalizeNeed / rosKeepCandidate missing"
    assert empty_start >= 0 and empty_end > empty_start, "rosEmptyText missing"
    return js[start:keep_end] + "\n" + js[empty_start:empty_end]


def test_ops_page_keeps_the_no_decodes_placeholder():
    html = OPS.read_text(encoding="utf-8")
    assert 'id="ros-empty"' in html
    assert "no decodes yet" in html


def test_empty_helpers_are_in_the_console_script():
    js = JS.read_text(encoding="utf-8")
    assert "function rosEmptyText(" in js
    assert "function rosEmptyTip(" in js
    assert "none needed" in js
    assert "none match Show" in js
    assert "this period" not in js[js.find("function rosEmptyText"):js.find("function rosDraw()")]
    # rosDraw paints the line instead of only toggling display.
    assert "empty.textContent = rosEmptyText(" in js


def test_empty_line_wording():
    node = shutil.which("node")
    if not node:
        return
    cases = [
        {
            "r": {"candidates": []},
            "needMode": "needed",
            "selected": None,
            "maxAge": 120,
            "text": "no decodes yet…",
        },
        {
            "r": {"candidates": [
                {"is_needed": False, "is_cq": True, "band": "2m", "age": 8},
                {"is_needed": False, "is_cq": False, "band": "2m", "age": 12},
            ]},
            "needMode": "needed",
            "selected": None,
            "maxAge": 120,
            "text": "2 decodes, none needed",
        },
        {
            "r": {"candidates": [
                {"is_needed": False, "is_cq": True, "band": "2m", "age": 8},
            ]},
            "needMode": "needed",
            "selected": None,
            "maxAge": 120,
            "text": "1 decode, none needed",
        },
        {
            "r": {"candidates": [
                {"is_needed": True, "is_cq": False, "msg": "R-12",
                 "message_tail": "R-12", "band": "2m", "age": 5},
            ]},
            "needMode": "needed-cq",
            "selected": None,
            "maxAge": 120,
            "text": "1 decode, none match Show",
        },
        {
            "r": {"candidates": [
                {"is_needed": True, "is_cq": True, "band": "2m", "age": 200},
                {"is_needed": False, "is_cq": False, "band": "2m", "age": 180},
            ]},
            "needMode": "needed",
            "selected": None,
            "maxAge": 120,
            "text": "2 decodes, none match Show",
        },
    ]
    runner = _js_funcs() + r"""
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = input.map((c) => {
  const selected = c.selected == null ? null : new Set(c.selected);
  return rosEmptyText(c.r, c.needMode, selected, c.maxAge);
});
process.stdout.write(JSON.stringify(out));
"""
    js_path = ""
    data_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(runner)
            js_path = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(cases, f)
            data_path = f.name
        proc = subprocess.run(
            [node, js_path, data_path], capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        got = json.loads(proc.stdout)
        expect = [c["text"] for c in cases]
        assert got == expect, (got, expect)
    finally:
        for p in (js_path, data_path):
            if p:
                Path(p).unlink(missing_ok=True)


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
