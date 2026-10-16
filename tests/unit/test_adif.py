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

"""ADIF reader: length counts, header skip, submode, log-copy rows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.adif import iter_records, load_qsos, read_text, record_id, to_logged_qso  # noqa: E402


SAMPLE = """WSJT-X log file. Ignore this <call:4>NOPE
<eoh>
<call:5>K1ABC <gridsquare:4>FN42 <mode:3>FT8 <submode:3>FT4 <band:2>6m
<qso_date:8>20260912 <time_on:6>140200 <comment:11>see <notag> <eor>
<call:4>W1AW <mode:3>SSB <freq:6>144.174 <qso_date:8>20260912 <time_on:4>1503 <eor>
<mode:3>FT8 <eor>
"""


def test_header_and_length_are_honored():
    rows = read_text(SAMPLE)
    assert len(rows) == 3
    assert rows[0]["call"] == "K1ABC"
    assert rows[0]["comment"] == "see <notag>"
    assert "NOPE" not in rows[0]["call"]
    assert rows[1]["call"] == "W1AW"
    assert rows[2].get("call", "") == ""


def test_submode_wins_and_band_comes_from_freq():
    rows = read_text(SAMPLE)
    assert rows[0]["submode"] == "FT4"
    q = to_logged_qso(rows[0], realpath="/tmp/wsjtx_log.adi")
    assert q is not None
    assert q.mode == "FT4"
    assert q.band == "6m"
    assert q.grid == "FN42"
    q2 = to_logged_qso(rows[1], realpath="/tmp/wsjtx_log.adi")
    assert q2 is not None and q2.band == "2m" and q2.mode == "SSB"
    assert to_logged_qso(rows[2], realpath="/tmp/x") is None


def test_file_and_fields_share_one_id():
    rows = read_text(SAMPLE)
    real = "/logs/wsjtx_log.adi"
    q = to_logged_qso(rows[0], realpath=real)
    assert q is not None
    assert q.id == record_id(rows[0], real)
    assert q.id.startswith("wsjtx|/logs/wsjtx_log.adi|20260912|140200|K1ABC|6m|FT4")


def test_load_path_round_trip(tmp_path=None):
    import tempfile
    folder = Path(tempfile.mkdtemp())
    path = folder / "wsjtx_log.adi"
    path.write_text(SAMPLE, encoding="utf-8")
    qsos, problem = load_qsos(path)
    assert problem is None
    assert [q.call for q in qsos] == ["K1ABC", "W1AW"]
    assert len(list(iter_records(path.read_text(encoding="utf-8")))) == 3


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
