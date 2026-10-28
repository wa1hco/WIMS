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

"""DX cluster spots: parse, read-only login, filter, score, QSY flag."""

import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine import scoring as S  # noqa: E402
from wims.engine.contest_rules import load_builtin  # noqa: E402
from wims.engine.geo import distance_km  # noqa: E402
from wims.integrations.cluster.client import (  # noqa: E402
    BACKOFF_START, LOGIN_WAIT_S, ClusterLink, ClusterService, is_login_prompt,
    next_backoff, sent_text,
)
from wims.integrations.cluster.modes import infer_mode  # noqa: E402
from wims.integrations.cluster.parse import parse_spot  # noqa: E402
from wims.integrations.cluster.ranges import in_range  # noqa: E402
from wims.integrations.cluster.settings import (  # noqa: E402
    DEFAULT_HOST, DEFAULT_PORT, all_bands, load, save,
)
from wims.integrations.cluster.telnet import strip_telnet  # noqa: E402
from wims.integrations.cluster.view import (  # noqa: E402
    OnAir, SpotBook, build_list, status_line,
)
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.state.heard_grids import HeardGrids  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dx_cluster_spots.txt"
AR_CLUSTER = Path(__file__).resolve().parents[1] / "fixtures" / "cluster_ar_cluster.txt"
DX_SPIDER = Path(__file__).resolve().parents[1] / "fixtures" / "cluster_dx_spider.txt"
SILENT_NODE = Path(__file__).resolve().parents[1] / "fixtures" / "cluster_silent.txt"
HOME = "FN42ev"
NOW = 1_700_000_000.0


def _log():
    log = LogStore(":memory:")
    log.rules = load_builtin("arrl-vhf")
    return log


def _book(lines, now=NOW):
    book = SpotBook()
    for line in lines:
        spot = parse_spot(line)
        assert spot is not None, line
        book.add(spot, now)
    return book


def _rows(lines, *, operations=None, allowed=None, grid=HOME, heard=None,
          qsy_cost=8, now=NOW, received=None, log=None):
    store = log if log is not None else _log()
    memory = heard

    def classify(call, band, square, mode):
        return store.classify(call, band, square, mode)

    def grid_for(call):
        if memory is None:
            return ""
        return memory.lookup(call, now).grid or ""

    rows, drops = build_list(
        _book(lines, now if received is None else received).rows(),
        now=now, ttl_s=15 * 60, our_grid=grid,
        allowed=allowed, operations=operations or [], classify=classify,
        grid_for=grid_for, qsy_cost=qsy_cost,
    )
    return rows, drops


def test_fixture_lines_parse():
    text = FIXTURE.read_text(encoding="utf-8")
    spots = []
    skipped = 0
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        spot = parse_spot(line)
        if spot is None:
            skipped += 1
            continue
        spots.append(spot)
    calls = [s.call for s in spots]
    assert calls == ["K1ABC", "K1ABC", "N0ROV/R", "W2XYZ", "K4CW", "EA8/DK9TN", "JA1ABC", "VE3ABC"]
    assert skipped == 3
    k1 = spots[0]
    assert k1.spotter == "K1TTT"
    assert k1.band == "10m"
    assert k1.grid == "FN42"
    assert k1.freq_hz == 28_074_000
    assert spots[2].spotter == "W3LPL-#"
    assert spots[2].grid == "FN31"
    assert spots[5].call == "EA8/DK9TN"
    assert spots[5].band == "6m"


def test_mhz_frequency_and_grid_not_rr73():
    mhz = parse_spot("DX de K1TTT: 14.074 JA1ABC PM95 1200Z")
    assert mhz is not None and mhz.freq_hz == 14_074_000 and mhz.band == "20m"
    rr = parse_spot("DX de K1TTT: 28074.0 K1ABC RR73 FN42 1201Z")
    assert rr is not None and rr.grid == "FN42"
    junk = parse_spot("DX de K1TTT: 123.0 NOTACALL nothing 1202Z")
    assert junk is None


def test_login_sends_only_the_callsign():
    sent = bytearray()
    link = ClusterLink("wa1hco", sent.extend)
    banner = bytes([255, 251, 1]) + b"Please enter your call:\r\n"
    line = b"DX de K1TTT:      28074.0  K1ABC        FN42 FT8                      1734Z\r\n"
    spots = link.feed(banner)
    spots += link.feed(line)
    assert [s.call for s in spots] == ["K1ABC"]
    assert link.sent_login
    text = sent_text(bytes(sent))
    assert text.strip() == "WA1HCO"
    assert "DX de" not in text
    for banned in ("set/", "announce", "sh/dx", "talk", "bye"):
        assert banned not in text.lower()
    # The telnet refusal is present, and it is not text.
    assert bytes(sent).startswith(bytes([255, 254, 1]))


def test_name_prompt_is_not_answered():
    sent = bytearray()
    link = ClusterLink("WA1HCO", sent.extend)
    link.feed(b"Your name:\r\n")
    assert link.extra
    assert sent == bytearray()
    assert not is_login_prompt("Your name:")
    assert is_login_prompt("Please enter your call:")
    assert is_login_prompt("login:")
    assert is_login_prompt("LOGIN:")
    assert is_login_prompt("CALL:")
    assert is_login_prompt("Callsign:")
    for prompt in (b"Login:\r\n", b"CALL:\r\n", b"PLEASE ENTER YOUR CALL:\r\n"):
        sent = bytearray()
        again = ClusterLink("wa1hco", sent.extend)
        again.feed(prompt)
        assert again.sent_login, prompt
        assert sent_text(bytes(sent)).strip() == "WA1HCO"


def test_mode_from_comment_then_frequency():
    assert infer_mode(28_074_000, "FN42 FT8", "10m") == "FT8"
    assert infer_mode(28_025_000, "CW", "10m") == "CW"
    assert infer_mode(28_074_000, "", "10m") == "FT8"
    assert infer_mode(28_180_000, "", "10m") == "FT4"
    assert infer_mode(28_400_000, "", "10m") == "SSB"
    assert infer_mode(50_313_000, "", "6m") == "FT8"
    assert infer_mode(50_260_000, "MSK", "6m") == "MSK144"
    assert infer_mode(144_174_000, "", "2m") == "FT8"
    assert infer_mode(50_125_000, "SSB", "6m") == "SSB"
    assert infer_mode(14_074_000, "Q65", "20m") == "Q65"


def test_other_bands_stay_and_are_marked_qsy():
    rows, drops = _rows(
        [
            "DX de K1TTT: 28074.0 K1ABC FN42 FT8 1734Z",
            "DX de K2SPO: 144174.0 W2XYZ FN20 1736Z",
            "DX de G4ABC: 50313.0 EA8/DK9TN IL18 1737Z",
        ],
        operations=[OnAir("10m", "FT8")],
    )
    by = {row["call"]: row for row in rows}
    assert "K1ABC" in by and by["K1ABC"]["where"] == "on band"
    assert by["K1ABC"]["mode"] == "FT8" and by["K1ABC"]["band"] == "10m"
    assert "W2XYZ" in by and by["W2XYZ"]["where"] == "QSY"
    assert by["W2XYZ"]["band"] == "2m" and by["W2XYZ"]["mode"] == "FT8"
    # 6m is not the radio we are on. IL18 is about 5100 km, inside the 6m window.
    assert distance_km(HOME, "IL18") < 6000
    assert in_range(distance_km(HOME, "IL18"), "6m", "FT8")
    assert "EA8/DK9TN" in by and by["EA8/DK9TN"]["where"] == "QSY"
    assert by["EA8/DK9TN"]["band"] == "6m"
    assert drops["spot_count"] == 3


def test_cw_on_the_same_band_is_qsy_not_dropped():
    rows, _drops = _rows(
        ["DX de K5DX: 28025.0 K4CW CW 1736Z"],
        operations=[OnAir("10m", "FT8")],
        heard=_heard("K4CW", "FN42"),
    )
    assert len(rows) == 1
    assert rows[0]["mode"] == "CW"
    assert rows[0]["where"] == "QSY"
    assert rows[0]["band"] == "10m"
    names = [f["name"] for f in rows[0]["factors"]]
    assert "qsy" in names


def test_far_vhf_dropped_hf_kept():
    assert distance_km(HOME, "PM95") > 900
    assert distance_km(HOME, "PM95") < 18000
    assert not in_range(distance_km(HOME, "PM95"), "2m", "FT8")
    assert in_range(distance_km(HOME, "PM95"), "20m", "FT8")
    rows, drops = _rows([
        "DX de N1ABC: 144174.0 JA1ABC PM95 FT8 1737Z",
        "DX de N1ABC: 14074.0 JA1ABC PM95 FT8 1737Z",
    ])
    assert [row["band"] for row in rows] == ["20m"]
    assert drops["range"] == 1


def test_dupe_and_missing_grid_and_age():
    log = _log()
    log.upsert(LoggedQso(
        id="q1", call="K1ABC", band="10m", grid="FN42", mode="FT8",
        points=1, is_mult=True, contest="VHF", timestamp="", operator="",
        rover_location=None, source="test",
    ))
    rows, drops = _rows(
        [
            "DX de K1TTT: 28074.0 K1ABC FN42 FT8 1734Z",
            "DX de K1TTT: 28074.0 N0NEW 1734Z",
        ],
        log=log,
    )
    assert rows == []
    assert drops["worked"] == 1
    assert drops["no_grid"] == 1
    old, old_drops = _rows(
        ["DX de K1TTT: 28074.0 K1ABC FN42 FT8 1734Z"],
        received=NOW,
        now=NOW + 16 * 60,
    )
    assert old == []
    assert old_drops["spot_count"] == 0


def test_heard_grid_fills_a_blank_comment():
    heard = _heard("W2XYZ", "FN20")
    rows, drops = _rows(
        ["DX de K2SPO: 144174.0 W2XYZ 1736Z"],
        heard=heard,
    )
    assert drops["no_grid"] == 0
    assert len(rows) == 1 and rows[0]["grid"] == "FN20"


def test_unchecked_band_is_hidden():
    rows, drops = _rows(
        [
            "DX de K1TTT: 28074.0 K1ABC FN42 FT8 1734Z",
            "DX de K2SPO: 144174.0 W2XYZ FN20 1736Z",
        ],
        allowed={"10m"},
    )
    assert [row["call"] for row in rows] == ["K1ABC"]
    assert drops["spot_count"] == 1


def test_msk_too_close_is_not_workable():
    assert not in_range(distance_km(HOME, "FN42"), "6m", "MSK144")
    rows, drops = _rows(
        ["DX de K1TTT: 50260.0 K1MSK FN42 MSK144 1734Z"],
    )
    assert rows == []
    assert drops["range"] == 1


def test_qsy_cost_is_a_penalty_not_a_gate():
    same = dict(
        is_new_mult=True, chase="", is_rover=False, age_s=0, ttl_s=900,
        spotter_count=1, spotter_near=0, distance_fit=1,
    )
    on = S.score_spot(S.SpotFeatures(needs_qsy=False, **same))
    qsy = S.score_spot(S.SpotFeatures(needs_qsy=True, **same))
    free = S.score_spot(
        S.SpotFeatures(needs_qsy=True, **same), S.cluster_weights(0),
    )
    assert qsy.total == round(on.total - 8, 1)
    assert free.total == on.total
    assert any(f.name == "qsy" and f.contribution == -8 for f in qsy.factors)
    assert all(f.name != "qsy" for f in free.factors)
    # A new grid that needs a QSY still outranks an ordinary needed contact.
    plain = S.score_spot(S.SpotFeatures(
        is_new_mult=False, needs_qsy=False, age_s=0, ttl_s=900,
        spotter_count=1, distance_fit=1,
    ))
    assert qsy.total > plain.total


def test_weights_are_named():
    names = set(S.CLUSTER_WEIGHTS)
    assert names == {
        "need_new", "need_call", "need_unconfirmed", "recency", "spotters",
        "spotter_near", "distance", "rover", "qsy",
    }
    assert S.CLUSTER_WEIGHTS["qsy"] < 0
    assert S.cluster_weights(12)["qsy"] == -12


def test_status_lines_name_the_next_step():
    assert status_line(
        enabled=False, phase="off", host=DEFAULT_HOST, port=23, callsign="",
        retry_s=0, reason="", spot_count=0, needed_count=0,
        bands_empty=False, have_grid=True,
    ) == "Cluster: off. Turn it on in Setup."
    assert "WSJT-X has not sent one yet" in status_line(
        enabled=True, phase="need_call", host=DEFAULT_HOST, port=23, callsign="",
        retry_s=0, reason="", spot_count=0, needed_count=0,
        bands_empty=False, have_grid=True,
    )
    connected = status_line(
        enabled=True, phase="connected", host=DEFAULT_HOST, port=DEFAULT_PORT,
        callsign="WA1HCO", retry_s=0, reason="", spot_count=12, needed_count=3,
        bands_empty=False, have_grid=True,
    )
    assert connected == "Cluster: logged in, 12 spots, 3 needed"
    assert status_line(
        enabled=True, phase="tcp", host=DEFAULT_HOST, port=DEFAULT_PORT,
        callsign="WA1HCO", retry_s=0, reason="", spot_count=0, needed_count=0,
        bands_empty=False, have_grid=True,
    ) == "Cluster: connected, no spots yet."
    assert status_line(
        enabled=True, phase="logged_in", host=DEFAULT_HOST, port=DEFAULT_PORT,
        callsign="WA1HCO", retry_s=0, reason="", spot_count=0, needed_count=0,
        bands_empty=False, have_grid=True,
    ) == "Cluster: logged in, no spots yet."
    silent = status_line(
        enabled=True, phase="silent", host="dxc.ve7cc.net", port=23,
        callsign="WA1HCO", retry_s=5, reason="silent", spot_count=0,
        needed_count=0, bands_empty=False, have_grid=True,
    )
    assert silent.startswith("Cluster: node sent nothing. Try another node on Setup.")
    assert "0 spots" not in silent
    retry = status_line(
        enabled=True, phase="retry", host=DEFAULT_HOST, port=23,
        callsign="WA1HCO", retry_s=40, reason="timeout", spot_count=0,
        needed_count=0, bands_empty=False, have_grid=True,
    )
    assert "can't reach" in retry and "Setup" in retry and "40" in retry
    assert "Choose bands in Setup" in status_line(
        enabled=True, phase="connected", host=DEFAULT_HOST, port=23,
        callsign="WA1HCO", retry_s=0, reason="", spot_count=0, needed_count=0,
        bands_empty=True, have_grid=True,
    )
    assert "No grid from WSJT-X" in status_line(
        enabled=True, phase="connected", host=DEFAULT_HOST, port=23,
        callsign="WA1HCO", retry_s=0, reason="", spot_count=4, needed_count=0,
        bands_empty=False, have_grid=False,
    )


def test_backoff_never_tight():
    assert next_backoff(0) == BACKOFF_START
    assert next_backoff(5) == 10
    assert next_backoff(160) == 300
    assert next_backoff(300) == 300
    assert BACKOFF_START >= 5


def test_settings_default_all_bands_and_node():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cluster.json"
        fresh = load(path)
        assert fresh["enabled"] is False
        assert fresh["host"] == "k1ttt.net"
        assert fresh["port"] == 7373
        assert fresh["node"] == "k1ttt"
        assert fresh["bands"] == "all"
        assert fresh["qsy_cost"] == 8
        save({"enabled": True, "host": "bad host", "port": 23,
              "bands": ["10m", "nope", "6m"], "qsy_cost": 12}, path)
        again = load(path)
        assert again["enabled"] is True
        assert again["host"] == DEFAULT_HOST
        assert again["bands"] == ["10m", "6m"]
        assert again["qsy_cost"] == 12
        assert "160m" in all_bands() and "2m" in all_bands() and "70cm" in all_bands()
        old = Path(tmp) / "old.json"
        old.write_text(
            '{"schema": 1, "enabled": true, "host": "dxc.ve7cc.net", '
            '"port": 23, "bands": "all", "qsy_cost": 8}\n',
            encoding="utf-8",
        )
        moved = load(old)
        assert moved["host"] == "k1ttt.net" and moved["port"] == 7373
        assert moved["node"] == "k1ttt"
        kept = Path(tmp) / "kept.json"
        kept.write_text(
            '{"schema": 2, "node": "ve7cc", "enabled": true, '
            '"host": "dxc.ve7cc.net", "port": 23, "bands": "all", "qsy_cost": 8}\n',
            encoding="utf-8",
        )
        stay = load(kept)
        assert stay["node"] == "ve7cc"
        assert stay["host"] == "dxc.ve7cc.net" and stay["port"] == 23


def test_reconnect_waits_out_the_backoff():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cluster.json"
        sleeps = []

        def boom(_address, _timeout):
            raise ConnectionRefusedError("no")

        svc = ClusterService(path=path, connect=boom)

        def pause(seconds):
            sleeps.append(seconds)
            svc._stop.set()

        svc._sleep = pause
        svc.update({"enabled": True})
        svc.start(lambda: "WA1HCO")
        svc._thread.join(timeout=2)
        assert sleeps == [5.0]
        assert svc.phase == "retry"
        assert svc.reason == "refused_port"


def test_select_does_not_transmit_or_retune():
    from wims.server.app import LiveFleet

    live = LiveFleet()

    class Tx:
        def __init__(self):
            self.calls = []

        def reply(self, *args, **kwargs):
            self.calls.append(("reply", args, kwargs))

        def halt(self, *args, **kwargs):
            self.calls.append(("halt", args, kwargs))

        def configure(self, *args, **kwargs):
            self.calls.append(("configure", args, kwargs))

        def configure_grid(self, *args, **kwargs):
            self.calls.append(("grid", args, kwargs))

    live._tx = Tx()
    out = live.select_spot({
        "call": "K1ABC", "grid": "FN42ev", "band": "10m", "mode": "FT8",
    })
    assert out["ok"] is True
    assert out["transmitted"] is False
    assert out["retuned"] is False
    assert live._tx.calls == []
    assert "not retuned" in out["line"]
    assert "Work needs a live decode" in out["line"]
    found = live._heard.lookup("K1ABC", time.time())
    assert (found.grid or "").startswith("FN42")
    # The click path is not the Work path.
    assert not hasattr(live.select_spot, "reply")


def test_telnet_refusal_only():
    reply = bytearray()
    plain = strip_telnet(bytes([255, 251, 1, 65, 66]), reply, {})
    assert plain == b"AB"
    assert bytes(reply) == bytes([255, 254, 1])


def _heard(call, grid):
    memory = HeardGrids()
    assert memory.note(call, grid, "10m", NOW)
    return memory


def test_service_public_uses_goal_and_qsy_flag():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cluster.json"
        svc = ClusterService(path=path)
        svc.update({"enabled": True, "qsy_cost": 8, "bands": "all"})
        assert svc.ingest("DX de K1TTT: 28074.0 K1ABC FN42 FT8 1734Z", NOW)
        assert svc.ingest("DX de K2SPO: 144174.0 W2XYZ FN20 1736Z", NOW)
        with svc._lock:
            svc.phase = "connected"
        log = _log()

        def classify(call, band, grid, mode):
            return log.classify(call, band, grid, mode)

        view = svc.public(
            now=NOW, callsign="WA1HCO", our_grid=HOME,
            operations=[OnAir("10m", "FT8")], classify=classify,
        )
        assert view["status_line"] == "Cluster: logged in, 2 spots, 2 needed"
        assert "Last spot" in view["detail"]
        where = {row["call"]: row["where"] for row in view["rows"]}
        assert where["K1ABC"] == "on band"
        assert where["W2XYZ"] == "QSY"
        assert view["rows"][0]["score"] >= view["rows"][1]["score"]
        # Sorted, and the QSY row is still present.
        assert {row["call"] for row in view["rows"]} == {"K1ABC", "W2XYZ"}


def test_no_callsign_does_not_open_a_socket():
    with tempfile.TemporaryDirectory() as tmp:
        opened = []

        def boom(*_a, **_k):
            opened.append(1)
            raise AssertionError("should not connect")

        svc = ClusterService(path=Path(tmp) / "cluster.json", connect=boom)

        def pause(_seconds):
            svc._stop.set()

        svc._sleep = pause
        svc.update({"enabled": True})
        svc.start(lambda: "")
        svc._thread.join(timeout=2)
        assert opened == []
        assert svc.phase == "need_call"


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class _ScriptSock:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = bytearray()

    def settimeout(self, _seconds):
        return None

    def sendall(self, data):
        self.sent += data

    def recv(self, _n):
        if not self.chunks:
            return b""
        item = self.chunks.pop(0)
        if item is None:
            raise socket.timeout()
        return item

    def close(self):
        return None


def _node_bytes(path: Path) -> bytes:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        return b""
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def _play(blob: bytes):
    with tempfile.TemporaryDirectory() as tmp:
        svc = ClusterService(path=Path(tmp) / "cluster.json")
        svc.update({"enabled": True, "bands": "all"})
        sock = _ScriptSock([blob])
        try:
            svc._read_loop(sock, "WA1HCO", svc._gen)
        except TimeoutError:
            pass
        log = _log()

        def classify(call, band, grid, mode):
            return log.classify(call, band, grid, mode)

        view = svc.public(
            now=time.time(), callsign="WA1HCO", our_grid=HOME, operations=[],
            classify=classify,
        )
        return sock, view


def test_prompt_any_case_and_no_login_into_silence():
    clock = _Clock()
    sent = bytearray()
    link = ClusterLink("WA1HCO", sent.extend, now=clock)
    clock.t = LOGIN_WAIT_S + 1
    link.poll()
    assert sent == bytearray()
    link.feed(b"Welcome to the DX Spider cluster\r\n")
    clock.t = LOGIN_WAIT_S - 0.1
    link.poll()
    assert b"WA1HCO" not in sent
    clock.t = LOGIN_WAIT_S
    link.poll()
    assert sent_text(bytes(sent)).strip() == "WA1HCO"


def test_silent_node_is_not_called_connected():
    assert _node_bytes(SILENT_NODE) == b""
    clock = _Clock()

    class Sock(_ScriptSock):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        def recv(self, _n):
            self.calls += 1
            clock.t = 59.0 if self.calls == 1 else 60.0
            raise socket.timeout()

    sock = Sock()
    with tempfile.TemporaryDirectory() as tmp:
        svc = ClusterService(
            path=Path(tmp) / "cluster.json", connect=lambda *_a, **_k: sock,
            monotonic=clock,
        )

        def pause(_seconds):
            svc._stop.set()

        svc._sleep = pause
        svc.update({"enabled": True})
        svc.start(lambda: "WA1HCO")
        svc._thread.join(timeout=2)
        assert svc.phase == "silent"
        assert sock.sent.startswith(b"\r\n")
        assert b"WA1HCO" not in sock.sent
        view = svc.public(
            now=NOW, callsign="WA1HCO", our_grid=HOME, operations=[],
            classify=lambda *_a: None,
        )
        assert view["status_line"].startswith(
            "Cluster: node sent nothing. Try another node on Setup.")
        assert "0 spots" not in view["status_line"]
        assert "No spot line yet" in view["detail"]


def test_ar_cluster_and_dx_spider_transcripts():
    ar_sock, ar = _play(_node_bytes(AR_CLUSTER))
    assert ar_sock.sent.startswith(b"\r\n")
    assert sent_text(bytes(ar_sock.sent)).strip() == "WA1HCO"
    assert "set/" not in sent_text(bytes(ar_sock.sent)).lower()
    assert "logged in" in ar["status_line"]
    assert any(row["call"] == "K1ABC" for row in ar["rows"])
    assert "Last spot" in ar["detail"]

    spider_sock, spider = _play(_node_bytes(DX_SPIDER))
    assert sent_text(bytes(spider_sock.sent)).strip() == "WA1HCO"
    assert any(row["call"] == "JA1ABC" for row in spider["rows"])
    assert "logged in" in spider["status_line"]


def test_thread_stops():
    # A disabled service pauses and must exit when stopped.
    with tempfile.TemporaryDirectory() as tmp:
        svc = ClusterService(path=Path(tmp) / "cluster.json")
        started = threading.Event()

        def pause(_seconds):
            started.set()
            svc._stop.wait(1)

        svc._sleep = pause
        svc.start(lambda: "WA1HCO")
        assert started.wait(2)
        svc.stop()
        assert svc._thread is None or not svc._thread.is_alive()


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
