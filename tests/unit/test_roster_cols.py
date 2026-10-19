# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Operate roster Message column — source contract for wims.js.

The console has no Node test runner. These checks read the script the browser
loads, the same way other UI tests in this tree do, and (when node is on
PATH) execute the saved-column merge.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"

INSERT = """function rosInsertNewCols(keys) {
  // Saved sets from before Message existed omit msg. Put it right after Calling.
  if (!keys || keys.indexOf("msg") >= 0) return keys;
  const at = keys.indexOf("to_call");
  if (at >= 0) return keys.slice(0, at + 1).concat(["msg"], keys.slice(at + 1));
  return ["msg"].concat(keys);
}"""


def _js() -> str:
    return JS.read_text(encoding="utf-8")


def test_message_column_is_text_and_default_after_calling():
    js = _js()
    body = re.search(r"\{key:\"msg\"[\s\S]*?cell:rosMessage\}", js)
    assert body, "ROS_COLS is missing the Message column"
    col = body.group(0)
    assert 'label:"Message"' in col
    assert "num:" not in col and "num :" not in col
    defaults = re.search(r"const ROS_COLS_DEFAULT = \[([^\]]+)\]", js)
    assert defaults
    keys = re.findall(r'"([a-z0-9_]+)"', defaults.group(1))
    assert keys[keys.index("to_call") + 1] == "msg"
    assert keys[0] == "call"


def test_message_cell_tooltip_is_full_decode_and_stays_short():
    js = _js()
    start = js.find("function rosMessage")
    assert start >= 0
    fn = js[start:js.find("function rosSourceLabel")]
    assert "ROS_MSG_SHOW" in fn
    assert "c.message" in fn
    assert "escAttr(tip)" in fn
    assert "ros-msg" in fn
    assert "…" in fn


def test_saved_column_set_gains_message_once():
    js = _js()
    assert INSERT in js
    assert 'const ROS_COLS_VERSION = 3' in js
    assert 'const ROS_COLS_VERSION_KEY = "wims.ops.cols.v"' in js
    assert "rosMigrateColPref" in js
    assert "wims.ops.cols" in js
    node = shutil.which("node")
    if not node:
        return
    script = INSERT + """
const a = rosInsertNewCols(["call","to_call","band","grid","snr"]);
if (a.join(",") !== "call,to_call,msg,band,grid,snr") process.exit(2);
const b = rosInsertNewCols(["call","band"]);
if (b.join(",") !== "msg,call,band") process.exit(3);
const c = rosInsertNewCols(["call","to_call","msg","band"]);
if (c.join(",") !== "call,to_call,msg,band") process.exit(4);
if (rosInsertNewCols(null) !== null) process.exit(5);
"""
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout


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
