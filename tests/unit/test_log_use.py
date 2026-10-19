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

"""Log to use: saved choice, goal suggestion, and the count-since window."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.contest_rules import load_builtin  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.rules.choice import load_logs, save_logs  # noqa: E402
from wims.rules.log_use import (  # noqa: E402
    catalog_from_parts,
    cutoff_bounds,
    qso_in_window,
    resolve_use,
    warnings_for,
)
from wims.state.logstore import LogStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _qso(call, band, grid, *, qid=None, qdate="", time_on="", timestamp="", mode="FT8"):
    return LoggedQso(
        id=qid or f"{call}-{band}-{qdate}-{time_on}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp=timestamp or None,
        operator="", rover_location=None, source="test",
        qso_date=qdate or None, time_on=time_on or None,
    )


def _n1mm(name, path, nr, start, count):
    return {
        "id": f"n1mm|{nr}|{path}",
        "kind": "n1mm",
        "path": path,
        "paths": [path],
        "label": name,
        "title": f"N1MM · {name} · {count} contacts",
        "count": count,
        "file_count": count,
        "contest_nr": nr,
        "contest_name": name,
        "start_date": start,
        "status": "ok",
    }


def _wsjtx(path, count=3):
    return {
        "id": "wsjtx",
        "kind": "wsjtx",
        "path": path,
        "paths": [path],
        "label": "WSJT-X log",
        "title": f"WSJT-X log · {count} contacts",
        "count": count,
        "file_count": count,
        "contest_nr": None,
        "contest_name": "",
        "start_date": "",
        "status": "ok",
    }


def _logs(**kw):
    base = {
        "schema": 2, "primary": "auto", "explicit": False, "selection": None,
        "count_since": "", "count_until": "", "cutoff": "whole",
        "shared_path": "", "overrides": {},
    }
    base.update(kw)
    return base


def test_schema1_auto_is_not_a_saved_choice():
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(json.dumps({
            "schema": 1, "primary": "auto", "shared_path": "", "overrides": {},
        }), encoding="utf-8")
        got = load_logs(path)
        assert got["explicit"] is False
        assert got["count_since"] == "" and got["count_until"] == ""
        assert got["selection"] is None
        path.write_text(json.dumps({
            "schema": 1, "primary": "wsjtx", "shared_path": "/tmp/wsjtx_log.adi",
        }), encoding="utf-8")
        chosen = load_logs(path)
        assert chosen["explicit"] is True
        assert chosen["primary"] == "wsjtx"
    finally:
        path.unlink(missing_ok=True)


def test_log_since_and_until_round_trip_as_separate_fields():
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    try:
        save_logs({
            "explicit": True,
            "primary": "n1mm",
            "selection": {
                "id": "n1mm|2|/tmp/ham.s3db",
                "kind": "n1mm",
                "path": "/tmp/ham.s3db",
                "label": "ARRLVHFSEP",
                "contest_nr": 2,
                "contest_name": "ARRLVHFSEP",
            },
            "count_since": "2026-01-01T05:00:00Z",
            "count_until": "2026-10-01T00:00:00Z",
            "cutoff": "custom",
        }, path)
        got = load_logs(path)
        assert got["schema"] == 2
        assert got["selection"]["contest_nr"] == 2
        assert got["count_since"] == "2026-01-01T05:00:00Z"
        assert got["count_until"] == "2026-10-01T00:00:00Z"
        assert got["selection"]["path"] == "/tmp/ham.s3db"
    finally:
        path.unlink(missing_ok=True)


def test_casual_goal_suggests_wsjtx_not_a_leftover_n1mm_file():
    catalog = [
        _n1mm("DX", "/tmp/dx.s3db", 1, "2026-10-01", 500),
        _n1mm("ARRLVHFJUN", "/tmp/june.s3db", 2, "2026-06-13", 40),
        _wsjtx("/tmp/wsjtx_log.adi", 12),
    ]
    got = resolve_use(
        _logs(), goal="operating", goal_id="checklist", catalog=catalog,
    )
    assert got["explicit"] is False
    assert got["chosen"]["id"] == "wsjtx"
    assert "WSJT-X" in got["why"]
    assert "leftover" not in got["why"]


def test_contest_goal_picks_the_newest_match_not_a_bigger_other_log():
    catalog = [
        _n1mm("DX", "/tmp/dx.s3db", 1, "2026-10-01", 500),
        _n1mm("ARRLVHFJUN", "/tmp/june.s3db", 2, "2026-06-13", 80),
        _n1mm("ARRLVHFSEP", "/tmp/sept.s3db", 3, "2026-09-12", 10),
        _wsjtx("/tmp/wsjtx_log.adi"),
    ]
    got = resolve_use(_logs(), goal="contest", goal_id="arrl-vhf", catalog=catalog)
    assert got["chosen"]["contest_name"] == "ARRLVHFSEP"
    assert "newest matching" in got["why"]
    none = resolve_use(_logs(), goal="contest", goal_id="nyqp", catalog=catalog)
    assert none["chosen"] is None
    assert "not used" in none["why"]


def test_explicit_selection_wins_over_the_goal():
    catalog = [
        _n1mm("ARRLVHFSEP", "/tmp/sept.s3db", 3, "2026-09-12", 10),
        _wsjtx("/tmp/wsjtx_log.adi"),
    ]
    logs = _logs(
        explicit=True,
        primary="wsjtx",
        selection={
            "id": "wsjtx", "kind": "wsjtx", "path": "/tmp/wsjtx_log.adi",
            "label": "WSJT-X log", "contest_nr": None, "contest_name": "",
        },
    )
    got = resolve_use(logs, goal="contest", goal_id="arrl-vhf", catalog=catalog)
    assert got["explicit"] is True
    assert got["chosen"]["kind"] == "wsjtx"
    assert got["why"].startswith("You chose")


def test_presets_set_a_start_and_leave_the_end_open():
    now = datetime(2026, 10, 17, 15, 24, tzinfo=timezone.utc)
    cutoff, since, until = cutoff_bounds("start_now", now=now)
    assert cutoff == "start_now" and until == ""
    assert since == "2026-10-17T15:24:00Z"
    cutoff, since, until = cutoff_bounds("this_year", now=now)
    assert cutoff == "this_year" and until == ""
    assert since.startswith("2026-01-01T")
    cutoff, since, until = cutoff_bounds("whole", now=now)
    assert cutoff == "whole" and since == "" and until == ""


def test_window_changes_dupe_lookup_and_still_honors_per_band():
    store = LogStore(":memory:")
    store.rules = load_builtin("arrl-vhf")
    store.set_window("2026-01-01T00:00:00Z", "")
    store.upsert(_qso(
        "K1ABC", "6m", "FN42", qdate="20250601", time_on="120000",
        timestamp="2025-06-01 12:00:00",
    ))
    # The old contact is stored, and the lookup does not treat it as worked.
    assert store.count() == 1
    assert store.is_dupe("K1ABC", "6m", "FN42") is False
    store.upsert(_qso(
        "K1ABC", "6m", "FN42", qid="new", qdate="20260601", time_on="120000",
        timestamp="2026-06-01 12:00:00",
    ))
    assert store.is_dupe("K1ABC", "6m", "FN42") is True
    assert store.is_dupe("K1ABC", "2m", "FN42") is False
    store.set_window("2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z")
    assert store.is_dupe("K1ABC", "6m", "FN42") is False
    assert qso_in_window(
        _qso("K1ABC", "6m", "FN42", qdate="20260201", time_on="000000"),
        "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z",
    ) is True


def test_warnings_for_missing_empty_stale_and_unreadable():
    today = datetime(2026, 10, 17, tzinfo=timezone.utc).date()
    chosen = _wsjtx("/tmp/missing.adi", 0)
    missing, _notes = warnings_for(
        chosen=chosen, qsos=[], problem="missing", mtime=None,
        since="", until="", today=today, goal="operating", why="",
    )
    assert any("missing" in w["message"] for w in missing)
    empty, _notes = warnings_for(
        chosen=chosen, qsos=[], problem=None, mtime=None,
        since="", until="", today=today, goal="operating", why="",
    )
    assert any("no contacts" in w["message"].lower() for w in empty)
    stale_q = _qso("K1ABC", "6m", "FN42", qdate="20200601", time_on="120000")
    stale, _notes = warnings_for(
        chosen=chosen, qsos=[stale_q], problem=None, mtime=None,
        since="", until="", today=today, goal="operating", why="",
    )
    assert any("before today's operating session" in w["message"] for w in stale)
    bad, _notes = warnings_for(
        chosen=chosen, qsos=[], problem="unreadable", mtime=None,
        since="", until="", today=today, goal="operating", why="",
    )
    assert any("cannot read" in w["message"] for w in bad)
    _warns, notes = warnings_for(
        chosen=chosen, qsos=[stale_q], problem=None, mtime=None,
        since="", until="", today=today, goal="contest", why="",
    )
    assert any("contest name" in n["message"] for n in notes)
    fresh, _notes = warnings_for(
        chosen=chosen, qsos=[], problem=None, mtime=None,
        since="2026-10-17T15:00:00Z", until="", today=today, goal="operating", why="",
    )
    assert any("since" in w["message"] for w in fresh)


def test_catalog_lists_n1mm_wsjtx_and_gridtracker():
    rows = catalog_from_parts(
        contests=[{
            "db_path": "/tmp/ham.s3db", "db_label": "ham.s3db",
            "contest_nr": 4, "contest_name": "NYQP", "start_date": "2026-09-19",
            "qso_count": 15, "label": "NYQP · 2026-09-19 · 15 QSOs",
        }],
        access=[{
            "instance": "6m", "path": "/tmp/WSJT-X - 6m/wsjtx_log.adi",
            "status": "ok", "count": 2, "message": "ok",
        }],
        seed_paths=["/tmp/WSJT-X - 6m/wsjtx_log.adi"],
        gridtracker=[{"path": "/tmp/gt/log.adi", "count": 4, "problem": ""}],
    )
    kinds = {row["kind"] for row in rows}
    assert {"n1mm", "wsjtx", "adif", "gridtracker"} <= kinds


def _adi(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    lines = ["WSJT-X", "<eoh>"]
    for call, qdate, tim, band in rows:
        lines.append(
            f"<call:{len(call)}>{call} <qso_date:8>{qdate} <time_on:6>{tim} "
            f"<band:{len(band)}>{band} <mode:3>FT8 <eor>"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_log_page_has_the_log_controls_and_setup_does_not():
    static = ROOT / "src" / "wims" / "server" / "static"
    page = (static / "log.html").read_text(encoding="utf-8")
    setup = (static / "setup.html").read_text(encoding="utf-8")
    n1mm = (static / "status.html").read_text(encoding="utf-8")
    assert 'id="log-in-use"' in page
    assert "Log to use" in page
    assert 'id="log-cutoff"' in page
    assert "Start now" in page and "This year" in page and "Whole log" in page
    assert 'id="log-refresh"' in page
    assert 'id="contest-resync"' in page
    assert "python -m" not in page
    assert 'href="/log"' in setup
    assert 'id="log-pick"' not in setup
    assert 'id="logs-check"' not in setup
    assert 'id="shared-log"' not in setup
    assert "contest-rescan" not in n1mm
    assert 'id="n1mm-single"' in n1mm
    assert 'class="nav-n1mm" hidden' in setup
    js = (static / "wims.js").read_text(encoding="utf-8")
    assert "select_log" in js and "select_cutoff" in js
    assert "refresh_logs" in js
    assert "LOG_TIPS" in js
    assert "renderN1mmNav" in js
    assert "nav-n1mm" in js
    assert 'here = p === "/n1mm"' in js


def test_changing_the_log_reloads_and_the_window_changes_dupes():
    from wims.server.app import LiveFleet
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    default = home / "WSJT-X"
    six = home / "WSJT-X - 6m"
    default.mkdir(parents=True)
    six.mkdir()
    year = datetime.now().year
    old = f"{year - 2}0601"
    new = f"{year}0601"
    _adi(default / "wsjtx_log.adi", [("K1OLD", new, "120000", "6m")])
    _adi(six / "wsjtx_log.adi", [
        ("K1ABC", old, "120000", "6m"),
        ("N1NEW", new, "130000", "6m"),
    ])
    logs_path = tmp / "logs.json"
    rules_path = tmp / "rules.json"
    rules_path.write_text(json.dumps({
        "schema": 4, "goal": "contest", "goal_id": "arrl-vhf",
        "contest": "arrl-vhf", "explicit": True,
    }), encoding="utf-8")
    prev_logs = os.environ.get("WIMS_LOGS")
    prev_rules = os.environ.get("WIMS_CONTEST_RULES")
    prev_data = os.environ.get("XDG_DATA_HOME")
    os.environ["WIMS_LOGS"] = str(logs_path)
    os.environ["WIMS_CONTEST_RULES"] = str(rules_path)
    os.environ["XDG_DATA_HOME"] = str(home)
    try:
        save_logs({
            "explicit": True,
            "primary": "adif",
            "selection": {
                "id": f"adif|{six / 'wsjtx_log.adi'}",
                "kind": "adif",
                "path": str(six / "wsjtx_log.adi"),
                "label": "WSJT-X — 6m",
                "contest_nr": None,
                "contest_name": "",
            },
        }, logs_path)
        live = LiveFleet()
        view = live.apply_log_use()
        assert view["line"].startswith("Log in use:")
        assert "6m" in view["line"]
        assert live._log.is_dupe("K1OLD", "6m") is False
        assert live._log.is_dupe("N1NEW", "6m") is True
        # Just operating does not pick a different log. The 6m file stays.
        live.set_rules({"action": "select", "goal": "operating", "goal_id": "checklist"})
        disk = load_logs(logs_path)
        assert disk["explicit"] is True
        assert disk["selection"]["path"] == str(six / "wsjtx_log.adi")
        assert live._log.rules.id == "checklist"
        assert live._log.is_dupe("N1NEW", "6m") is True
        live.attach_rules()
        # Back to the contest rule so per-band is the check, on the same log.
        live.set_rules({"action": "select", "goal": "contest", "goal_id": "arrl-vhf"})
        res = live.set_rules({"action": "select_cutoff", "cutoff": "this_year"})
        assert res["ok"] is True
        saved = load_logs(logs_path)
        assert saved["cutoff"] == "this_year"
        assert saved["count_since"] and saved["count_until"] == ""
        assert live._log.is_dupe("K1ABC", "6m") is False
        assert live._log.is_dupe("N1NEW", "6m") is True
        assert live._log.is_dupe("N1NEW", "2m") is False
        assert any("contest name" in n["message"] for n in live._log_in_use["notes"])
        # End time is its own field. It drops the this-year contact from the lookup.
        saved["cutoff"] = "custom"
        saved["count_since"] = f"{year - 3}-01-01T00:00:00Z"
        saved["count_until"] = f"{year}-01-01T00:00:00Z"
        save_logs(saved, logs_path)
        live.apply_log_use()
        assert live._log.is_dupe("K1ABC", "6m") is True
        assert live._log.is_dupe("N1NEW", "6m") is False
        switched = live.set_rules({
            "action": "select_log",
            "id": f"adif|{default / 'wsjtx_log.adi'}",
        })
        assert switched["ok"] is True
        # The end time is separate from the log, so it still hides this year's contact.
        assert live._log.is_dupe("K1OLD", "6m") is False
        assert live._log.is_dupe("N1NEW", "6m") is False
        again = load_logs(logs_path)
        assert again["selection"]["path"] == str(default / "wsjtx_log.adi")
        assert again["explicit"] is True
        assert again["count_until"].startswith(f"{year}-01-01")
        opened = live.set_rules({"action": "select_cutoff", "cutoff": "whole"})
        assert opened["ok"] is True
        assert live._log.is_dupe("K1OLD", "6m") is True
        assert load_logs(logs_path)["count_since"] == ""
    finally:
        if prev_logs is None:
            os.environ.pop("WIMS_LOGS", None)
        else:
            os.environ["WIMS_LOGS"] = prev_logs
        if prev_rules is None:
            os.environ.pop("WIMS_CONTEST_RULES", None)
        else:
            os.environ["WIMS_CONTEST_RULES"] = prev_rules
        if prev_data is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev_data


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
