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

"""Operate show menu: Needed, Needed and CQ, Needed and CQ or 73, All.

Sample decodes go through the Message-column parser. The console applies the
same rule to the fields that parser already produced.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.roster_filter import (  # noqa: E402
    normalize_need_filter,
    row_visible,
    visible_decode,
)
from wims.udp import messages as m  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"
OPS = ROOT / "src" / "wims" / "server" / "static" / "ops.html"

MODES = ("needed", "needed-cq", "needed-73", "all")

# message, is_needed, visible under Needed / Needed and CQ / Needed and CQ or 73 / All
ROWS = [
    ("CQ K1ABC FN42", True, (True, True, True, True)),
    ("CQ DX W1AW FN31", True, (True, True, True, True)),
    ("CQ NA N1MM FN42", True, (True, True, True, True)),
    ("W2XYZ K1ABC RR73", True, (True, False, True, True)),
    ("N1NEW K1ABC 73", True, (True, False, True, True)),
    ("W2XYZ K1ABC RR73 FN42", True, (True, False, True, True)),
    ("K2ABC K1ABC R-12", True, (True, False, False, True)),
    ("CQ W9OLD FN20", False, (False, False, False, True)),
    # RRR is an ack, not a station that is free to call.
    ("W1AW K1ABC RRR", True, (True, False, False, True)),
]


def _check(mode: str) -> None:
    idx = MODES.index(mode)
    for msg, needed, flags in ROWS:
        got = visible_decode(msg, is_needed=needed, mode=mode)
        assert got is flags[idx], (mode, msg, got, flags[idx])


def test_needed_shows_only_needed_stations():
    _check("needed")


def test_needed_and_cq_keeps_cq_and_directed_cq():
    _check("needed-cq")


def test_needed_and_cq_or_73_keeps_signoffs_including_rr73_with_grid():
    _check("needed-73")
    # The grid extractor does not call this a sign-off; the Message tail does.
    assert m.decode_is_signoff("W2XYZ K1ABC RR73 FN42") is False
    assert visible_decode(
        "W2XYZ K1ABC RR73 FN42", is_needed=True, mode="needed-73",
    ) is True


def test_all_shows_every_sample_including_a_non_needed_cq():
    _check("all")


def test_sample_decodes_use_the_message_column_parser():
    is_cq, dx, to, grid, tail = m._interpret_decode("CQ DX W1AW FN31")
    assert is_cq is True and dx == "W1AW" and to == "CQ"
    assert grid == "FN31" and tail == "FN31"
    is_cq, dx, _to, grid, tail = m._interpret_decode("CQ K1ABC FN42")
    assert is_cq is True and dx == "K1ABC" and tail == "FN42"
    is_cq, dx, _to, grid, tail = m._interpret_decode("W2XYZ K1ABC RR73")
    assert is_cq is False and dx == "K1ABC" and tail == "RR73" and grid is None
    is_cq, dx, to, grid, tail = m._interpret_decode("N1NEW K1ABC 73")
    assert is_cq is False and dx == "K1ABC" and to == "N1NEW"
    assert tail == "73" and grid is None
    is_cq, dx, _to, grid, tail = m._interpret_decode("W2XYZ K1ABC RR73 FN42")
    assert is_cq is False and dx == "K1ABC" and tail == "RR73 FN42" and grid == "FN42"
    is_cq, dx, _to, grid, tail = m._interpret_decode("K2ABC K1ABC R-12")
    assert is_cq is False and dx == "K1ABC" and tail == "R-12"
    is_cq, dx, _to, _grid, _tail = m._interpret_decode("CQ W9OLD FN20")
    assert is_cq is True and dx == "W9OLD"
    for msg, _needed, _flags in ROWS:
        _is_cq, dx, _to, _grid, _tail = m._interpret_decode(msg)
        assert dx, msg


def test_saved_checkbox_checked_is_needed_and_unchecked_is_all():
    assert normalize_need_filter(None) == "needed"
    assert normalize_need_filter(True) == "needed"
    assert normalize_need_filter("true") == "needed"
    assert normalize_need_filter("1") == "needed"
    assert normalize_need_filter("yes") == "needed"
    assert normalize_need_filter("checked") == "needed"
    assert normalize_need_filter(False) == "all"
    assert normalize_need_filter("false") == "all"
    assert normalize_need_filter("0") == "all"
    assert normalize_need_filter("no") == "all"
    assert normalize_need_filter("unchecked") == "all"
    assert normalize_need_filter("needed") == "needed"
    assert normalize_need_filter("needed-cq") == "needed-cq"
    assert normalize_need_filter("needed-73") == "needed-73"
    assert normalize_need_filter("all") == "all"
    assert normalize_need_filter("  All  ") == "all"
    assert normalize_need_filter("") == "needed"


def test_operate_page_menu_labels_and_saved_choice():
    html = OPS.read_text(encoding="utf-8")
    assert 'type="checkbox"' not in html
    assert "needed only" not in html
    opts = re.findall(
        r'role="option" data-value="([^"]+)" title="([^"]+)"[^>]*>([^<]+)</button>',
        html,
    )
    assert [o[0] for o in opts] == list(MODES)
    assert [o[2] for o in opts] == [
        "Needed",
        "Needed and CQ",
        "Needed and CQ or 73",
        "All",
    ]
    assert all(len(o[1].split()) <= 16 for o in opts)
    js = JS.read_text(encoding="utf-8")
    assert 'const ROS_NEED_KEY = "wims.ops.needed"' in js
    assert "localStorage.getItem(ROS_NEED_KEY)" in js
    assert "localStorage.setItem(ROS_NEED_KEY" in js
    start = js.find("function rosNormalizeNeed")
    end = js.find("function rosSaveNeed")
    body = js[start:end]
    assert start >= 0 and end > start
    assert "c.is_cq" in body
    assert "rosExchangeTail" in body
    assert "RegExp" not in body and ".match(" not in body
    sign = js[js.find("function rosTailIsFreeSignoff"):js.find("function rosKeepCandidate")]
    assert '"73"' in sign and '"RR73"' in sign
    assert "RRR" not in sign
    msg = js[js.find("function rosMessage"):js.find("function rosSourceLabel")]
    assert "rosExchangeTail(c)" in msg
    assert 'needed.checked' not in js
    assert "ros-needed\").checked" not in js


def test_console_filter_matches_the_message_parser():
    node = shutil.which("node")
    if not node:
        return
    js = JS.read_text(encoding="utf-8")
    start = js.find("function rosNormalizeNeed")
    end = js.find("function rosSaveNeed")
    funcs = js[start:end]
    runner = funcs + r"""
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const norms = input.norms.map((v) => rosNormalizeNeed(v));
const rows = input.rows.map((r) => !!rosKeepCandidate(r.row, r.mode));
process.stdout.write(JSON.stringify({norms: norms, rows: rows}));
"""
    norms = [
        None, True, False, "", "true", "false", "1", "0", "yes", "no",
        "checked", "unchecked", "needed", "needed-cq", "needed-73", "all",
        "NEEDED", "  All  ",
    ]
    rows = []
    expect_rows = []
    for msg, needed, _flags in ROWS:
        is_cq, _dx, _to, _grid, tail = m._interpret_decode(msg)
        for mode in MODES:
            rows.append({
                "row": {
                    "is_needed": needed,
                    "is_cq": is_cq,
                    "msg": tail or "",
                    "message_tail": tail or "",
                },
                "mode": mode,
            })
            expect_rows.append(row_visible(
                is_needed=needed, is_cq=is_cq, message_tail=tail, mode=mode,
            ))
    # Message column reads message_tail when msg is blank.
    rows.append({
        "row": {"is_needed": True, "is_cq": False, "msg": "", "message_tail": "73"},
        "mode": "needed-73",
    })
    expect_rows.append(True)
    rows.append({
        "row": {"is_needed": True, "is_cq": False, "msg": "", "message_tail": "RR73 FN42"},
        "mode": "needed-cq",
    })
    expect_rows.append(False)
    payload = {"norms": norms, "rows": rows}
    js_path = ""
    data_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(runner)
            js_path = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(payload, f)
            data_path = f.name
        proc = subprocess.run(
            [node, js_path, data_path], capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        got = json.loads(proc.stdout)
        expect_norms = [normalize_need_filter(v) for v in norms]
        assert got["norms"] == expect_norms, (got["norms"], expect_norms)
        assert got["rows"] == expect_rows
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
