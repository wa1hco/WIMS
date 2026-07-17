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

"""Tests for fleet discovery, health, and expected-vs-actual."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.discovery.fleet import FleetTracker, ExpectedInstance  # noqa: E402

HEARTBEAT = bytes.fromhex(
    "adbccbda00000002000000000000000657534a542d58"
    "0000000300000005332e302e3000000006616239373662"
)
STATUS_6M = bytes.fromhex(
    "adbccbda00000002000000010000000657534a542d580000000002ffb728"
    "00000003465438000000054b3447444a000000032d31350000000346543800"
    "0001000005dc000003600000000657413148434f00000006464e3432455600"
    "000004454c393800ffffffff0000ffffffffffffffff0000000744656661756c74ffffffff"
)
DECODE = bytes.fromhex(
    "adbccbda00000002000000020000000657534a542d5801007c4868000000143f"
    "c99999a00000000000031b000000017e0000000c4351204e4a314820464e34320000"
)


def test_discovers_instance_and_band():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")
    t.observe(M.parse(STATUS_6M), now=101.0, src_ip="192.168.10.21")
    t.observe(M.parse(DECODE), now=102.0, src_ip="192.168.10.21")
    n = t.nodes["WSJT-X"]
    assert n.band == "6m"
    assert n.mode == "FT8"
    assert n.version == "3.0.0"
    assert n.decode_count == 1
    assert n.host == "192.168.10.21"


def test_health_transitions():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")
    n = t.nodes["WSJT-X"]
    assert n.health(now=110.0) == "ALIVE"   # 10s
    assert n.health(now=145.0) == "STALE"   # 45s (>2*15)
    assert n.health(now=200.0) == "DEAD"    # 100s (>4*15)


def test_prune_drops_silent_instances():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")
    assert "WSJT-X" in t.nodes
    # Still within prune window (default 120s) — keep, even if DEAD for UI.
    assert t.prune(now=200.0) == []
    assert "WSJT-X" in t.nodes
    removed = t.prune(now=230.0)   # 130s silent > 120s
    assert removed == ["WSJT-X"]
    assert "WSJT-X" not in t.nodes


def test_id_collision_recent_hosts_only():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="127.0.0.1")
    t.observe(M.parse(HEARTBEAT), now=101.0, src_ip="192.168.1.50")
    n = t.nodes["WSJT-X"]
    assert n.id_collision_at(now=105.0) is True
    # Desktop path gone; only VM still sending — no sticky collision.
    t.observe(M.parse(HEARTBEAT), now=200.0, src_ip="192.168.1.50")
    assert n.id_collision_at(now=200.0) is False
    assert n.host == "192.168.1.50"


def test_quiet_detection():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")
    t.observe(M.parse(STATUS_6M), now=100.0, src_ip="192.168.10.21")
    # Heartbeats keep coming but no decodes -> alive but QUIET.
    t.observe(M.parse(HEARTBEAT), now=170.0, src_ip="192.168.10.21")
    n = t.nodes["WSJT-X"]
    assert n.health(now=170.0) == "ALIVE"
    assert n.is_quiet(now=170.0) is True


def test_expected_missing_and_unexpected():
    t = FleetTracker()
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")  # id "WSJT-X"
    expected = [
        ExpectedInstance(id="ROY-432", band="70cm", vehicle="Roy"),
        ExpectedInstance(id="TRAILER-6M", band="6m", vehicle="Trailer"),
    ]
    issues = {d.kind for d in t.diff_expected(expected, now=100.0)}
    assert "missing" in issues       # ROY-432 / TRAILER-6M not on the wire
    assert "unexpected" in issues    # observed "WSJT-X" not in expected


def test_n1mm_presence_from_capture():
    import glob
    import json
    caps = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "captures" / "n1mm-*.jsonl")))
    if not caps:
        return  # no N1MM capture available -> skip
    t = FleetTracker()
    for line in open(caps[-1], encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("root") == "contactinfo":
            t.observe_n1mm_xml(rec["text"], now=100.0, src_ip="127.0.0.1")
    assert t.loggers, "no logger discovered from contactinfo"
    lg = next(iter(t.loggers.values()))
    assert lg.kind == "N1MM"
    assert lg.id == "DESKTOP-E34PGI3"        # the StationName in the capture
    assert lg.last_call is not None          # last QSO recorded (whichever it was)
    assert lg.last_band == "20m"             # band 14 MHz -> 20m
    assert lg.qso_count >= 1


def test_n1mm_presence_synthetic():
    t = FleetTracker()
    xml = ("<contactinfo><app>N1MM</app><StationName>ROY-PC</StationName>"
           "<call>K1ABC</call><band>432</band><mode>FT8</mode></contactinfo>")
    t.observe_n1mm_xml(xml, now=50.0, src_ip="192.168.10.21")
    assert "ROY-PC" in t.loggers
    n = t.loggers["ROY-PC"]
    assert n.last_call == "K1ABC" and n.last_band == "70cm" and n.host == "192.168.10.21"


def test_n1mm_radioinfo_presence_without_qso():
    # A real <RadioInfo> beacon (no QSO) must register the N1MM instance so the link
    # is verifiable during setup, without logging a contact.
    t = FleetTracker()
    xml = ("<RadioInfo><app>N1MM</app><StationName>DESKTOP-E34PGI3</StationName>"
           "<RadioNr>1</RadioNr><Freq>5031300</Freq><Mode>MIXED+DIG</Mode>"
           "<mycall>W2SZ</mycall><IsConnected>False</IsConnected></RadioInfo>")
    t.observe_n1mm_xml(xml, now=100.0, src_ip="127.0.0.1")
    assert "DESKTOP-E34PGI3" in t.loggers
    n = t.loggers["DESKTOP-E34PGI3"]
    assert n.last_seen == 100.0          # presence established
    assert n.mycall == "W2SZ"
    assert n.last_qso is None            # but no QSO logged yet
    assert n.qso_count == 0
    # A later contactinfo then records the QSO on the same node.
    t.observe_n1mm_xml("<contactinfo><app>N1MM</app><StationName>DESKTOP-E34PGI3</StationName>"
                       "<call>K1ABC</call><band>50</band></contactinfo>", now=160.0, src_ip="127.0.0.1")
    assert n.qso_count == 1 and n.last_qso == 160.0 and n.last_seen == 160.0


def test_id_collision_detected():
    t = FleetTracker()
    # Same id "WSJT-X" from two different hosts = unresolvable instances.
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.21")
    t.observe(M.parse(HEARTBEAT), now=100.0, src_ip="192.168.10.22")
    n = t.nodes["WSJT-X"]
    assert n.id_collision is True
    issues = [d for d in t.diff_expected([], now=100.0) if d.kind == "id-collision"]
    assert issues and issues[0].severity == "error"


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
