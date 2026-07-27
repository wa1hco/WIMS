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

"""Server TX control — click-to-work Reply (GT2-style, no global arm), panic Halt,
arbiter release, CQ gate, and the read-only (--no-tx) path (plan §3.2 / §2.12).
No sockets: a fake controller records what would be sent."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.server.app import LiveFleet  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402

MID = "RIG-20M"


class _FakeTx:
    def __init__(self):
        self.dest = ("127.0.0.1", 2237)
        self.sent = []
        self.last_dests = None

    def reply(self, inst, decode, *, modifiers=0, dests=None):
        self.last_dests = dests
        self.sent.append(("reply", inst, decode.message))

    def configure(self, inst, *, dx_call, dx_grid="", rx_df=None,
                  generate_messages=True, mode="", schema=2, dests=None):
        self.last_dests = dests
        self.sent.append(("configure", inst, dx_call, dx_grid, generate_messages))

    def halt(self, inst, *, auto_only=False, dests=None):
        self.last_dests = dests
        self.sent.append(("halt", inst))


# Simulated MessageClient ephemeral control port (not the UDP Server port).
CTRL_PORT = 54321


def _fleet_with_cq_decode():
    """LiveFleet seeded with one instance and one CQ roster row; returns (live, tx, row_id)."""
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, mode="FT8",
                       de_call="WA1HCO", de_grid="FN42")), now, "127.0.0.1", CTRL_PORT)
    live.observe_wsjtx(M.parse(E.build_decode(MID, time_ms=1000, snr=-8, delta_time=0.2,
                       delta_frequency=1500, message="CQ K1ABC FN31")),
                       now, "127.0.0.1", CTRL_PORT)
    row_id = live.snapshot(now)["roster"]["candidates"][0]["id"]
    return live, tx, row_id


def test_row_id_round_trips_to_entry():
    live, _tx, row_id = _fleet_with_cq_decode()
    assert row_id == f"{MID}|K1ABC|FN31"
    assert live._roster.entry_for(row_id) is not None
    assert live._roster.entry_for("no|such|row") is None


def test_hf_band_derivation():
    # 14.074 MHz must read as 20m — solo tester is not VHF-only.
    _live, _tx, row_id = _fleet_with_cq_decode()
    assert row_id.endswith("|K1ABC|FN31")  # built, and:
    assert _live.snapshot(time.time())["roster"]["candidates"][0]["band"] == "20m"


def test_work_sends_reply_without_arm():
    """Roster click is the human gate — no Enable TX master switch (GT2-style)."""
    live, tx, row_id = _fleet_with_cq_decode()
    r = live.work_station(row_id)
    assert r["ok"] and r["sent"] == "reply" and r["call"] == "K1ABC"
    assert r.get("auto_tx_eligible") is True
    assert r.get("dest")  # control destination echoed for UI diagnostics
    # Unicast to MessageClient ephemeral source first — not UDP Server :2237.
    assert tx.last_dests and tx.last_dests[0] == ("127.0.0.1", CTRL_PORT)
    assert tx.sent[-1] == ("reply", MID, "CQ K1ABC FN31")   # exact echo of the decode
    # CQ path must not need Configure.
    assert not any(s[0] == "configure" for s in tx.sent)


def test_work_non_cq_sends_reply_and_configure():
    """Mid-exchange: Reply alone often leaves DX blank; Configure fills call/grid."""
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, mode="FT8",
                       de_call="WA1HCO", de_grid="FN42")), now, "127.0.0.1", CTRL_PORT)
    live.observe_wsjtx(M.parse(E.build_decode(
        MID, time_ms=1000, snr=-5, delta_time=0.1, delta_frequency=1200,
        message="W9XYZ K1ABC R-12")), now, "127.0.0.1", CTRL_PORT)
    row_id = live.snapshot(now)["roster"]["candidates"][0]["id"]
    r = live.work_station(row_id)
    assert r["ok"] and r["call"] == "K1ABC"
    assert r.get("auto_tx_eligible") is False
    assert "configure" in r["sent"]
    kinds = [s[0] for s in tx.sent]
    assert "reply" in kinds and "configure" in kinds
    conf = next(s for s in tx.sent if s[0] == "configure")
    assert conf[1] == MID and conf[2] == "K1ABC"


def test_work_prefers_instance_source_host_for_reply():
    """Multi-host: Reply must go to the VM's MessageClient (ip + ephemeral port)."""
    live, tx, row_id = _fleet_with_cq_decode()
    # Re-observe from a "VM" address with a new ephemeral control port.
    now = time.time()
    vm_port = 61234
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, mode="FT8")),
                       now, "192.168.1.50", vm_port)
    r = live.work_station(row_id)
    assert r["ok"]
    assert ("192.168.1.50", vm_port) in (r.get("dests") or [])
    assert tx.last_dests[0] == ("192.168.1.50", vm_port)
    # Must NOT prefer the UDP Server port as the primary control dest.
    assert tx.last_dests[0][1] != 2237


def test_snapshot_tx_block_can_tx_when_enabled():
    live, _tx, row_id = _fleet_with_cq_decode()
    tx0 = live.snapshot(time.time())["tx"]
    assert tx0["enabled"] and tx0["can_tx"]
    assert "armed" not in tx0
    live.work_station(row_id)
    tx1 = live.snapshot(time.time())["tx"]
    assert tx1["can_tx"] and tx1["holders"].get(MID) == MID


def test_arbiter_releases_on_tx_to_rx_edge():
    live, _tx, row_id = _fleet_with_cq_decode()
    live.work_station(row_id)
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, transmitting=True)), now, "127.0.0.1")
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, transmitting=False)), now, "127.0.0.1")
    assert live.snapshot(now)["tx"]["holders"] == {}


def test_halt_always_available():
    live, tx, _row_id = _fleet_with_cq_decode()
    r = live.halt()
    assert r["ok"] and MID in r["halted"]
    assert any(s[0] == "halt" for s in tx.sent)


def test_work_unknown_row():
    live, _tx, _row_id = _fleet_with_cq_decode()
    r = live.work_station("no|such|row")
    assert r["ok"] is False and r["error"] == "unknown_row"


def test_qsy_drops_other_band_roster_rows():
    """Status dial change (20m→6m) removes old-band rows so they cannot be Worked."""
    live, tx, row_id = _fleet_with_cq_decode()
    assert live._roster.entry_for(row_id) is not None
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 50_313_000, mode="FT8")),
                       now, "127.0.0.1", CTRL_PORT)
    assert live._roster.entry_for(row_id) is None
    r = live.work_station(row_id)
    assert r["ok"] is False and r["error"] == "unknown_row"


def test_same_band_status_does_not_drop_roster():
    """Heartbeat/Status churn on the same band must not clear the roster."""
    live, _tx, row_id = _fleet_with_cq_decode()
    now = time.time()
    for i in range(5):
        live.observe_wsjtx(M.parse(E.build_status(
            MID, 14_074_000, mode="FT8", transmitting=bool(i % 2))),
            now + i, "127.0.0.1", CTRL_PORT)
    assert live._roster.entry_for(row_id) is not None
    assert live.snapshot(now + 10)["roster"]["count"] >= 1


def test_decode_before_status_survives_first_status():
    """Decode tagged band '?' then Status must reband, not wipe."""
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    # Decode first (no Status yet → band "?")
    live.observe_wsjtx(M.parse(E.build_decode(
        MID, time_ms=1000, snr=-8, delta_time=0.2, delta_frequency=1500,
        message="CQ K1ABC FN31")), now, "127.0.0.1", CTRL_PORT)
    e = live._roster.entry_for(f"{MID}|K1ABC|FN31")
    assert e is not None and e.band == "?"
    live.observe_wsjtx(M.parse(E.build_status(
        MID, 50_313_000, mode="FT8", de_call="WA1HCO", de_grid="FN42")),
        now + 1, "127.0.0.1", CTRL_PORT)
    e2 = live._roster.entry_for(f"{MID}|K1ABC|FN31")
    assert e2 is not None and e2.band == "6m"


def test_dual_host_same_id_does_not_qsy_wipe():
    """Two VMs both using id 'WSJT-X' on 6m and 2m must not thrash the roster."""
    live = LiveFleet()
    now = time.time()
    mid = "WSJT-X"
    # Host A = 6m
    live.observe_wsjtx(M.parse(E.build_status(mid, 50_313_000, mode="FT8")),
                       now, "192.168.1.10", 50001)
    live.observe_wsjtx(M.parse(E.build_decode(
        mid, time_ms=0, snr=-5, delta_time=0.1, delta_frequency=1000,
        message="CQ K1SIX FN42")), now + 0.1, "192.168.1.10", 50001)
    # Host B = 2m (same UDP id — common misconfig)
    live.observe_wsjtx(M.parse(E.build_status(mid, 144_174_000, mode="FT8")),
                       now + 0.2, "192.168.1.20", 50002)
    live.observe_wsjtx(M.parse(E.build_decode(
        mid, time_ms=0, snr=-3, delta_time=0.1, delta_frequency=1100,
        message="CQ K1TWO FN31")), now + 0.3, "192.168.1.20", 50002)
    # Alternate Status again (would have been continuous false QSY)
    live.observe_wsjtx(M.parse(E.build_status(mid, 50_313_000, mode="FT8")),
                       now + 0.4, "192.168.1.10", 50001)
    live.observe_wsjtx(M.parse(E.build_status(mid, 144_174_000, mode="FT8")),
                       now + 0.5, "192.168.1.20", 50002)
    # Both decodes still present
    assert live._roster.entry_for(f"{mid}|K1SIX|FN42") is not None
    assert live._roster.entry_for(f"{mid}|K1TWO|FN31") is not None
    n = live._tracker.nodes[mid]
    assert n.id_collision_at(now + 0.5)


def test_work_refuses_band_mismatch():
    """Hard gate: refuse Reply if row band ≠ instance band (safety net if row remains)."""
    live, tx, row_id = _fleet_with_cq_decode()  # 20m row
    n = live._tracker.nodes[MID]
    n.band = "6m"
    n.dial_hz = 50_313_000
    r = live.work_station(row_id)
    assert r["ok"] is False and r["error"] == "band_mismatch"
    assert r.get("band_row") == "20m" and r.get("band_now") == "6m"
    assert tx.sent == []


def test_work_refuses_dial_mismatch():
    """Same band label but dial moved >3 kHz → refuse (wrong RF footprint)."""
    live, tx, row_id = _fleet_with_cq_decode()  # dial 14.074
    n = live._tracker.nodes[MID]
    n.dial_hz = 14_090_000  # still 20m, far from decode dial
    r = live.work_station(row_id)
    assert r["ok"] is False and r["error"] == "dial_mismatch"
    assert tx.sent == []


def test_cq_is_gated_off_by_default():
    live, _tx, _row_id = _fleet_with_cq_decode()
    assert live.call_cq()["error"] == "cq_not_supported_yet"


def test_no_tx_path_is_read_only():
    live = LiveFleet(tx_controller=None)
    assert live.work_station("x")["error"] == "tx_disabled"
    assert live.halt()["error"] == "tx_disabled"
    assert live.snapshot(time.time())["tx"]["enabled"] is False
    assert live.snapshot(time.time())["tx"]["can_tx"] is False


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
