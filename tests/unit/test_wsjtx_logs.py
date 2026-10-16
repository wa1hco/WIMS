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

"""Per-instance wsjtx_log.adi discovery and the plain warning sentences."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.wsjtx_logs import (  # noqa: E402
    app_name,
    assess,
    discover_access,
    seed_files,
)


ADI = "<eoh><call:5>K1ABC <mode:3>FT8 <band:2>6m <qso_date:8>20260912 <time_on:6>140200 <eor>\n"


def test_rig_name_directory():
    assert app_name("") == "WSJT-X"
    assert app_name("WSJT-X") == "WSJT-X"
    assert app_name("(active/default)") == "WSJT-X"
    assert app_name("6m") == "WSJT-X - 6m"


def test_missing_dir_missing_file_and_ok():
    root = Path(tempfile.mkdtemp())
    missing = assess("6m", root / "WSJT-X - 6m" / "wsjtx_log.adi")
    assert missing.status == "missing_dir"
    assert "cannot find its WSJT-X folder" in missing.message

    folder = root / "WSJT-X - 2m"
    folder.mkdir()
    empty = assess("2m", folder / "wsjtx_log.adi")
    assert empty.status == "missing_file"
    assert "no wsjtx_log.adi yet" in empty.message

    path = folder / "wsjtx_log.adi"
    path.write_text(ADI, encoding="utf-8")
    ok = assess("2m", path)
    assert ok.status == "ok" and ok.count == 1
    assert "1 contacts" in ok.message


def test_discover_lists_each_instance_and_shared_file_once():
    root = Path(tempfile.mkdtemp())
    a = root / "WSJT-X - 6m"
    b = root / "WSJT-X - 2m"
    a.mkdir()
    b.mkdir()
    (a / "wsjtx_log.adi").write_text(ADI, encoding="utf-8")
    (b / "wsjtx_log.adi").write_text(ADI, encoding="utf-8")
    rows = discover_access(["6m", "2m"], home=root)
    by_id = {r.instance: r for r in rows}
    assert by_id["6m"].status == "ok"
    assert by_id["2m"].status == "ok"
    files = seed_files(["6m", "2m"], home=root)
    assert len(files) == 2

    shared = root / "shared.adi"
    shared.write_text(ADI, encoding="utf-8")
    one = seed_files(["6m", "2m"], home=root, logs={"shared_path": str(shared), "overrides": {}})
    assert one == [shared]
    heard = discover_access(["ghost"], home=root)
    ghost = [r for r in heard if r.instance == "ghost"][0]
    assert ghost.status == "missing_dir"


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
