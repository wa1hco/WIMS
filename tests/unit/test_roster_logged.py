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

"""A logged contact clears Mult on the roster for the log that is in use."""

import builtins
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _hear(live, mid, hz, call, grid, now=1.0, ip="10.0.0.1"):
    live.observe_wsjtx(
        M.parse(E.build_status(mid, hz, mode="FT8", decoding=True)),
        now=now, src_ip=ip,
    )
    text = f"CQ {call} {grid}".strip()
    live.observe_wsjtx(
        M.parse(E.build_decode(
            mid, time_ms=0, snr=-3, delta_time=0.1,
            delta_frequency=1500, message=text,
        )),
        now=now + 0.1, src_ip=ip,
    )


def _row(live, call, now=2.0):
    rows = live.snapshot(now)["roster"]["candidates"]
    return next(c for c in rows if c["call"] == call)


def _contact(call, band, grid="", qid="q1", extra=""):
    grid_xml = f"<gridsquare>{grid}</gridsquare>" if grid else ""
    return (
        f"<contactinfo><app>N1MM</app><ID>{qid}</ID><call>{call}</call>"
        f"<band>{band}</band>{grid_xml}{extra}</contactinfo>"
    )


def _adi(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WSJT-X", "<eoh>"]
    for call, qdate, tim, band, grid in rows:
        grid_xml = f" <gridsquare:{len(grid)}>{grid}" if grid else ""
        lines.append(
            f"<call:{len(call)}>{call} <qso_date:8>{qdate} <time_on:6>{tim} "
            f"<band:{len(band)}>{band} <mode:3>FT8{grid_xml} <eor>"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _touch_ahead(path: Path) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))


def _choose_adif(live, path: Path, label: str, kind: str = "adif"):
    live._install_chosen({
        "kind": kind,
        "label": label,
        "path": str(path),
        "paths": [str(path)],
    }, [], None)
    live._log_choice_active = True
    live._log.log_label = label


def test_band_tokens_keep_mhz_edges_and_meter_numbers():
    def band(token, freq=""):
        extra = f"<txfreq>{freq}</txfreq>" if freq else ""
        q = LoggedQso.from_contactinfo(
            f"<contactinfo><ID>1</ID><call>K1ABC</call><band>{token}</band>{extra}"
            "</contactinfo>"
        )
        return q.band

    assert band("14") == "20m"
    assert band("50") == "6m"
    assert band("144") == "2m"
    # 10 MHz is below the 30 m edge, so it stays on the MHz path (not 10 m).
    assert band("10") == "40m"
    assert band("10.1") == "30m"
    assert band("28") == "10m"
    assert band("2") == "2m"
    assert band("6") == "6m"
    assert band("3,5") == "80m"
    assert band("70cm") == "70cm"
    assert band("2", "14417400") == "2m"
    # A 2 m frequency wins over a band token that would otherwise be 160 m.
    assert band("160", "14417400") == "2m"


def test_n1mm_contact_flips_mult_to_worked():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    before = _row(live, "K1ABC", now=1.5)
    assert before["is_new_mult"] is True and before["is_needed"] is True
    assert before["mult_reason"] == (
        "Mult: grid FN31 not yet worked on 2m in June VHF."
    )
    live.observe_n1mm(
        _contact("K1ABC", "144", "FN31"), now=1.6, src_ip="10.0.0.2",
    )
    after = _row(live, "K1ABC", now=2.0)
    assert after["is_dupe"] is True and after["is_needed"] is False
    assert after["is_new_mult"] is False
    assert live._log.count() == 1


def test_n1mm_meter_band_and_empty_grid_clear_the_square():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31wa")
    live.observe_n1mm(
        _contact("K1ABC", "2", extra="<txfreq>14417400</txfreq>"),
        now=1.6, src_ip="10.0.0.2",
    )
    row = live._log.con.execute("SELECT band, grid FROM qsos").fetchone()
    assert row["band"] == "2m"
    assert row["grid"] == "FN31WA"
    after = _row(live, "K1ABC", now=2.0)
    assert after["is_dupe"] is True and after["is_new_mult"] is False

    comma = LoggedQso.from_contactinfo(
        "<contactinfo><ID>c</ID><call>K1ABC</call><band>3,5</band></contactinfo>"
    )
    assert comma.band == "80m"


def test_six_char_grid_matches_the_square_including_a_rover():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31wa")
    live.observe_n1mm(_contact("K1ABC", "144", "FN31"), now=1.6, src_ip="10.0.0.2")
    fixed = _row(live, "K1ABC", now=2.0)
    assert fixed["is_dupe"] is True and fixed["is_new_mult"] is False

    live2 = LiveFleet()
    _hear(live2, "SIM-2M", 144_174_000, "K1ROV/R", "FN31wa")
    assert _row(live2, "K1ROV/R", now=1.5)["is_new_mult"] is True
    live2.observe_n1mm(
        _contact("K1ROV/R", "144", "FN31", qid="rov"), now=1.6, src_ip="10.0.0.2",
    )
    rover = _row(live2, "K1ROV/R", now=2.0)
    assert rover["is_dupe"] is True and rover["is_new_mult"] is False


def test_other_band_stays_a_mult_and_the_tip_names_this_band():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    live.observe_n1mm(
        _contact("K1ABC", "50", "FN31"), now=1.0, src_ip="10.0.0.2",
    )
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31", now=1.2)
    row = _row(live, "K1ABC", now=2.0)
    assert row["is_needed"] is True and row["is_new_mult"] is True
    assert row["mult_reason"] == (
        "Mult: grid FN31 not yet worked on 2m in June VHF."
    )
    assert "6m" not in row["mult_reason"]


def test_portable_suffix_stays_needed_but_the_square_is_worked():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    live.observe_n1mm(
        _contact("K1ABC/P", "144", "FN31", qid="p"), now=1.6, src_ip="10.0.0.2",
    )
    row = _row(live, "K1ABC", now=2.0)
    assert row["is_needed"] is True and row["is_dupe"] is False
    assert row["is_new_mult"] is False
    assert "K1ABC/P" in row["need_reason"]
    assert "different call" in row["need_reason"]


def test_start_now_keeps_an_older_contact_a_mult():
    live = LiveFleet()
    live._log.log_label = "June VHF"
    live._log.upsert(LoggedQso(
        id="old", call="K1ABC", band="2m", grid="FN31", mode="FT8",
        points=1, is_mult=False, contest="VHF",
        timestamp="2026-06-14 12:00:00", operator="", rover_location=None,
        source="adif", qso_date="20260614", time_on="120000",
    ))
    live._log.set_window("2026-10-19T18:00:00Z", "")
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    row = _row(live, "K1ABC", now=2.0)
    assert row["is_needed"] is True and row["is_new_mult"] is True
    assert "June VHF" in row["mult_reason"]
    assert "FN31" in row["mult_reason"] and "2m" in row["mult_reason"]
    assert "since" in row["mult_reason"]


def test_qso_logged_udp_flips_mult_without_the_log_agent():
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    adi = home / "WSJT-X - SIM-2M" / "wsjtx_log.adi"
    _adi(adi, [])
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    real_import = builtins.__import__

    def boom(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "wims.log.app":
            raise ModuleNotFoundError("tkinter")
        return real_import(name, globals, locals, fromlist, level)

    try:
        live = LiveFleet()
        _choose_adif(live, adi, "SIM-2M log")
        _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
        assert _row(live, "K1ABC", now=1.5)["is_new_mult"] is True
        builtins.__import__ = boom
        try:
            live.observe_wsjtx(
                M.parse(E.build_qso_logged(
                    "SIM-2M", dx_call="K1ABC", dx_grid="FN31",
                    tx_frequency=0, mode="FT8",
                )),
                now=1.6, src_ip="10.0.0.1",
            )
        finally:
            builtins.__import__ = real_import
        assert live._log.count() == 1
        stored = live._log.con.execute("SELECT band, grid FROM qsos").fetchone()
        assert stored["band"] == "2m" and stored["grid"] == "FN31"
        after = _row(live, "K1ABC", now=2.0)
        assert after["is_dupe"] is True and after["is_new_mult"] is False
    finally:
        builtins.__import__ = real_import
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


def test_qso_in_a_different_log_stays_a_mult():
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    chosen = tmp / "june.adi"
    _adi(chosen, [])
    _adi(home / "WSJT-X - SIM-2M" / "wsjtx_log.adi", [
        ("K1ABC", "20261018", "120000", "2m", "FN31"),
    ])
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    try:
        live = LiveFleet()
        _choose_adif(live, chosen, "June ADIF")
        _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
        live.observe_wsjtx(
            M.parse(E.build_qso_logged(
                "SIM-2M", dx_call="K1ABC", dx_grid="FN31",
                tx_frequency=144_174_000, mode="FT8",
            )),
            now=1.6, src_ip="10.0.0.1",
        )
        assert live._log.count() == 0
        row = _row(live, "K1ABC", now=2.0)
        assert row["is_new_mult"] is True and row["is_needed"] is True
        assert "June ADIF" in row["mult_reason"]
    finally:
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


def test_adif_append_clears_mult_on_the_same_push():
    tmp = Path(tempfile.mkdtemp())
    adi = tmp / "wsjtx_log.adi"
    _adi(adi, [])
    live = LiveFleet()
    _choose_adif(live, adi, "SIM-2M log")
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    assert _row(live, "K1ABC", now=1.5)["is_new_mult"] is True
    _adi(adi, [("K1ABC", "20261018", "120000", "2m", "FN31")])
    _touch_ahead(adi)
    live._adif_poll_mono = 0.0
    after = _row(live, "K1ABC", now=2.0)
    assert after["is_dupe"] is True and after["is_new_mult"] is False
    assert live._log.count() == 1


def test_locked_read_does_not_wipe_a_worked_contact():
    tmp = Path(tempfile.mkdtemp())
    adi = tmp / "wsjtx_log.adi"
    _adi(adi, [("K1ABC", "20261018", "120000", "2m", "FN31")])
    live = LiveFleet()
    _choose_adif(live, adi, "SIM-2M log")
    live._log.upsert(LoggedQso(
        id="kept", call="K1ABC", band="2m", grid="FN31", mode="FT8",
        points=1, is_mult=False, contest="", timestamp="2026-10-18 12:00:00",
        operator="", rover_location=None, source="adif",
    ))
    src = live._adif_source
    src.poll_changed = lambda: True
    src.seed = lambda: []
    src.status = lambda: {"error": "locked"}
    live._adif_poll_mono = 0.0
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    row = _row(live, "K1ABC", now=2.0)
    assert live._log.count() == 1
    assert row["is_dupe"] is True and row["is_new_mult"] is False


def test_n1mm_file_change_clears_mult_without_a_contact_packet():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "june.s3db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE DXLOG (ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, "
        "Mode TEXT, Points INT, IsMultiplier1 INT, ContestName TEXT, "
        "ContestNR INT, TimeStamp TEXT, Operator TEXT)"
    )
    con.commit()
    con.close()
    live = LiveFleet()
    live._install_chosen({
        "kind": "n1mm",
        "label": "June VHF",
        "path": str(db),
        "contest_nr": 1,
        "contest_name": "ARRL-VHF",
    }, [], None)
    live._log_choice_active = True
    live._log.log_label = "June VHF"
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
    assert _row(live, "K1ABC", now=1.5)["is_new_mult"] is True
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("file-1", "K1ABC", "2", "FN31", "FT8", 1, 1, "ARRL-VHF", 1,
         "2026-10-18 12:00:00", "W1AW"),
    )
    con.commit()
    con.close()
    _touch_ahead(db)
    live._adif_poll_mono = 0.0
    after = _row(live, "K1ABC", now=2.0)
    assert after["is_dupe"] is True and after["is_new_mult"] is False
    stored = live._log.con.execute("SELECT band FROM qsos").fetchone()
    assert stored["band"] == "2m"

    # A failed re-read leaves the worked row in place.
    live._log_source.resync = lambda: []
    live._log_source.status = lambda: {"error": "unreadable"}
    _touch_ahead(db)
    live._adif_poll_mono = 0.0
    _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31", now=3.0)
    again = _row(live, "K1ABC", now=3.5)
    assert live._log.count() == 1
    assert again["is_dupe"] is True and again["is_new_mult"] is False


def test_colors_does_not_switch_logs_and_uses_the_selected_file():
    from wims.rules.choice import save_logs
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    chosen = tmp / "june.adi"
    other = home / "WSJT-X - SIM-2M" / "wsjtx_log.adi"
    _adi(chosen, [])
    _adi(other, [("K1ABC", "20261018", "120000", "2m", "FN31")])
    logs_path = tmp / "logs.json"
    rules_path = tmp / "rules.json"
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
                "id": f"adif|{chosen}",
                "kind": "adif",
                "path": str(chosen),
                "label": "June ADIF",
                "contest_nr": None,
                "contest_name": "",
            },
        }, logs_path)
        live = LiveFleet()
        _choose_adif(live, chosen, "June ADIF")
        live._log_in_use["name"] = "June ADIF"
        _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
        assert _row(live, "K1ABC", now=1.4)["is_new_mult"] is True
        paths = [str(p) for p in live._adif_source.paths]
        opened = live.set_rules({
            "action": "select", "goal": "operating", "goal_id": "wsjtx-colors",
        })
        assert opened["ok"] is True
        assert live._log.rules.id == "wsjtx-colors"
        assert [str(p) for p in live._adif_source.paths] == paths
        assert live._log.count() == 0
        still = _row(live, "K1ABC", now=1.8)
        assert still["is_new_mult"] is True
        assert "June ADIF" in still["mult_reason"]
        _adi(chosen, [("K1ABC", "20261018", "120000", "2m", "FN31")])
        _touch_ahead(chosen)
        live._adif_poll_mono = 0.0
        cleared = _row(live, "K1ABC", now=2.2)
        assert cleared["is_new_mult"] is False
        assert cleared["is_dupe"] is True
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


def test_wsjtx_aggregate_accepts_the_instance_file():
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "data"
    shared = tmp / "shared.adi"
    _adi(shared, [])
    prev = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(home)
    try:
        live = LiveFleet()
        _choose_adif(live, shared, "WSJT-X log", kind="wsjtx")
        _hear(live, "SIM-2M", 144_174_000, "K1ABC", "FN31")
        live.observe_wsjtx(
            M.parse(E.build_qso_logged(
                "SIM-2M", dx_call="K1ABC", dx_grid="FN31",
                tx_frequency=144_174_000, mode="FT8",
            )),
            now=1.6, src_ip="10.0.0.1",
        )
        assert live._log.count() == 1
        names = [Path(p).name for p in live._adif_source.paths]
        assert "wsjtx_log.adi" in names
        after = _row(live, "K1ABC", now=2.0)
        assert after["is_dupe"] is True and after["is_new_mult"] is False
    finally:
        if prev is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = prev


_CX_LOG = "WSJT-X - IC7300/wsjtx_log.adi"
_CX_OLD = (
    "<call:6>CX4BAN <gridsquare:4>GF15 <mode:3>FT8 "
    "<qso_date:8>20210202 <time_on:6>154500 <band:3>40m <eor>"
)
_CX_NEW = (
    "<call:6>CX4BAN <gridsquare:0> <mode:3>FT8 <rst_sent:3>-09 <rst_rcvd:3>-08 "
    "<qso_date:8>20261019 <time_on:6>022845 <band:3>20m <freq:9>14.074738 "
    "<station_callsign:6>WA1HCO <eor>"
)


def _cx_file(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("WSJT-X\n<eoh>\n" + body + "\n", encoding="utf-8")


def _cx_colors(live):
    from wims.engine.contest_rules import WsjtxColors, default_color_categories
    cats, _note = default_color_categories(cty_ok=False)
    live._log.rules = WsjtxColors(categories=cats, log_label=_CX_LOG)
    live._log.log_label = _CX_LOG


def _hear_cx(live, now=1.0, message="CQ DX CX4BAN GF15"):
    live.observe_wsjtx(
        M.parse(E.build_status(
            "IC7300", 14_074_738, mode="FT8", decoding=True, de_call="WA1HCO",
        )),
        now=now, src_ip="10.0.0.8",
    )
    live.observe_wsjtx(
        M.parse(E.build_decode(
            "IC7300", time_ms=0, snr=-8, delta_time=0.2,
            delta_frequency=800, mode="FT8", message=message,
        )),
        now=now + 0.1, src_ip="10.0.0.8",
    )


def _stored_grids(live):
    return {
        (row["band"], row["grid"] or "")
        for row in live._log.con.execute("SELECT band, grid FROM qsos")
    }


def test_cx4ban_empty_grid_credits_the_heard_square():
    """The shared IC7300 log, the 2021 40 m GF15 line, and the new blank 20 m line.

    WSJT-X writes <gridsquare:0> when the exchange never sent a grid. The CQ
    WIMS heard was 'CQ DX CX4BAN GF15'. That square is on 20 m, so the 40 m
    record does not clear it. Once the 20 m line is in the selected log, the
    heard square is credited and the station is worked, not a mult.
    """
    tmp = Path(tempfile.mkdtemp())
    adi = tmp / "WSJT-X - IC7300" / "wsjtx_log.adi"
    _cx_file(adi, _CX_OLD)
    live = LiveFleet()
    _choose_adif(live, adi, _CX_LOG, kind="wsjtx")
    _cx_colors(live)
    _hear_cx(live)
    before = _row(live, "CX4BAN", now=1.5)
    assert before["band"] == "20m"
    assert before["is_needed"] is True and before["is_new_mult"] is True
    assert before["grid"] == "GF15"
    assert "GF15" in before["mult_reason"] and "20m" in before["mult_reason"]
    assert _CX_LOG in before["mult_reason"]
    assert ("40m", "GF15") in _stored_grids(live)
    assert ("20m", "GF15") not in _stored_grids(live)

    _cx_file(adi, _CX_OLD + "\n" + _CX_NEW)
    _touch_ahead(adi)
    live._adif_poll_mono = 0.0
    after = _row(live, "CX4BAN", now=2.5)
    assert after["is_needed"] is False and after["is_dupe"] is True
    assert after["is_new_mult"] is False
    assert "GF15" in after["need_reason"] and "20m" in after["need_reason"]
    assert _CX_LOG in after["need_reason"]
    assert ("20m", "GF15") in _stored_grids(live)

    # The file was already read, with a blank grid, before the CQ was scored.
    # A later push still credits GF15 without waiting for the file to change.
    adi2 = tmp / "already-read.adi"
    _cx_file(adi2, _CX_OLD + "\n" + _CX_NEW)
    live2 = LiveFleet()
    _choose_adif(live2, adi2, _CX_LOG, kind="adif")
    _cx_colors(live2)
    assert live2.snapshot(1.0)["roster"]["count"] == 0
    assert ("20m", "") in _stored_grids(live2)
    assert ("20m", "GF15") not in _stored_grids(live2)
    live2._adif_source.poll_changed = lambda: False
    _hear_cx(live2, now=2.0)
    later = _row(live2, "CX4BAN", now=2.5)
    assert later["is_needed"] is False and later["is_new_mult"] is False
    assert ("20m", "GF15") in _stored_grids(live2)
    assert "already in" in later["need_reason"]
    assert "GF15" in later["need_reason"]

    # No grid on the decode: the 20 m line is still worked, and there is no
    # square to mark as a new mult.
    adi3 = tmp / "no-grid-decode.adi"
    _cx_file(adi3, _CX_OLD + "\n" + _CX_NEW)
    live3 = LiveFleet()
    _choose_adif(live3, adi3, _CX_LOG, kind="adif")
    _cx_colors(live3)
    live3.snapshot(1.0)
    _hear_cx(live3, now=2.0, message="CQ DX CX4BAN")
    plain = _row(live3, "CX4BAN", now=2.5)
    assert plain["is_needed"] is False and plain["is_dupe"] is True
    assert plain["is_new_mult"] is False

    # Same records under ARRL VHF. 40 m GF15 does not clear 20 m until the
    # blank 20 m line takes the square from the CQ.
    adi4 = tmp / "arrl.adi"
    _cx_file(adi4, _CX_OLD + "\n" + _CX_NEW)
    live4 = LiveFleet()
    _choose_adif(live4, adi4, _CX_LOG, kind="adif")
    assert live4._log.rules.id == "arrl-vhf"
    live4.snapshot(1.0)
    live4._adif_source.poll_changed = lambda: False
    _hear_cx(live4, now=2.0)
    arrl = _row(live4, "CX4BAN", now=2.5)
    assert arrl["is_needed"] is False and arrl["is_new_mult"] is False
    assert "Already worked" in arrl["need_reason"]
    assert "GF15" in arrl["need_reason"] and "20m" in arrl["need_reason"]
    assert ("20m", "GF15") in _stored_grids(live4)


def test_mult_badge_names_the_reason():
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(
        encoding="utf-8",
    )
    badge = js.split("function rosCall", 1)[1].split("function rosCalling", 1)[0]
    assert "escAttr(c.mult_reason" in badge
    assert 'class="badge"' in badge
    draw = js.split("function rosDraw", 1)[1].split("function txPost", 1)[0]
    assert "c.mult_reason" in draw


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
