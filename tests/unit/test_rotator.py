# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rotator dialect, sim, registry, roster Az ant / Δaz (plan §2.10 / §3.8)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.geo import delta_az  # noqa: E402
from wims.integrations.rotator import yaesu_gs232 as Y  # noqa: E402
from wims.integrations.rotator.sim import SimRotator  # noqa: E402
from wims.integrations.rotator.registry import RotatorRegistry  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402


def test_delta_az_shortest_arc():
    assert delta_az(10, 20) == 10
    assert delta_az(350, 10) == 20
    assert delta_az(0, 180) == 180
    assert delta_az(None, 90) is None


def test_yaesu_commands_and_parse():
    assert Y.cmd_move_az(45) == b"M045\r"
    assert Y.cmd_stop() == b"A\r"
    az, el = Y.parse_position(b"AZ=123 EL=10")
    assert az == 123 and el == 10
    az2, el2 = Y.parse_position("+0045")
    assert az2 == 45 and el2 is None


def test_sim_slews_toward_target():
    s = SimRotator(az=0, rate_dps=90, settle_tol=1)
    s.move_az(90)
    time.sleep(0.05)
    az, _ = s.read()
    assert 0 < az <= 90
    # Fast-forward by many steps
    for _ in range(50):
        time.sleep(0.02)
        s.read()
        if not s.moving:
            break
    assert abs(s.read()[0] - 90) < 2


def test_registry_point_and_instance_map():
    reg = RotatorRegistry()
    reg.ensure_sim("ROT-6M", az=0, instances=["SIM-6M"])
    r = reg.point("ROT-6M", 120)
    assert r["ok"] and r["az"] == 120
    st = reg.for_instance("SIM-6M")
    assert st is not None and st.target_az == 120
    reg.tick_sims()
    assert st.moving or abs((st.az or 0) - 120) < 5


def test_registry_soft_clamp():
    reg = RotatorRegistry()
    reg.ensure_sim("R", az=0, soft_min=30, soft_max=90)
    r = reg.point("R", 10)
    assert r["ok"] and r["az"] == 30 and r.get("clamped")


def test_agent_report_ingests_rotator():
    reg = RotatorRegistry()
    n = reg.ingest_report([{
        "id": "ROT-A", "az": 200, "moving": False, "link_ok": True,
        "instances": ["WSJT-X"], "health": "OK",
    }], agent_id="seat-1")
    assert n == 1
    st = reg.for_instance("WSJT-X")
    assert st and st.az == 200 and st.agent_id == "seat-1"


def test_livefleet_roster_az_ant_and_point_api():
    live = LiveFleet()
    live._rotators.ensure_sim("ROT-6M", az=30, instances=["SIM-6M"])
    now = time.time()
    live.observe_wsjtx(M.parse(E.build_status(
        "SIM-6M", 50_313_000, mode="FT8", de_call="WA1HCO", de_grid="FN31")),
        now, "10.0.0.1", 50000)
    live.observe_wsjtx(M.parse(E.build_decode(
        "SIM-6M", time_ms=0, snr=-5, delta_time=0.1, delta_frequency=1500,
        message="CQ K1ABC FN42")), now, "10.0.0.1", 50000)
    snap = live.snapshot(now)
    assert snap["rotators"] and snap["rotators"][0]["id"] == "ROT-6M"
    row = next(c for c in snap["roster"]["candidates"] if c["call"] == "K1ABC")
    assert row["az"] is not None
    assert row["az_ant"] == 30
    assert row["delta_az"] is not None
    assert row["rotator_id"] == "ROT-6M"
    r = live.point_rotator(row_id=row["id"])
    assert r["ok"] and r["rotator"] == "ROT-6M"
    r2 = live.stop_rotator("ROT-6M")
    assert r2["ok"] and "ROT-6M" in r2["halted"]


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
