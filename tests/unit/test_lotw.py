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

"""GridTracker LoTW file: discovery, matching, and the DO62 confirmation."""

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.goal_rules import AwardRules, ChecklistRules  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.lotw import (  # noqa: E402
    TIME_WINDOW_S,
    candidate_paths,
    current,
    format_updated,
    mode_group,
    use_paths,
)
from wims.state.logstore import LogStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WHEN = datetime(2018, 11, 22, 15, 32, 0, tzinfo=timezone.utc)
EPOCH = WHEN.timestamp()


def _adif(records) -> str:
    parts = ["LoTW confirmations\n<eoh>\n"]
    for rec in records:
        for key, val in rec.items():
            text = str(val)
            parts.append(f"<{key}:{len(text)}>{text}")
        parts.append("<eor>\n")
    return "".join(parts)


def _va5dak(**extra) -> dict:
    rec = {
        "call": "VA5DAK",
        "band": "15M",
        "mode": "FT8",
        "qso_date": "20181122",
        "time_on": "153200",
        "gridsquare": "DO62",
        "state": "SK",
        "dxcc": "1",
    }
    rec.update(extra)
    return rec


def _qso(call="VA5DAK", band="15m", grid="DO62", mode="FT8", *,
         state=None, time_on="153400", qso_date="20181122"):
    return LoggedQso(
        id=f"{call}-{band}-{mode}-{grid or ''}-{time_on}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="", timestamp="2018-11-22 15:34:00",
        operator="", rover_location=None, source="test",
        state=state, confirmed=False,
        qso_date=qso_date, time_on=time_on,
    )


def _store(items, rows, **rules_kw):
    store = LogStore(":memory:")
    store.rules = ChecklistRules(
        items, title="Checklist", log_label="the log", **rules_kw,
    )
    for row in rows:
        store.upsert(row)
    return store


def _write(folder: Path, name: str, text: str, mtime: int | None = None) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_format_updated_is_plain_local_time():
    assert format_updated(datetime(2026, 10, 21, 1, 54)) == "Oct 21, 2026, 1:54 AM"
    assert format_updated(datetime(2018, 11, 22, 0, 5)) == "Nov 22, 2018, 12:05 AM"
    assert format_updated(datetime(2018, 11, 22, 12, 0)) == "Nov 22, 2018, 12:00 PM"
    assert format_updated(datetime(2018, 11, 22, 15, 32)) == "Nov 22, 2018, 3:32 PM"


def test_candidate_paths_cover_gridtracker_2_and_1():
    home = Path("/home/op")
    linux = candidate_paths(home, platform="linux", environ={})
    assert home / ".config" / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif" in linux
    assert home / ".local" / "share" / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif" in linux
    assert home / "Documents" / "GridTracker" / "LogbookOfTheWorld.adif" in linux
    xdg = candidate_paths(home, platform="linux", environ={"XDG_CONFIG_HOME": "/xdg"})
    assert Path("/xdg/GridTracker2/Ginternal/LoTW_QSL.adif") in xdg
    mac = candidate_paths(home, platform="darwin", environ={})
    assert (
        home / "Library" / "Application Support" / "GridTracker2"
        / "Ginternal" / "LoTW_QSL.adif"
    ) in mac
    win = candidate_paths(
        Path("/Users/op"), platform="win32", environ={"APPDATA": "/roaming"},
    )
    assert Path("/roaming/GridTracker2/Ginternal/LoTW_QSL.adif") in win
    assert Path("/Users/op/Documents/GridTracker/LogbookOfTheWorld.adif") in win
    assert Path("/Users/op/OneDrive/Documents/GridTracker/LogbookOfTheWorld.adif") in win
    fallback = candidate_paths(Path("/Users/op"), platform="win32", environ={})
    assert (
        Path("/Users/op/AppData/Roaming/GridTracker2/Ginternal/LoTW_QSL.adif")
        in fallback
    )


def test_missing_file_says_not_found():
    with tempfile.TemporaryDirectory() as folder:
        use_paths([Path(folder) / "LoTW_QSL.adif"])
        idx = current()
        assert idx.line == "LoTW confirmations: not found"
        assert idx.found is False
        assert idx.count == 0
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH) is False


def test_malformed_file_confirms_nothing():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(Path(folder), "LoTW_QSL.adif", "")
        path.write_bytes(b"\x00\xff this is not a logbook\nno tags here\n")
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        use_paths([path])
        idx = current()
        assert idx.found is True
        assert idx.line == (
            "LoTW confirmations: from GridTracker, but the file could not be read"
        )
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH) is False
        assert idx.confirms_row({
            "call": "VA5DAK", "band": "15m", "mode": "FT8",
            "qso_date": "20181122", "time_on": "153200",
        }) is False
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime


def test_mode_group_ft8_matches_data_and_mfsk():
    assert mode_group("FT8") == mode_group("DATA") == mode_group("MFSK") == "DATA"
    assert mode_group("CW") == "CW"
    assert TIME_WINDOW_S == 30 * 60
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for mode in ("DATA", "MFSK"):
            path = _write(root, "LoTW_QSL.adif", _adif([_va5dak(mode=mode)]))
            use_paths([path])
            idx = current()
            assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH), mode
            assert idx.confirms("VA5DAK", "15m", mode, EPOCH), mode
        cw = _write(root, "LoTW_QSL.adif", _adif([_va5dak(mode="CW")]))
        os.utime(cw, (cw.stat().st_mtime + 5, cw.stat().st_mtime + 5))
        idx = current()
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH) is False
        assert idx.confirms("VA5DAK", "15m", "CW", EPOCH) is True


def test_time_window_is_thirty_minutes():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(Path(folder), "LoTW_QSL.adif", _adif([_va5dak()]))
        use_paths([path])
        idx = current()
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH + TIME_WINDOW_S) is True
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH - TIME_WINDOW_S) is True
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH + TIME_WINDOW_S + 1) is False
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH - TIME_WINDOW_S - 1) is False
        assert idx.confirms("VA5DAK", "10m", "FT8", EPOCH) is False
        assert idx.confirms("K1ABC", "15m", "FT8", EPOCH) is False


def test_va5dak_do62_becomes_confirmed():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(Path(folder), "LoTW_QSL.adif", _adif([_va5dak()]))
        raw = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        rows = [_qso()]
        use_paths([])
        store = _store({"grid": {"enabled": True, "scope": "overall"}}, rows)
        before = store.classify("VE1NEW", "15m", "DO62", "FT8")
        assert before.chase == "unconfirmed"
        assert "DO62" in before.need_reason
        use_paths([path])
        after = store.classify("VE1NEW", "15m", "DO62", "FT8")
        assert after.chase == ""
        assert after.is_dupe is True
        assert "unconfirmed" not in after.need_reason.lower()
        assert "DO62" in after.need_reason
        other = store.classify("VE1NEW", "15m", "FN11", "FT8")
        assert other.chase == "needed"
        flag = store.con.execute("SELECT confirmed FROM qsos").fetchone()[0]
        assert not flag
        assert path.read_bytes() == raw
        assert path.stat().st_mtime_ns == mtime
        banded = _store({"grid": {"enabled": True, "scope": "band"}}, rows)
        on_band = banded.classify("VE1NEW", "15m", "DO62", "FT8")
        off_band = banded.classify("VE1NEW", "10m", "DO62", "FT8")
        assert on_band.chase == "" and "unconfirmed" not in on_band.need_reason.lower()
        assert off_band.chase == "needed"
        store.rules = AwardRules("vucc", log_label="the log")
        award = store.classify("VE1NEW", "6m", "DO62", "FT8")
        assert award.chase == "" and award.is_dupe is True


def test_lotw_fields_confirm_grid_state_and_dxcc():
    """The record's own grid, state, and DXCC count even when the QSO time does not."""
    with tempfile.TemporaryDirectory() as folder:
        # Hours away, so the logged contact itself is not the match.
        path = _write(
            Path(folder), "LoTW_QSL.adif",
            _adif([_va5dak(time_on="010000")]),
        )
        use_paths([path])
        assert current().confirms_row({
            "call": "VA5DAK", "band": "15m", "mode": "FT8",
            "qso_date": "20181122", "time_on": "153200",
        }) is False
        rows = [_qso(grid=None, time_on="153200")]
        grid = _store({"grid": {"enabled": True, "scope": "overall"}}, rows)
        hit = grid.classify("VE1NEW", "20m", "DO62", "FT8")
        assert hit.chase == "" and "unconfirmed" not in hit.need_reason.lower()
        state = _store({"state": {"enabled": True, "scope": "overall"}}, rows)
        sk = state.classify("VE9ZZ", "20m", "FN20", "FT8", state="SK")
        ma = state.classify("W1ZZ", "20m", "FN42", "FT8", state="MA")
        assert sk.chase == "" and "unconfirmed" not in sk.need_reason.lower()
        assert "Saskatchewan" in sk.need_reason
        assert ma.chase == "needed"
        lookup = lambda call: "Canada" if (call or "").upper()[:2] in {"VA", "VE"} else None
        dxcc = _store(
            {"dxcc": {"enabled": True, "scope": "overall"}}, rows,
            dxcc_lookup=lookup,
        )
        canada = dxcc.classify("VE1NEW", "20m", "FN20", "FT8")
        assert canada.chase == "" and "Canada" in canada.need_reason
        assert "unconfirmed" not in canada.need_reason.lower()


def test_data_mode_confirms_an_ft8_grid_on_that_mode():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(
            Path(folder), "LoTW_QSL.adif",
            _adif([_va5dak(mode="DATA", time_on="010000")]),
        )
        use_paths([path])
        store = _store(
            {"grid": {"enabled": True, "scope": "mode"}},
            [_qso()],
        )
        ft8 = store.classify("VE1NEW", "15m", "DO62", "FT8")
        assert ft8.chase == "" and "unconfirmed" not in ft8.need_reason.lower()
        cw_path = _write(
            Path(folder), "cw.adif",
            _adif([_va5dak(mode="CW", time_on="010000")]),
        )
        os.utime(cw_path, (path.stat().st_mtime + 10, path.stat().st_mtime + 10))
        use_paths([cw_path])
        cw_store = _store(
            {"grid": {"enabled": True, "scope": "mode"}},
            [_qso()],
        )
        still = cw_store.classify("VE1NEW", "15m", "DO62", "FT8")
        assert still.chase == "unconfirmed"


def test_newest_file_wins():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        older = _write(
            root, "LogbookOfTheWorld.adif", _adif([_va5dak()]), mtime=1_000,
        )
        newer = _write(
            root, "LoTW_QSL.adif",
            _adif([{"call": "K1ABC", "band": "6M", "mode": "FT8",
                    "qso_date": "20200101", "time_on": "000000"}]),
            mtime=2_000,
        )
        use_paths([older, newer])
        idx = current()
        assert idx.path == str(newer)
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH) is False
        assert idx.confirms("K1ABC", "6m", "FT8", datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        os.utime(older, (3_000, 3_000))
        idx = current()
        assert idx.path == str(older)
        assert idx.confirms("VA5DAK", "15m", "FT8", EPOCH) is True


def test_reread_when_mtime_changes():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(Path(folder), "LoTW_QSL.adif", _adif([_va5dak()]))
        use_paths([path])
        store = _store({"grid": {"enabled": True, "scope": "overall"}}, [_qso()])
        assert store.classify("VE1NEW", "15m", "DO62", "FT8").chase == ""
        path.write_text("LoTW confirmations\n<eoh>\n", encoding="utf-8")
        later = path.stat().st_mtime + 5
        os.utime(path, (later, later))
        again = store.classify("VE1NEW", "15m", "DO62", "FT8")
        assert again.chase == "unconfirmed"
        shown = current()
        local = datetime.fromtimestamp(path.stat().st_mtime)
        assert shown.line == (
            "LoTW confirmations: from GridTracker, updated " + format_updated(local)
        )
        assert shown.count == 0


def test_read_does_not_change_the_file():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(Path(folder), "LoTW_QSL.adif", _adif([_va5dak()]))
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        use_paths([path])
        current()
        current()
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime


def test_ten_thousand_records_stay_fast():
    with tempfile.TemporaryDirectory() as folder:
        chunks = ["LoTW confirmations\n<eoh>\n"]
        for i in range(10000):
            call = f"K{i:05d}"
            chunks.append(
                f"<call:6>{call}<band:3>15M<mode:3>FT8"
                f"<qso_date:8>20181122<time_on:6>153200<gridsquare:4>DO62<eor>\n"
            )
        path = _write(Path(folder), "LoTW_QSL.adif", "".join(chunks))
        use_paths([path])
        started = time.perf_counter()
        idx = current()
        elapsed = time.perf_counter() - started
        assert idx.count == 10000
        assert elapsed < 5.0, elapsed
        assert idx.confirms("K00042", "15m", "FT8", EPOCH) is True
        assert idx.records[42].grid == "DO62"


def test_setup_names_the_source():
    html = (ROOT / "src" / "wims" / "server" / "static" / "setup.html").read_text(
        encoding="utf-8",
    )
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(
        encoding="utf-8",
    )
    assert 'id="lotw-line"' in html
    assert "LoTW confirmations: not found" in html
    assert "s.lotw" in js
    assert "LoTW confirmations: not found" in js
    for blob in (html, js):
        assert "python -m" not in blob


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
