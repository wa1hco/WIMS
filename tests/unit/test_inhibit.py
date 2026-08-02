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
    ADAPTIVE_HANG_MAX_S,
    ADAPTIVE_HANG_MIN_S,
    LONG_HANG_S,
    InhibitGate,
    KeyAgentScheduler,
    adaptive_hang_s,
    encode_datagram,
    parse_datagram,
)


def hold(station="ROY-222-SSB", band="222", seq=1, ttl_ms=600):
    """A hold datagram: "inhibit this band for ttl_ms"."""
    return encode_datagram(station, band, seq, ttl_ms)


def release(station="ROY-222-SSB", band="222", seq=1):
    """The release: the same message with ttl 0."""
    return encode_datagram(station, band, seq, 0)


def state_of(data):
    """Interpret a datagram the way the gate does: ttl 0 = release."""
    return "release" if parse_datagram(data)["ttl_ms"] == 0 else "hold"


# -- datagram encode/parse ----------------------------------------------------

def test_datagram_roundtrip():
    msg = parse_datagram(hold(seq=42))
    assert msg is not None
    assert msg["ttl_ms"] == 600 and msg["seq"] == 42
    assert msg["station"] == "ROY-222-SSB" and msg["band"] == "222"


def test_datagram_rejects_garbage():
    for bad in (b"", b"not json", b"{}", b'{"tx_inhibit":2,"ttl_ms":600}',
                b'{"tx_inhibit":1}',                       # ttl_ms missing
                b'{"tx_inhibit":1,"ttl_ms":5}',            # nonzero but under min
                b'{"tx_inhibit":1,"ttl_ms":999999}',       # over max
                b'{"tx_inhibit":1,"ttl_ms":"600"}',        # wrong type
                b'{"tx_inhibit":1,"ttl_ms":true}',         # bool is not an int here
                b"x" * 1000):                              # oversize
        assert parse_datagram(bad) is None, bad[:40]
    g = InhibitGate()
    assert g.on_datagram(b"junk", 0.0) is False
    assert g.invalid == 1 and not g.inhibited(0.0)


# -- gate: two states, TTL deadman -------------------------------------------

def test_gate_default_open():
    g = InhibitGate()
    assert not g.inhibited(0.0)
    assert g.holding_station(0.0) == ""


def test_gate_hold_then_release():
    g = InhibitGate()
    assert g.on_datagram(hold(), 0.0) is True     # OPEN -> INHIBITED
    assert g.inhibited(0.1)
    assert g.holding_station(0.1) == "ROY-222-SSB"
    assert g.on_datagram(release(), 0.2) is True     # INHIBITED -> OPEN, immediate
    assert not g.inhibited(0.2)
    assert g.expiries == 0                             # clean release, no alarm


def test_gate_ttl_deadman_expires_and_alarms():
    g = InhibitGate()
    g.on_datagram(hold(ttl_ms=600), 0.0)
    assert g.inhibited(0.59)                           # still armed just before ttl
    assert not g.inhibited(0.61)                       # deadman released
    assert g.expiries == 1                             # ...and counted as an alarm


def test_gate_keepalive_rearms_deadline():
    g = InhibitGate()
    g.on_datagram(hold(), 0.0)
    g.on_datagram(hold(seq=2), 0.5)             # keepalive at 0.5
    assert g.inhibited(1.0)                            # would have expired at 0.6
    assert not g.inhibited(1.2)                        # expires 0.5 + 0.6


def test_gate_single_hold_last_writer_wins():
    # 2026-08-02: the gate tracks ONE hold — arbitration among multiple
    # SSB/CW stations is out of scope for WSJT-X (SSB/CW side's job, e.g.
    # OR-ed KEY lines). Last hold names the holder; any valid release opens.
    g = InhibitGate()
    g.on_datagram(hold(station="A"), 0.0)
    assert g.on_datagram(hold(station="B"), 0.1) is False  # still inhibited
    assert g.holding_station(0.1) == "B"                   # last writer wins
    assert g.on_datagram(release(station="A"), 0.2) is True  # any release opens
    assert not g.inhibited(0.3)


def test_gate_release_when_open_is_noop():
    g = InhibitGate()
    assert g.on_datagram(release(station="NOBODY"), 0.0) is False
    assert not g.inhibited(0.0)


# -- key agent: immediate assert, keepalives, hang ---------------------------

def test_agent_assert_is_immediate():
    a = KeyAgentScheduler("ROY-222-SSB", "222")
    out = a.set_key(True, 0.0)
    assert len(out) == 1 and state_of(out[0]) == "hold"
    assert a.set_key(True, 0.1) == []                  # level, not edge spam


def test_agent_keepalives_while_keyed():
    a = KeyAgentScheduler("S", "222", keepalive_s=0.2)
    a.set_key(True, 0.0)
    assert a.poll(0.1) == []                           # not due yet
    out = a.poll(0.21)
    assert len(out) == 1 and state_of(out[0]) == "hold"
    assert a.poll(0.25) == [] and a.poll(0.42) != []   # steady 0.2 s cadence


def test_agent_hang_then_release():
    a = KeyAgentScheduler("S", "222", hang_s=0.5, keepalive_s=0.2)
    a.set_key(True, 0.0)
    a.set_key(False, 1.0)                              # key up: hang starts
    kinds = []
    t = 1.0
    while a.holding:
        t += 0.05
        for d in a.poll(t):
            kinds.append(state_of(d))
    assert kinds[-1] == "release" and kinds.count("release") == 1
    assert all(k == "hold" for k in kinds[:-1])       # keepalives span the hang
    assert 1.49 < t < 1.56                             # clear at ~key-up + hang


def test_agent_rekey_during_hang_cancels_release():
    # A CW string: gaps between elements shorter than hang never emit clear.
    a = KeyAgentScheduler("S", "222", hang_s=0.5, keepalive_s=0.2)
    sent = a.set_key(True, 0.0)
    t = 0.0
    for _ in range(20):                                # 20 dits: 40 ms on / 60 ms off
        t += 0.04
        sent += a.poll(t) + a.set_key(False, t)
        t += 0.06
        sent += a.poll(t) + a.set_key(True, t)
    states = [state_of(d) for d in sent]
    assert "release" not in states                       # one continuous hold
    a.set_key(False, t)
    while a.holding:
        t += 0.05
        sent += a.poll(t)
    assert state_of(sent[-1]) == "release"


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


# -- adaptive hang classifier (§3) --------------------------------------------

def _send_cw(a, t, dit, units_seq):
    """Key one CW element per entry of units_seq (1=dit, 3=dah), inter-element
    gap of one dit. Returns the time of the final key-up."""
    for units in units_seq:
        a.set_key(True, t)
        t += units * dit
        a.set_key(False, t)
        t += dit
    return t - dit                                     # time of last key-up


def test_adaptive_function_direct():
    assert adaptive_hang_s([]) == (LONG_HANG_S, "long")
    assert adaptive_hang_s([2.0]) == (LONG_HANG_S, "long")          # SSB over
    assert adaptive_hang_s([0.06, 0.18, 0.06]) == (0.48, "cw")         # 20 WPM
    assert adaptive_hang_s([0.06, 2.0]) == (LONG_HANG_S, "long")    # latest wins


def test_adaptive_ssb_burst_releases_after_debounce():
    a = KeyAgentScheduler("S", "222")                  # no hang_s -> adaptive
    a.set_key(True, 0.0)
    a.set_key(False, 2.0)                              # one 2 s PTT over
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S
    t, states = 2.0, []
    while a.holding:
        t += 0.02
        states += [state_of(d) for d in a.poll(t)]
    assert states[-1] == "release"
    assert 2.01 < t < 2.06                             # keyup + 20 ms debounce


def test_adaptive_hang_tracks_cw_speed():
    # 8 x dit: 15 WPM -> 0.64 s, 20 -> 0.48 s, 30 -> 0.32 s (§3 sizing rule).
    for wpm, want in ((15, 0.64), (20, 0.48), (30, 0.32)):
        dit = 1.2 / wpm
        a = KeyAgentScheduler("S", "222")
        _send_cw(a, 0.0, dit, (1, 3, 1, 1, 3, 1))      # mixed dits and dahs
        assert a.hang_mode == "cw", wpm
        assert abs(a.last_hang_s - want) < 1e-9, (wpm, a.last_hang_s)


def test_adaptive_hang_covers_word_gap():
    # The 7-dit inter-word gap must never emit clear (8-dit hang > 7-dit gap).
    dit = 0.06                                         # 20 WPM
    a = KeyAgentScheduler("S", "222")
    sent = []
    t = _send_cw(a, 0.0, dit, (1, 1, 3, 1))            # first word
    for _ in range(7):                                 # poll across the 7-dit gap
        t += dit
        sent += a.poll(t)
    a.set_key(True, t)                                 # second word begins
    states = [state_of(d) for d in sent]
    assert "release" not in states and a.holding         # one continuous hold


def test_adaptive_midlength_closure_is_not_cw():
    # Keyboard-bench regression (2026-08-02): a ~0.4 s press is neither a
    # dit nor a rig-hung over; it must get the debounce, not a clamped
    # 1 s "3 WPM CW" hang.
    assert adaptive_hang_s([0.4]) == (LONG_HANG_S, "long")
    a = KeyAgentScheduler("S", "222")
    a.set_key(True, 0.0)
    a.set_key(False, 0.4)
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S


def test_adaptive_hang_clamps():
    a = KeyAgentScheduler("S", "222")
    a.set_key(True, 0.0)
    a.set_key(False, 0.022)                            # absurdly fast (~55 WPM)
    assert a.last_hang_s == ADAPTIVE_HANG_MIN_S        # floor, not 0.176
    a = KeyAgentScheduler("S", "222")
    a.set_key(True, 0.0)
    a.set_key(False, 0.14)                             # very slow CW (~8 WPM dit)
    assert a.last_hang_s == ADAPTIVE_HANG_MAX_S        # ceiling, not 1.12


def test_adaptive_mode_flips_cw_to_ssb_and_back():
    a = KeyAgentScheduler("S", "222")
    t = _send_cw(a, 0.0, 0.06, (1, 3, 1))
    assert a.hang_mode == "cw"
    a.set_key(True, t + 1.0)
    a.set_key(False, t + 3.0)                          # op grabs the SSB mic
    assert a.hang_mode == "long" and a.last_hang_s == LONG_HANG_S
    _send_cw(a, t + 4.0, 0.06, (1, 1))                 # back on the key
    assert a.hang_mode == "cw" and abs(a.last_hang_s - 0.48) < 1e-9


def test_adaptive_debounce_ignores_bounce_glitch():
    a = KeyAgentScheduler("S", "222")
    _send_cw(a, 0.0, 0.06, (1, 3, 1))                  # honest 20 WPM
    a.set_key(True, 10.0)
    a.set_key(False, 10.005)                           # 5 ms contact bounce
    assert abs(a.last_hang_s - 0.48) < 1e-9            # estimate unpoisoned


def test_manual_hang_override_disables_classifier():
    a = KeyAgentScheduler("S", "222", hang_s=2.0)
    _send_cw(a, 0.0, 0.04, (1, 3, 1, 1))               # 30 WPM traffic
    assert a.hang_mode == "manual" and a.last_hang_s == 2.0
    a.set_key(True, 5.0)
    a.set_key(False, 8.0)                              # long SSB-style closure
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
