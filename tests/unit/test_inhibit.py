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

"""TX-inhibit gate + Key-agent scheduler — type-18 / lease proofs."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.interlock.inhibit import (  # noqa: E402
    ADAPTIVE_HANG_MAX_S,
    ADAPTIVE_HANG_MIN_S,
    LONG_HANG_S,
    NM_MAGIC,
    NM_SCHEMA,
    NM_TX_INHIBIT,
    InhibitGate,
    KeyAgentScheduler,
    adaptive_hang_s,
    encode_tx_inhibit,
    parse_datagram,
)


def hold(controller_id="ROY-SSB", ttl_ms=600, station="ROY-222-SSB", target_id=""):
    return encode_tx_inhibit(controller_id, ttl_ms, station=station, target_id=target_id)


def release(controller_id="ROY-SSB", station="ROY-222-SSB"):
    return encode_tx_inhibit(controller_id, 0, station=station)


def state_of(data):
    return "release" if parse_datagram(data)["ttl_ms"] == 0 else "hold"


# -- datagram encode/parse ----------------------------------------------------

def test_datagram_roundtrip():
    msg = parse_datagram(hold(controller_id="CTRL-A", station="Badge",
                              target_id="INST-1", ttl_ms=600))
    assert msg is not None
    assert msg["ttl_ms"] == 600
    assert msg["controller_id"] == "CTRL-A"
    assert msg["station"] == "Badge"
    assert msg["target_id"] == "INST-1"


def test_datagram_golden_header():
    raw = encode_tx_inhibit("C1", 600, station="S", target_id="")
    magic, schema, mtype = struct.unpack_from(">III", raw, 0)
    assert (magic, schema, mtype) == (NM_MAGIC, NM_SCHEMA, NM_TX_INHIBIT)
    assert parse_datagram(raw)["controller_id"] == "C1"


def test_datagram_rejects_garbage():
    for bad in (b"", b"not json", b"{}",
                b'{"tx_inhibit":1,"ttl_ms":600,"station":"X","band":"222","seq":1}',
                b"x" * 1000,
                struct.pack(">III", NM_MAGIC, NM_SCHEMA, 17) + b"\x00" * 20,
                ):
        assert parse_datagram(bad) is None, bad[:40]
    # Empty controller_id rejected at encode and parse.
    try:
        encode_tx_inhibit("", 600)
    except ValueError:
        pass
    else:
        raise AssertionError("empty controller_id should raise")
    # Manually craft type-18 with empty controller_id.
    body = struct.pack(">III", NM_MAGIC, NM_SCHEMA, NM_TX_INHIBIT)
    body += struct.pack(">I", 0)  # target_id empty
    body += struct.pack(">I", 0)  # controller_id empty — invalid
    body += struct.pack(">I", 600)
    body += struct.pack(">I", 0)  # station empty
    assert parse_datagram(body) is None
    g = InhibitGate()
    assert g.on_datagram(b"junk", 0.0) is False
    assert g.invalid == 1 and not g.inhibited(0.0)


def test_datagram_rejects_bad_ttl():
    for ttl in (5, 999999):
        try:
            encode_tx_inhibit("C", ttl)
        except ValueError:
            pass
        else:
            raise AssertionError(f"ttl {ttl} should raise")


# -- gate: leases, OR, TTL deadman -------------------------------------------

def test_gate_default_open():
    g = InhibitGate()
    assert not g.inhibited(0.0)
    assert g.holding_station(0.0) == ""
    assert g.live_controllers(0.0) == []


def test_gate_hold_then_release():
    g = InhibitGate()
    assert g.on_datagram(hold(), 0.0) is True
    assert g.inhibited(0.1)
    assert g.holding_station(0.1) == "ROY-222-SSB"
    assert g.on_datagram(release(), 0.2) is True
    assert not g.inhibited(0.2)
    assert g.expiries == 0


def test_gate_ttl_deadman_expires_and_alarms():
    g = InhibitGate()
    g.on_datagram(hold(ttl_ms=600), 0.0)
    assert g.inhibited(0.59)
    assert not g.inhibited(0.61)
    assert g.expiries == 1


def test_gate_keepalive_rearms_deadline():
    g = InhibitGate()
    g.on_datagram(hold(), 0.0)
    g.on_datagram(hold(), 0.5)
    assert g.inhibited(1.0)
    assert not g.inhibited(1.2)


def test_gate_multi_controller_or():
    g = InhibitGate()
    g.on_datagram(hold(controller_id="A", station="SSB"), 0.0)
    assert g.on_datagram(hold(controller_id="B", station="CW"), 0.1) is False
    assert g.inhibited(0.1)
    assert g.live_controllers(0.1) == ["A", "B"]
    assert g.holding_station(0.1) == "SSB, CW"
    # Release A only — B still holds.
    assert g.on_datagram(release(controller_id="A", station="SSB"), 0.2) is False
    assert g.inhibited(0.2)
    assert g.live_controllers(0.2) == ["B"]
    assert g.holding_station(0.2) == "CW"
    assert g.on_datagram(release(controller_id="B", station="CW"), 0.3) is True
    assert not g.inhibited(0.3)


def test_gate_release_other_controller_is_noop_on_foreign_lease():
    g = InhibitGate()
    g.on_datagram(hold(controller_id="A", station="A"), 0.0)
    # B was never holding — release B must not clear A.
    assert g.on_datagram(release(controller_id="B"), 0.1) is False
    assert g.inhibited(0.1)
    assert g.live_controllers(0.1) == ["A"]


def test_gate_release_when_open_is_noop():
    g = InhibitGate()
    assert g.on_datagram(release(controller_id="NOBODY"), 0.0) is False
    assert not g.inhibited(0.0)


def test_gate_json_counts_invalid():
    g = InhibitGate()
    old = b'{"tx_inhibit":1,"ttl_ms":600,"station":"X","band":"222","seq":1}'
    assert g.on_datagram(old, 0.0) is False
    assert g.invalid == 1 and not g.inhibited(0.0)


# -- key agent: immediate assert, keepalives, hang ---------------------------

def test_agent_assert_is_immediate():
    a = KeyAgentScheduler("ROY-SSB", station="ROY-222-SSB")
    out = a.set_key(True, 0.0)
    assert len(out) == 1 and state_of(out[0]) == "hold"
    msg = parse_datagram(out[0])
    assert msg["controller_id"] == "ROY-SSB" and msg["station"] == "ROY-222-SSB"
    assert a.set_key(True, 0.1) == []


def test_agent_keepalives_while_keyed():
    a = KeyAgentScheduler("S", keepalive_s=0.2)
    a.set_key(True, 0.0)
    assert a.poll(0.1) == []
    out = a.poll(0.21)
    assert len(out) == 1 and state_of(out[0]) == "hold"
    assert a.poll(0.25) == [] and a.poll(0.42) != []


def test_agent_hang_then_release():
    a = KeyAgentScheduler("S", hang_s=0.5, keepalive_s=0.2)
    a.set_key(True, 0.0)
    a.set_key(False, 1.0)
    kinds = []
    t = 1.0
    while a.holding:
        t += 0.05
        for d in a.poll(t):
            kinds.append(state_of(d))
    assert kinds[-1] == "release" and kinds.count("release") == 1
    assert all(k == "hold" for k in kinds[:-1])
    assert 1.49 < t < 1.56


def test_agent_rekey_during_hang_cancels_release():
    a = KeyAgentScheduler("S", hang_s=0.5, keepalive_s=0.2)
    sent = a.set_key(True, 0.0)
    t = 0.0
    for _ in range(20):
        t += 0.04
        sent += a.poll(t) + a.set_key(False, t)
        t += 0.06
        sent += a.poll(t) + a.set_key(True, t)
    states = [state_of(d) for d in sent]
    assert "release" not in states
    a.set_key(False, t)
    while a.holding:
        t += 0.05
        sent += a.poll(t)
    assert state_of(sent[-1]) == "release"


def test_agent_ttl_must_exceed_keepalive():
    try:
        KeyAgentScheduler("S", keepalive_s=0.5, ttl_ms=600)
    except ValueError:
        pass
    else:
        raise AssertionError("ttl/keepalive validation missing")


def test_agent_requires_controller_id():
    try:
        KeyAgentScheduler("")
    except ValueError:
        pass
    else:
        raise AssertionError("empty controller_id should raise")


# -- end-to-end (agent feeding gate, no transport) ---------------------------

def test_agent_drives_gate_through_cw_burst():
    a = KeyAgentScheduler("S", hang_s=0.5, keepalive_s=0.2, ttl_ms=600)
    g = InhibitGate()

    def deliver(datagrams, now):
        for d in datagrams:
            g.on_datagram(d, now)

    deliver(a.set_key(True, 0.0), 0.0)
    assert g.inhibited(0.0)
    t = 0.0
    while t < 2.0:
        t += 0.05
        deliver(a.poll(t), t)
        assert g.inhibited(t), f"gate dropped mid-hold at {t:.2f}"
    deliver(a.set_key(False, t), t)
    while a.holding:
        t += 0.05
        deliver(a.poll(t), t)
    assert not g.inhibited(t)
    assert g.expiries == 0


def test_agent_death_releases_gate_by_deadman():
    a = KeyAgentScheduler("S", ttl_ms=600)
    g = InhibitGate()
    for d in a.set_key(True, 0.0):
        g.on_datagram(d, 0.0)
    assert g.inhibited(0.5)
    assert not g.inhibited(0.7)
    assert g.expiries == 1


def test_two_agents_or_on_one_gate():
    a = KeyAgentScheduler("SSB", station="ROY-SSB", hang_s=0.0, ttl_ms=600)
    b = KeyAgentScheduler("CW", station="ROY-CW", hang_s=0.0, ttl_ms=600)
    g = InhibitGate()
    for d in a.set_key(True, 0.0):
        g.on_datagram(d, 0.0)
    for d in b.set_key(True, 0.1):
        g.on_datagram(d, 0.1)
    assert g.live_controllers(0.1) == ["CW", "SSB"]
    # SSB key-up with hang 0 → immediate release; CW still holding.
    for d in a.set_key(False, 0.2):
        g.on_datagram(d, 0.2)
    for d in a.poll(0.2):
        g.on_datagram(d, 0.2)
    assert g.inhibited(0.2) and g.live_controllers(0.2) == ["CW"]
    for d in b.set_key(False, 0.3):
        g.on_datagram(d, 0.3)
    for d in b.poll(0.3):
        g.on_datagram(d, 0.3)
    assert not g.inhibited(0.3)


# -- adaptive hang classifier -------------------------------------------------

def _send_cw(a, t, dit, units_seq):
    for units in units_seq:
        a.set_key(True, t)
        t += units * dit
        a.set_key(False, t)
        t += dit
    return t - dit


def test_adaptive_function_direct():
    assert adaptive_hang_s([]) == (LONG_HANG_S, "long")
    assert adaptive_hang_s([2.0]) == (LONG_HANG_S, "long")
    # 20 WPM dit = 0.06 → 10.5 × 0.06 = 0.63
    assert adaptive_hang_s([0.06, 0.18, 0.06]) == (0.63, "cw")
    assert adaptive_hang_s([0.06, 2.0]) == (LONG_HANG_S, "long")


def test_adaptive_ssb_burst_releases_immediately():
    a = KeyAgentScheduler("S")
    a.set_key(True, 0.0)
    a.set_key(False, 2.0)
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S
    states = [state_of(d) for d in a.poll(2.0)]
    assert states == ["release"]
    assert not a.holding


def test_adaptive_hang_tracks_cw_speed():
    # 10.5 × dit: 15 WPM → 0.84, 20 → 0.63, 30 → 0.42
    for wpm, want in ((15, 0.84), (20, 0.63), (30, 0.42)):
        dit = 1.2 / wpm
        a = KeyAgentScheduler("S")
        _send_cw(a, 0.0, dit, (1, 3, 1, 1, 3, 1))
        assert a.hang_mode == "cw", wpm
        assert abs(a.last_hang_s - want) < 1e-9, (wpm, a.last_hang_s, want)


def test_adaptive_hang_covers_word_gap():
    # 7-dit inter-word gap must never emit clear (10.5-dit hang > 7-dit gap).
    dit = 0.06
    a = KeyAgentScheduler("S")
    sent = []
    t = _send_cw(a, 0.0, dit, (1, 1, 3, 1))
    for _ in range(7):
        t += dit
        sent += a.poll(t)
    a.set_key(True, t)
    states = [state_of(d) for d in sent]
    assert "release" not in states and a.holding


def test_adaptive_midlength_closure_is_not_cw():
    assert adaptive_hang_s([0.4]) == (LONG_HANG_S, "long")
    a = KeyAgentScheduler("S")
    a.set_key(True, 0.0)
    a.set_key(False, 0.4)
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S


def test_adaptive_hang_clamps():
    a = KeyAgentScheduler("S")
    a.set_key(True, 0.0)
    a.set_key(False, 0.022)
    assert a.last_hang_s == ADAPTIVE_HANG_MIN_S
    a = KeyAgentScheduler("S")
    a.set_key(True, 0.0)
    a.set_key(False, 0.14)
    assert a.last_hang_s == ADAPTIVE_HANG_MAX_S


def test_adaptive_mode_flips_cw_to_ssb_and_back():
    a = KeyAgentScheduler("S")
    t = _send_cw(a, 0.0, 0.06, (1, 3, 1))
    assert a.hang_mode == "cw"
    a.set_key(True, t + 1.0)
    a.set_key(False, t + 3.0)
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S
    _send_cw(a, t + 4.0, 0.06, (1, 1))
    assert a.hang_mode == "cw" and abs(a.last_hang_s - 0.63) < 1e-9


def test_adaptive_debounce_ignores_bounce_glitch():
    a = KeyAgentScheduler("S")
    _send_cw(a, 0.0, 0.06, (1, 3, 1))
    a.set_key(True, 10.0)
    a.set_key(False, 10.005)
    assert abs(a.last_hang_s - 0.63) < 1e-9


def test_manual_hang_override_disables_classifier():
    a = KeyAgentScheduler("S", hang_s=2.0)
    _send_cw(a, 0.0, 0.04, (1, 3, 1, 1))
    assert a.hang_mode == "manual" and a.last_hang_s == 2.0
    a.set_key(True, 5.0)
    a.set_key(False, 8.0)
    assert a.hang_mode == "manual" and a.last_hang_s == 2.0


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
