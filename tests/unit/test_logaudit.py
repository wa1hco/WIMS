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

"""Log audit: match, only-in, grid disagreement, duplicate, exit codes."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.logaudit.check import compare, load_adif_source, render_text, to_json  # noqa: E402
from wims.logaudit.cli import main  # noqa: E402


def _adi(rows: list[str]) -> str:
    return "<eoh>\n" + "\n".join(rows) + "\n"


def _row(call, band, mode, hhmmss, grid=""):
    grid_f = f" <gridsquare:{len(grid)}>{grid}" if grid else ""
    return (
        f"<call:{len(call)}>{call}{grid_f} <mode:{len(mode)}>{mode} "
        f"<band:{len(band)}>{band} <qso_date:8>20260912 <time_on:6>{hhmmss} <eor>"
    )


def test_match_only_and_grid_clash():
    root = Path(tempfile.mkdtemp())
    a = root / "wsjtx.adi"
    b = root / "other.adi"
    a.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("W2XYZ", "2m", "FT8", "151000", "FN31"),
        _row("N1ONLY", "6m", "FT8", "160000", "FN20"),
    ]), encoding="utf-8")
    b.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140230", "FN42"),
        _row("W2XYZ", "2m", "FT8", "151100", "FN32"),
        _row("W1AW", "6m", "USB", "164000", "FN31"),
    ]), encoding="utf-8")
    ga, ra = load_adif_source(a, "WSJT-X 6m")
    gb, rb = load_adif_source(b, "N1MM")
    report = compare([(ga, ra), (gb, rb)], lotw_names=set())
    text = render_text(report)
    assert report.exit_code() == 1
    assert len(report.matched) == 1
    assert len(report.disagreements) == 1
    assert any(row["call"] == "N1ONLY" for row in report.only)
    assert any(row["call"] == "W1AW" for row in report.only)
    assert "WIMS log check" in text
    assert "Disagreements" in text
    assert "[OK]" in text
    blob = to_json(report)
    assert blob["matched"] and blob["disagreements"]


def test_duplicate_inside_one_file_and_missing_path():
    root = Path(tempfile.mkdtemp())
    path = root / "one.adi"
    path.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("K1ABC", "6m", "FT8", "140230", "FN42"),
    ]), encoding="utf-8")
    info, rows = load_adif_source(path, "WSJT-X")
    report = compare([(info, rows)], lotw_names=set())
    assert report.duplicates
    assert report.exit_code() == 1
    missing, none_rows = load_adif_source(root / "nope.adi", "ADIF nope.adi")
    bad = compare([(missing, none_rows)], lotw_names=set())
    assert bad.exit_code() == 2
    assert bad.unreadable is True


def test_cli_json_on_two_files():
    root = Path(tempfile.mkdtemp())
    a = root / "a.adi"
    b = root / "b.adi"
    a.write_text(_adi([_row("K1ABC", "6m", "FT8", "140200", "FN42")]), encoding="utf-8")
    b.write_text(_adi([_row("K1ABC", "6m", "FT8", "140200", "FN42")]), encoding="utf-8")
    out = root / "report.json"
    code = main(["--adif", str(a), "--adif", str(b), "--json", str(out)])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["matched"]
    assert data["disagreements"] == []


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
