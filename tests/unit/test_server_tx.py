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

"""Server TX control — arm gating, click-to-work Reply, panic Halt, arbiter release,
CQ gate, and the read-only (--no-tx) path (plan §3.2 / §4.5). No sockets: a fake
controller records what would be sent."""

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

    def reply(self, inst, decode, *, modifiers=0):
        self.sent.append(("reply", inst, decode.message))

    def halt(self, inst, *, auto_only=False):
        self.sent.append(("halt", inst))


def _fleet_with_cq_decode():
    """LiveFleet seeded with one instance and one CQ roster row; returns (live, tx, row_id)."""
    tx = _FakeTx()
    live = LiveFleet(tx_controller=tx)
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, mode="FT8",
                       de_call="WA1HCO", de_grid="FN42")), now, "127.0.0.1")
    live.observe_wsjtx(M.parse(E.build_decode(MID, time_ms=1000, snr=-8, delta_time=0.2,
                       delta_frequency=1500, message="CQ K1ABC FN31")), now, "127.0.0.1")
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


def test_work_refused_while_disarmed():
    live, tx, row_id = _fleet_with_cq_decode()
    assert live.work_station(row_id) == {"ok": False, "error": "disarmed"}
    assert tx.sent == []                      # fail-safe: nothing transmitted


def test_work_sends_reply_when_armed():
    live, tx, row_id = _fleet_with_cq_decode()
    assert live.arm(True) == {"ok": True, "armed": True}
    r = live.work_station(row_id)
    assert r["ok"] and r["sent"] == "reply" and r["call"] == "K1ABC"
    assert tx.sent[-1] == ("reply", MID, "CQ K1ABC FN31")   # exact echo of the decode


def test_snapshot_tx_block_reflects_arm_and_holder():
    live, _tx, row_id = _fleet_with_cq_decode()
    tx0 = live.snapshot(time.time())["tx"]
    assert tx0["enabled"] and not tx0["armed"] and not tx0["can_tx"]
    live.arm(True)
    live.work_station(row_id)
    tx1 = live.snapshot(time.time())["tx"]
    assert tx1["can_tx"] and tx1["holders"].get(MID) == MID


def test_arbiter_releases_on_tx_to_rx_edge():
    live, _tx, row_id = _fleet_with_cq_decode()
    live.arm(True)
    live.work_station(row_id)
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, transmitting=True)), now, "127.0.0.1")
    live.observe_wsjtx(M.parse(E.build_status(MID, 14074000, transmitting=False)), now, "127.0.0.1")
    assert live.snapshot(now)["tx"]["holders"] == {}


def test_halt_allowed_even_while_disarmed():
    live, tx, _row_id = _fleet_with_cq_decode()
    live.arm(False)
    r = live.halt()
    assert r["ok"] and MID in r["halted"]
    assert any(s[0] == "halt" for s in tx.sent)


def test_work_unknown_row_when_armed():
    live, _tx, _row_id = _fleet_with_cq_decode()
    live.arm(True)
    assert live.work_station("no|such|row") == {"ok": False, "error": "unknown_row"}


def test_cq_is_gated_off_by_default():
    live, _tx, _row_id = _fleet_with_cq_decode()
    assert live.call_cq()["error"] == "cq_not_supported_yet"


def test_no_tx_path_is_read_only():
    live = LiveFleet(tx_controller=None)
    assert live.work_station("x")["error"] == "tx_disabled"
    assert live.halt()["error"] == "tx_disabled"
    assert live.snapshot(time.time())["tx"]["enabled"] is False


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
