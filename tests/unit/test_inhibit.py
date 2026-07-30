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

"""TX-inhibit gate + Key-agent scheduler — state machine proofs (design §11.1/§3)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.interlock.inhibit import (  # noqa: E402
    InhibitGate,
    KeyAgentScheduler,
    encode_datagram,
    parse_datagram,
)


def dg(state, station="ROY-222-SSB", band="222", seq=1, ttl_ms=600):
    return encode_datagram(state, station, band, seq, ttl_ms)


# -- datagram encode/parse ----------------------------------------------------

def test_datagram_roundtrip():
    msg = parse_datagram(dg("keyed", seq=42))
    assert msg is not None
    assert msg["state"] == "keyed" and msg["seq"] == 42
    assert msg["station"] == "ROY-222-SSB" and msg["band"] == "222"


def test_datagram_rejects_garbage():
    for bad in (b"", b"not json", b"{}", b'{"wims_inhibit":2,"state":"keyed"}',
                b'{"wims_inhibit":1,"state":"launch"}',
                b'{"wims_inhibit":1,"state":"keyed","ttl_ms":5}',      # ttl too small
                b'{"wims_inhibit":1,"state":"keyed","ttl_ms":999999}', # ttl too big
                b"x" * 1000):                                          # oversize
        assert parse_datagram(bad) is None, bad[:40]
    g = InhibitGate()
    assert g.on_datagram(b"junk", 0.0) is False
    assert g.invalid == 1 and not g.inhibited(0.0)


# -- gate: two states, TTL deadman -------------------------------------------

def test_gate_default_open():
    g = InhibitGate()
    assert not g.inhibited(0.0)
    assert g.holding_stations(0.0) == []


def test_gate_keyed_then_clear():
    g = InhibitGate()
    assert g.on_datagram(dg("keyed"), 0.0) is True     # OPEN -> INHIBITED
    assert g.inhibited(0.1)
    assert g.holding_stations(0.1) == ["ROY-222-SSB"]
    assert g.on_datagram(dg("clear"), 0.2) is True     # INHIBITED -> OPEN, immediate
    assert not g.inhibited(0.2)
    assert g.expiries == 0                             # clean release, no alarm


def test_gate_ttl_deadman_expires_and_alarms():
    g = InhibitGate()
    g.on_datagram(dg("keyed", ttl_ms=600), 0.0)
    assert g.inhibited(0.59)                           # still armed just before ttl
    assert not g.inhibited(0.61)                       # deadman released
    assert g.expiries == 1                             # ...and counted as an alarm


def test_gate_keepalive_rearms_deadline():
    g = InhibitGate()
    g.on_datagram(dg("keyed"), 0.0)
    g.on_datagram(dg("keyed", seq=2), 0.5)             # keepalive at 0.5
    assert g.inhibited(1.0)                            # would have expired at 0.6
    assert not g.inhibited(1.2)                        # expires 0.5 + 0.6


def test_gate_two_stations_compose():
    # §4.3: clear from one station must not release the other's hold.
    g = InhibitGate()
    g.on_datagram(dg("keyed", station="A"), 0.0)
    assert g.on_datagram(dg("keyed", station="B"), 0.1) is False  # already inhibited
    assert g.on_datagram(dg("clear", station="A"), 0.2) is False  # B still holds
    assert g.inhibited(0.3) and g.holding_stations(0.3) == ["B"]
    assert g.on_datagram(dg("clear", station="B"), 0.4) is True
    assert not g.inhibited(0.4)


def test_gate_clear_for_unknown_station_is_noop():
    g = InhibitGate()
    assert g.on_datagram(dg("clear", station="NOBODY"), 0.0) is False
    assert not g.inhibited(0.0)


# -- key agent: immediate assert, keepalives, hang ---------------------------

def test_agent_assert_is_immediate():
    a = KeyAgentScheduler("ROY-222-SSB", "222")
    out = a.set_key(True, 0.0)
    assert len(out) == 1 and parse_datagram(out[0])["state"] == "keyed"
    assert a.set_key(True, 0.1) == []                  # level, not edge spam


def test_agent_keepalives_while_keyed():
    a = KeyAgentScheduler("S", "222", keepalive_s=0.2)
    a.set_key(True, 0.0)
    assert a.poll(0.1) == []                           # not due yet
    out = a.poll(0.21)
    assert len(out) == 1 and parse_datagram(out[0])["state"] == "keyed"
    assert a.poll(0.25) == [] and a.poll(0.42) != []   # steady 0.2 s cadence


def test_agent_hang_then_clear():
    a = KeyAgentScheduler("S", "222", hang_s=0.5, keepalive_s=0.2)
    a.set_key(True, 0.0)
    a.set_key(False, 1.0)                              # key up: hang starts
    kinds = []
    t = 1.0
    while a.holding:
        t += 0.05
        for d in a.poll(t):
            kinds.append(parse_datagram(d)["state"])
    assert kinds[-1] == "clear" and kinds.count("clear") == 1
    assert all(k == "keyed" for k in kinds[:-1])       # keepalives span the hang
    assert 1.49 < t < 1.56                             # clear at ~key-up + hang


def test_agent_rekey_during_hang_cancels_clear():
    # A CW string: gaps between elements shorter than hang never emit clear.
    a = KeyAgentScheduler("S", "222", hang_s=0.5, keepalive_s=0.2)
    sent = a.set_key(True, 0.0)
    t = 0.0
    for _ in range(20):                                # 20 dits: 40 ms on / 60 ms off
        t += 0.04
        sent += a.poll(t) + a.set_key(False, t)
        t += 0.06
        sent += a.poll(t) + a.set_key(True, t)
    states = [parse_datagram(d)["state"] for d in sent]
    assert "clear" not in states                       # one continuous hold
    a.set_key(False, t)
    while a.holding:
        t += 0.05
        sent += a.poll(t)
    assert parse_datagram(sent[-1])["state"] == "clear"


def test_agent_ttl_must_exceed_keepalive():
    try:
        KeyAgentScheduler("S", "222", keepalive_s=0.5, ttl_ms=600)
    except ValueError:
        pass
    else:
        raise AssertionError("ttl/keepalive validation missing")


# -- end-to-end (agent feeding gate, no transport) ---------------------------

def test_agent_drives_gate_through_cw_burst():
    a = KeyAgentScheduler("S", "222", hang_s=0.5, keepalive_s=0.2, ttl_ms=600)
    g = InhibitGate()

    def deliver(datagrams, now):
        for d in datagrams:
            g.on_datagram(d, now)

    deliver(a.set_key(True, 0.0), 0.0)
    assert g.inhibited(0.0)                            # asserted on first edge
    t = 0.0
    while t < 2.0:                                     # 2 s keyed with keepalives
        t += 0.05
        deliver(a.poll(t), t)
        assert g.inhibited(t), f"gate dropped mid-hold at {t:.2f}"
    deliver(a.set_key(False, t), t)
    while a.holding:                                   # hang window: still held
        t += 0.05
        deliver(a.poll(t), t)
    assert not g.inhibited(t)                          # released by clear, not ttl
    assert g.expiries == 0


def test_agent_death_releases_gate_by_deadman():
    a = KeyAgentScheduler("S", "222", ttl_ms=600)
    g = InhibitGate()
    for d in a.set_key(True, 0.0):
        g.on_datagram(d, 0.0)
    # agent dies here: no keepalives, no clear
    assert g.inhibited(0.5)
    assert not g.inhibited(0.7)                        # ttl 600 ms
    assert g.expiries == 1                             # alarmed, not silent


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
