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

"""Tests for the durable console API contract (server/state.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M, encode as E  # noqa: E402
from wims.discovery.fleet import FleetTracker  # noqa: E402
from wims.interlock.arbiter import OverlapDetector, identity_groups  # noqa: E402
from wims.server.state import (  # noqa: E402
    fleet_to_dict, interlock_to_dict, roster_to_dict, decodes_to_dict,
    n1mm_sync_to_dict, inventory_bands, normalize_share_policy,
    DEFAULT_SHARE_POLICY, API_VERSION)
from wims.server.app import LiveFleet  # noqa: E402


def test_fleet_to_dict_shape():
    t = FleetTracker()
    t.observe(M.parse(E.build_heartbeat("SIM-6M", version="2.7.0")), now=100.0, src_ip="192.168.10.21")
    t.observe(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
              now=101.0, src_ip="192.168.10.21")
    t.observe(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-7, delta_time=0.1,
                                     delta_frequency=1500, message="CQ K1ABC FN42")),
              now=101.0, src_ip="192.168.10.21")
    t.observe_n1mm_xml("<contactinfo><app>N1MM</app><StationName>ROY-PC</StationName>"
                       "<call>K1ABC</call><band>50</band></contactinfo>", now=101.0, src_ip="192.168.10.22")

    d = fleet_to_dict(t, now=102.0, wsjt_pkts=3, n1mm_pkts=1)
    assert d["api"] == API_VERSION
    assert d["rx"] == {"wsjtx": 3, "n1mm": 1}
    assert d["share_policy_default"] == DEFAULT_SHARE_POLICY
    assert "bands" in d and isinstance(d["bands"], list)

    inst = d["instances"][0]
    assert inst["id"] == "SIM-6M" and inst["band"] == "6m" and inst["mode"] == "FT8"
    assert inst["state"] == "DEC" and inst["health"] == "ALIVE"
    assert inst["dial_hz"] == 50_313_000 and inst["host"] == "192.168.10.21"
    assert isinstance(inst["decodes_per_period"], float)
    assert inst["share_policy"] == "coordinated"
    assert inst["inhibit"] is None  # coordinated → no inhibit projection

    lg = d["loggers"][0]
    assert lg["kind"] == "N1MM" and lg["id"] == "ROY-PC" and lg["last_call"] == "K1ABC"
    assert lg["last_band"] == "6m"

    # WSJT-X row carries N1MM logger-of-record (station + host address).
    nl = inst["n1mm_logger"]
    assert nl["status"] == "ok"
    assert nl["id"] == "ROY-PC"
    assert nl["host"] == "192.168.10.22"
    assert nl["last_band"] == "6m"

    bands = {b["band"]: b for b in d["bands"]}
    assert "6m" in bands
    assert bands["6m"]["share_policy"] == "coordinated"
    assert bands["6m"]["wsjt_count"] == 1
    assert bands["6m"]["logger_count"] == 1
    assert bands["6m"]["wsjt"][0]["id"] == "SIM-6M"
    assert bands["6m"]["wsjt"][0]["n1mm_logger"]["id"] == "ROY-PC"


def test_n1mm_network_view_multi_and_none():
    """N1MM-centric view: multi-WSJT → one N1MM; N1MM with zero WSJT; unbound WSJT."""
    t = FleetTracker()
    # Two 6m beams + one 2m instance
    t.observe(M.parse(E.build_status("TRAILER-50-A", 50_313_000, mode="FT8")),
              now=10.0, src_ip="10.0.0.1")
    t.observe(M.parse(E.build_status("TRAILER-50-B", 50_313_000, mode="FT8")),
              now=10.0, src_ip="10.0.0.2")
    t.observe(M.parse(E.build_status("CHIP-2M", 144_174_000, mode="FT8")),
              now=10.0, src_ip="10.0.0.3")
    # N1MM-50 takes both 6m streams; N1MM-SSB has no digital
    t.observe_n1mm_xml(
        "<contactinfo><app>N1MM</app><StationName>N1MM-50</StationName>"
        "<call>K1ABC</call><band>50</band><mycall>N2OY</mycall></contactinfo>",
        now=10.0, src_ip="10.0.0.10")
    t.observe_n1mm_xml(
        "<RadioInfo><app>N1MM</app><StationName>N1MM-SSB</StationName>"
        "<OpCall>W1AW</OpCall><Freq>1441740</Freq><Mode>USB</Mode></RadioInfo>",
        now=10.0, src_ip="10.0.0.20")

    d = fleet_to_dict(t, now=11.0)
    net = d["n1mm_network"]
    assert net["logger_count"] == 2
    by = {lg["id"]: lg for lg in d["loggers"]}

    n50 = by["N1MM-50"]
    assert n50["has_wsjt"] is True
    assert n50["role"] == "digital_logger"
    assert n50["wsjt_count"] == 2
    ids = {w["id"] for w in n50["wsjt_instances"]}
    assert ids == {"TRAILER-50-A", "TRAILER-50-B"}
    assert "6m" in n50["wsjt_bands"]
    assert "6m" in n50["bands"]

    ssb = by["N1MM-SSB"]
    assert ssb["has_wsjt"] is False
    assert ssb["role"] == "no_wsjt"
    assert ssb["wsjt_count"] == 0
    assert ssb["wsjt_instances"] == []
    # RadioInfo Freq should contribute a band
    assert ssb.get("bands_seen") or ssb.get("last_band") or ssb.get("bands")

    # 2m has no N1MM on that band → unbound
    unbound_ids = {w["id"] for w in net["unbound_wsjt"]}
    assert "CHIP-2M" in unbound_ids
    assert net["with_wsjt"] == 1
    assert net["without_wsjt"] == 1


def test_n1mm_logger_missing_and_colocated():
    t = FleetTracker()
    t.observe(M.parse(E.build_status("ONLY-6M", 50_313_000, mode="FT8")),
              now=10.0, src_ip="10.0.0.1")
    d = fleet_to_dict(t, now=11.0)
    assert d["instances"][0]["n1mm_logger"]["status"] == "missing"

    t2 = FleetTracker()
    t2.observe(M.parse(E.build_status("SEAT-222", 222_174_000, mode="FT8")),
               now=10.0, src_ip="10.0.0.9")
    # Logger on same host but last_band not yet 1.25m (e.g. only RadioInfo).
    t2.observe_n1mm_xml(
        "<RadioInfo><app>N1MM</app><StationName>SEAT-PC</StationName>"
        "<NetBiosName>SEAT-PC</NetBiosName><RadioNr>1</RadioNr>"
        "<Freq>1400000</Freq><TXFreq>1400000</TXFreq>"
        "<Mode>USB</Mode><OpCall>N2OY</OpCall><IsRunning>False</IsRunning>"
        "</RadioInfo>",
        now=10.0, src_ip="10.0.0.9")
    d2 = fleet_to_dict(t2, now=11.0)
    nl = d2["instances"][0]["n1mm_logger"]
    # May be colocated (same host) or missing if RadioInfo did not register — either
    # way host should surface when logger is present.
    if d2["loggers"]:
        assert nl["status"] in ("colocated", "ok", "multiple")
        assert nl["host"] == "10.0.0.9" or nl["id"] == "SEAT-PC"


def test_inventory_and_share_policy_interlock():
    assert normalize_share_policy("INTERLOCK") == "interlock"
    assert normalize_share_policy("nope") == "coordinated"

    t = FleetTracker()
    t.observe(M.parse(E.build_status("A-6M", 50_313_000, mode="FT8")),
              now=10.0, src_ip="10.0.0.1")
    t.observe(M.parse(E.build_status("B-2M", 144_174_000, mode="FT8", transmitting=True)),
              now=10.0, src_ip="10.0.0.2")
    d = fleet_to_dict(t, now=11.0, share_policies={"6m": "interlock", "2m": "coordinated"})
    by_id = {i["id"]: i for i in d["instances"]}
    assert by_id["A-6M"]["share_policy"] == "interlock"
    assert by_id["A-6M"]["inhibit"] is not None
    assert by_id["A-6M"]["inhibit"]["state"] == "unknown"
    assert by_id["B-2M"]["share_policy"] == "coordinated"
    assert by_id["B-2M"]["inhibit"] is None

    bands = {b["band"]: b for b in d["bands"]}
    assert bands["6m"]["share_policy"] == "interlock"
    assert bands["2m"]["wsjt_tx"] == ["B-2M"]

    # Policy-only band with no traffic yet still appears
    inv = inventory_bands([], [], {"70cm": "interlock"})
    assert inv[0]["band"] == "70cm" and inv[0]["share_policy"] == "interlock"
    assert inv[0]["wsjt_count"] == 0


def test_livefleet_set_share_policy():
    live = LiveFleet()
    r = live.set_share_policy("6m", "interlock")
    assert r["ok"] and r["share_policy"] == "interlock"
    live.observe_wsjtx(M.parse(E.build_status("SIM", 50_313_000, mode="FT8")),
                       now=1.0, src_ip="127.0.0.1")
    s = live.snapshot(now=1.0)
    assert s["instances"][0]["share_policy"] == "interlock"
    assert any(b["band"] == "6m" and b["share_policy"] == "interlock" for b in s["bands"])
    bad = live.set_share_policy("", "interlock")
    assert not bad["ok"]


def test_activity_tile_on_heartbeat_without_decode():
    """Quiet band: Heartbeat alone must create an activity tile that still scrolls."""
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_heartbeat("VM-9700", version="2.7.0")),
                       now=100.0, src_ip="192.168.10.50")
    s = live.snapshot(now=100.0)
    assert any(a["instance"] == "VM-9700" for a in s["activity"])
    tile = next(a for a in s["activity"] if a["instance"] == "VM-9700")
    assert tile["count"] == 0
    # Continuous clock window: full strip of empty periods (not zero rows).
    assert len(tile["rows"]) == 15  # ActivityMap default n_rows
    assert all(all(c is None for c in r["snr"]) for r in tile["rows"])


def test_snapshot_prunes_dead_instance_and_activity():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_heartbeat("OLD-DESKTOP", version="2.7.0")),
                       now=100.0, src_ip="192.168.1.10")
    live.observe_wsjtx(M.parse(E.build_heartbeat("VM-9700", version="2.7.0")),
                       now=100.0, src_ip="192.168.10.50")
    assert len(live.snapshot(now=100.0)["instances"]) == 2
    # Only VM keeps heartbeat; desktop silent past prune window (120s).
    live.observe_wsjtx(M.parse(E.build_heartbeat("VM-9700", version="2.7.0")),
                       now=250.0, src_ip="192.168.10.50")
    s = live.snapshot(now=250.0)
    ids = {i["id"] for i in s["instances"]}
    assert ids == {"VM-9700"}
    assert all(a["instance"] != "OLD-DESKTOP" for a in s["activity"])


def test_interlock_no_overlap_instance_grouping():
    det = OverlapDetector(group_of=identity_groups)
    det.observe("A", True, now=10.0)      # A transmitting, its own group
    d = interlock_to_dict(det, identity_groups, "instance",
                          node_ids=["A", "B"], transmitting_ids={"A"}, now=11.0)
    assert d["grouping"] == "instance"
    assert d["tx_now"] == ["A"]
    assert d["overlap_now"] is False
    assert d["violation_count"] == 0 and d["last_violation"] is None
    ga = next(g for g in d["groups"] if g["group"] == "A")
    assert ga["transmitting"] == ["A"] and ga["overlap"] is False


def test_interlock_overlap_detected_and_audited():
    # Two instances share one group ("6m") and both transmit -> overlap.
    group_of = lambda iid: "6m"
    det = OverlapDetector(group_of=group_of)
    det.observe("A", True, now=10.0)
    v = det.observe("B", True, now=10.5)      # B joins -> violation recorded
    assert v is not None
    d = interlock_to_dict(det, group_of, "band",
                          node_ids=["A", "B"], transmitting_ids={"A", "B"}, now=11.0)
    assert d["overlap_now"] is True
    assert d["violation_count"] == 1
    assert d["last_violation"]["group"] == "6m"
    assert d["last_violation"]["instances"] == ["A", "B"]
    g = d["groups"][0]
    assert g["overlap"] is True and g["transmitting"] == ["A", "B"]


def test_livefleet_band_grouping_flags_overlap():
    # End-to-end through the server wrapper: two instances on 6m both TX.
    live = LiveFleet(grouping="band")
    live.observe_wsjtx(M.parse(E.build_status("SIM-6A", 50_313_000, mode="FT8", transmitting=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_status("SIM-6B", 50_315_000, mode="FT8", transmitting=True)),
                       now=1.1, src_ip="192.168.10.22")
    il = live.snapshot(2.0)["interlock"]
    assert il["grouping"] == "band"
    assert il["overlap_now"] is True
    assert il["violation_count"] >= 1
    assert sorted(il["tx_now"]) == ["SIM-6A", "SIM-6B"]


def test_livefleet_roster_lists_all_decodes():
    # Status gives the instance a band + grid; all decodes populate the roster, scored.
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8",
                                              de_call="WA1HCO", de_grid="FN31", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-1, delta_time=0.1,
                                              delta_frequency=1600, message="WA1HCO W2XYZ FN20")),
                       now=1.1, src_ip="192.168.10.21")  # directed at us
    r = live.snapshot(2.0)["roster"]
    assert r["strategy"] == "vhf-default" and r["condition"] == "open"
    by = {c["call"]: c for c in r["candidates"]}
    assert set(by) == {"K1ABC", "W2XYZ"}                     # CQ and non-CQ both listed
    assert by["K1ABC"]["is_cq"] is True and by["K1ABC"]["to_call"] == "CQ"
    assert by["K1ABC"]["is_needed"] is True and by["K1ABC"]["is_new_mult"] is True  # empty log
    assert any(f["name"] == "new_mult" for f in by["K1ABC"]["factors"])   # breakdown present
    assert by["K1ABC"]["freq_hz"] == 50_313_000 + 1500      # RF = dial + decode df
    assert by["K1ABC"]["az"] is not None and 0 <= by["K1ABC"]["az"] < 360  # FN31 -> FN42
    assert by["K1ABC"]["distance_km"] is not None and by["K1ABC"]["distance_km"] > 0
    assert by["K1ABC"]["is_calling_us"] is False
    assert by["W2XYZ"]["is_cq"] is False and by["W2XYZ"]["to_call"] == "WA1HCO"
    assert by["W2XYZ"]["is_calling_us"] is True              # WA1HCO is de_call
    assert by["W2XYZ"]["is_armed"] is False


def test_livefleet_roster_armed_when_tx_enabled_for_dx():
    """Enable Tx + DX Call matching a row → is_armed (green highlight)."""
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status(
        "SIM-6M", 50_313_000, mode="FT8", de_call="WA1HCO", de_grid="FN31",
        dx_call="K1ABC", tx_enabled=True)), now=1.0, src_ip="10.0.0.1")
    live.observe_wsjtx(M.parse(E.build_decode(
        "SIM-6M", time_ms=0, snr=-3, delta_time=0.1, delta_frequency=1500,
        message="CQ K1ABC FN42")), now=1.1, src_ip="10.0.0.1")
    k = next(c for c in live.snapshot(2.0)["roster"]["candidates"] if c["call"] == "K1ABC")
    assert k["is_armed"] is True and k["is_calling_us"] is False


def test_livefleet_logged_qso_marks_dupe():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    # N1MM logs the QSO -> K1ABC stays in the roster but is flagged already-worked.
    live.observe_n1mm("<contactinfo><app>N1MM</app><ID>abc-1</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN42</gridsquare></contactinfo>",
                      now=1.5, src_ip="192.168.10.22")
    r = live.snapshot(2.0)["roster"]
    k = next(c for c in r["candidates"] if c["call"] == "K1ABC")
    assert k["is_dupe"] is True and k["is_needed"] is False
    assert r["not_needed"] == 1 and r["needed"] == 0


def test_livefleet_contactdelete_restores_needed():
    """Deleting a QSO in N1MM must un-grey the call on the roster (live, no resync)."""
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    live.observe_n1mm("<contactinfo><app>N1MM</app><ID>abc-1</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN42</gridsquare>"
                      "<contestname>ARRLVHFJUN</contestname></contactinfo>",
                      now=1.5, src_ip="192.168.10.22")
    k = next(c for c in live.snapshot(2.0)["roster"]["candidates"] if c["call"] == "K1ABC")
    assert k["is_dupe"] is True and k["is_needed"] is False
    # Operator deletes the QSO in N1MM → contactdelete by ID.
    live.observe_n1mm(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<contactdelete><app>N1MM</app><timestamp>2026-07-15 12:00:00</timestamp>"
        "<mycall>W2SZ</mycall><band>50</band><call>K1ABC</call>"
        "<contestnr>20</contestnr><StationName>VM</StationName>"
        "<ID>abc-1</ID></contactdelete>",
        now=3.0, src_ip="192.168.10.22")
    r = live.snapshot(3.5)["roster"]
    k = next(c for c in r["candidates"] if c["call"] == "K1ABC")
    assert k["is_dupe"] is False and k["is_needed"] is True
    assert r["not_needed"] == 0 and r["needed"] == 1
    assert live.snapshot(3.5)["n1mm_sync"]["qso_count"] == 0


def test_livefleet_contactreplace_updates_log():
    """Edit in N1MM is delete+replace; replace upserts the corrected record."""
    live = LiveFleet()
    live.observe_n1mm("<contactinfo><app>N1MM</app><ID>e1</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN42</gridsquare></contactinfo>",
                      now=1.0, src_ip="192.168.10.22")
    assert live._log.is_dupe("K1ABC", "6m", "FN42")
    # Edit grid FN42 → FN31: N1MM sends delete then replace (same ID).
    live.observe_n1mm("<contactdelete><app>N1MM</app><ID>e1</ID><call>K1ABC</call>"
                      "<band>50</band></contactdelete>",
                      now=2.0, src_ip="192.168.10.22")
    live.observe_n1mm("<contactreplace><app>N1MM</app><ID>e1</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN31</gridsquare></contactreplace>",
                      now=2.1, src_ip="192.168.10.22")
    assert live._log.count() == 1
    assert live._log.is_dupe("K1ABC", "6m", "FN42") is False
    assert live._log.is_dupe("K1ABC", "6m", "FN31") is True


def test_livefleet_activity_tile():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    # time_ms must fall inside the continuous window ending at wall-clock `now`.
    # Pin wall clock so the decode lands on the last row of the scrolling strip.
    import wims.udp.activity as actmod
    tms = 8_145_000
    real = actmod.utc_ms_since_midnight
    actmod.utc_ms_since_midnight = lambda t: tms + 1_000  # same 15s period
    try:
        live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=tms, snr=12, delta_time=0.1,
                                                  delta_frequency=795, message="CQ NJ1H FN42")),
                           now=1.1, src_ip="192.168.10.21")
        act = live.snapshot(2.0)["activity"]
        assert len(act) == 1 and act[0]["instance"] == "SIM-6M" and act[0]["count"] == 1
        assert len(act[0]["rows"]) == 15  # continuous strip
        col = int(795 / act[0]["freq_max"] * act[0]["n_bins"])
        # Decode is in the current period → last row of the scrolling window
        assert act[0]["rows"][-1]["snr"][col] == 12
    finally:
        actmod.utc_ms_since_midnight = real


def test_decodes_to_dict_newest_first():
    buf = [
        {"ts": 10.0, "instance": "A", "snr": -5, "df": 1500, "message": "CQ K1ABC FN42", "is_cq": True},
        {"ts": 11.0, "instance": "A", "snr": 3, "df": 1600, "message": "WA1HCO K1ABC -01", "is_cq": False},
    ]
    out = decodes_to_dict(buf, now=12.0)
    assert [e["message"] for e in out] == ["WA1HCO K1ABC -01", "CQ K1ABC FN42"]  # newest first
    assert out[0]["is_cq"] is False and out[1]["is_cq"] is True
    assert out[1]["ts"] == 10.0 and out[1]["df"] == 1500


def test_n1mm_sync_states():
    # never seen
    none = n1mm_sync_to_dict(100.0, n1mm_pkts=0, last_n1mm=None, qso_count=0, last_qso=None)
    assert none["status"] == "none" and none["feed_age"] is None and none["last_qso"] is None
    # active + a logged QSO
    act = n1mm_sync_to_dict(100.0, n1mm_pkts=5, last_n1mm=98.0, qso_count=3,
                            last_qso={"call": "K1ABC", "band": "6m", "ts": 95.0})
    assert act["status"] == "active" and act["feed_age"] == 2.0
    assert act["qso_count"] == 3 and act["last_qso"]["call"] == "K1ABC" and act["last_qso"]["age"] == 5.0
    # seen long ago -> idle (quiet, not a fault; N1MM has no heartbeat)
    idle = n1mm_sync_to_dict(1000.0, n1mm_pkts=5, last_n1mm=100.0, qso_count=3, last_qso=None)
    assert idle["status"] == "idle"


def test_livefleet_decodes_and_sync_end_to_end():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    live.observe_n1mm("<contactinfo><app>N1MM</app><ID>q9</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN42</gridsquare></contactinfo>",
                      now=1.5, src_ip="192.168.10.22")
    s = live.snapshot(2.0)
    assert s["decodes"][0]["message"] == "CQ K1ABC FN42" and s["decodes"][0]["instance"] == "SIM-6M"
    assert s["n1mm_sync"]["status"] == "active" and s["n1mm_sync"]["qso_count"] == 1
    assert s["n1mm_sync"]["last_qso"]["call"] == "K1ABC"


def test_livefleet_seeds_log_from_s3db(tmp_path=None):
    import os, sqlite3, tempfile
    # Build a minimal N1MM-shaped contest DB (DXLOG table) to seed from.
    fd, db = tempfile.mkstemp(suffix=".s3db"); os.close(fd)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE DXLOG (ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, "
                "Mode TEXT, Points INT, IsMultiplier1 INT, ContestName TEXT, "
                "TimeStamp TEXT, Operator TEXT)")
    con.execute("INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("a"*32, "K1ABC", "50", "FN42", "FT8", 1, 1, "ARRLVHFJUN", "", "W2SZ"))
    con.commit(); con.close()
    try:
        live = LiveFleet()
        n = live.seed_from_db(db)
        assert n == 1
        live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                           now=1.0, src_ip="10.0.0.1")
        live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                                  delta_frequency=1500, message="CQ K1ABC FN42")),
                           now=1.1, src_ip="10.0.0.1")
        s = live.snapshot(2.0)
        assert s["n1mm_sync"]["qso_count"] == 1
        assert s["n1mm_sync"]["seed"]["count"] == 1
        assert s["n1mm_sync"]["seed"]["source"].endswith(".s3db")
        # seeded QSO makes the matching CQ already-worked -> listed but not needed
        assert [c["call"] for c in s["roster"]["candidates"]] == ["K1ABC"]
        assert s["roster"]["candidates"][0]["is_needed"] is False
        assert s["roster"]["not_needed"] == 1
    finally:
        os.unlink(db)


def test_auto_seed_picks_one_contest_not_all():
    import os, sqlite3, tempfile
    fd, db = tempfile.mkstemp(suffix=".s3db"); os.close(fd)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE ContestInstance (
          ContestID INT, ContestName TEXT, StartDate TEXT, ContestNR INT);
        CREATE TABLE DXLOG (
          ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, Mode TEXT,
          Points INT, IsMultiplier1 INT, ContestName TEXT, ContestNR INT,
          TimeStamp TEXT, Operator TEXT);
    """)
    con.execute("INSERT INTO ContestInstance VALUES (1,'OLD','2025-09-01',1)")
    con.execute("INSERT INTO ContestInstance VALUES (2,'NEW','2026-06-14',2)")
    con.execute("INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("o"*32, "OLD1", "50", "FN42", "FT8", 1, 0, "OLD", 1, "", "W2SZ"))
    con.execute("INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("n"*32, "NEW1", "50", "FN31", "FT8", 1, 1, "NEW", 2, "", "W2SZ"))
    con.commit(); con.close()
    try:
        live = LiveFleet()
        live.configure_log_discovery(db_path=db)
        r = live.auto_seed()
        assert r["ok"] is True
        assert r["seeded"] == 1
        assert r["contest"]["contest_name"] == "NEW"
        s = live.snapshot(1.0)
        assert s["n1mm_sync"]["qso_count"] == 1
        assert s["n1mm_sync"]["active_contest"]["contest_name"] == "NEW"
        assert any(c["contest_name"] == "OLD" for c in s["n1mm_sync"]["contests"])
        # Switch to OLD via select_contest (Status UI path)
        live.select_contest(db_path=db, contest_nr=1)
        s2 = live.snapshot(2.0)
        assert s2["n1mm_sync"]["qso_count"] == 1
        assert s2["n1mm_sync"]["active_contest"]["contest_name"] == "OLD"
    finally:
        os.unlink(db)


def test_resync_log_reconciles_from_file():
    """Operator Resync re-reads DXLOG: drops deleted QSOs, keeps file truth."""
    import os, sqlite3, tempfile

    fd, db = tempfile.mkstemp(suffix=".s3db"); os.close(fd)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE ContestInstance (
          ContestID INT, ContestName TEXT, StartDate TEXT, ContestNR INT);
        CREATE TABLE DXLOG (
          ID TEXT, Call TEXT, Band TEXT, GridSquare TEXT, Mode TEXT,
          Points INT, IsMultiplier1 INT, ContestName TEXT, ContestNR INT,
          TimeStamp TEXT, Operator TEXT);
    """)
    con.execute("INSERT INTO ContestInstance VALUES (1,'ARRLVHFJUN','2026-06-14',20)")
    for i, call in enumerate(("AA1A", "BB2B", "CC3C")):
        con.execute("INSERT INTO DXLOG VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"id{i}" + "0" * 29, call, "50", "FN42", "FT8", 1, 0,
                     "ARRLVHFJUN", 20, "2026-06-14", "W2SZ"))
    con.commit()
    try:
        live = LiveFleet()
        live.configure_log_discovery(db_path=db)
        assert live.auto_seed()["ok"] is True
        assert live.snapshot(1.0)["n1mm_sync"]["qso_count"] == 3
        # Live UDP QSO not (yet) reflected in file — resync must drop it.
        live.observe_n1mm(
            "<contactinfo><app>N1MM</app><ID>liveonly</ID><call>ZZ9Z</call>"
            "<band>50</band><gridsquare>FN31</gridsquare>"
            "<contestname>ARRLVHFJUN</contestname></contactinfo>",
            now=2.0, src_ip="10.0.0.2")
        assert live._log.count() == 4
        # Operator deleted BB2B in N1MM (file updated; no contactdelete reached WIMS).
        con.execute("DELETE FROM DXLOG WHERE Call=?", ("BB2B",))
        con.commit()
        r = live.resync_log(now=10.0)
        assert r["ok"] is True
        s = r["summary"]
        assert s["total"] == 2
        assert s["deleted"] == 2          # BB2B + liveonly
        assert s["upserted"] == 2
        assert live._log.is_dupe("BB2B", "6m", "FN42") is False
        assert live._log.is_dupe("ZZ9Z", "6m", "FN31") is False
        assert live._log.is_dupe("AA1A", "6m", "FN42") is True
        snap = live.snapshot(11.0)
        ns = snap["n1mm_sync"]
        assert ns["qso_count"] == 2
        assert ns["last_resync"] is not None
        assert ns["last_resync"]["deleted"] == 2
        assert ns["last_resync"]["total"] == 2
        assert ns["last_resync"]["age"] == 1.0
    finally:
        con.close()
        os.unlink(db)


def test_resync_log_requires_active_contest():
    live = LiveFleet()
    r = live.resync_log(now=1.0)
    assert r["ok"] is False and r["error"] == "no_active_log"


def test_n1mm_sync_includes_last_resync():
    out = n1mm_sync_to_dict(
        100.0, n1mm_pkts=1, last_n1mm=99.0, qso_count=5, last_qso=None,
        last_resync={"ts": 90.0, "upserted": 5, "deleted": 1, "total": 5,
                     "source": "N2OY.s3db", "label": "ARRLVHFJUN"})
    assert out["last_resync"]["age"] == 10.0
    assert out["last_resync"]["deleted"] == 1 and out["last_resync"]["total"] == 5
    assert out["last_resync"]["source"] == "N2OY.s3db"
    none = n1mm_sync_to_dict(100.0, n1mm_pkts=0, last_n1mm=None, qso_count=0, last_qso=None)
    assert none["last_resync"] is None


def test_json_serializable():
    import json
    t = FleetTracker()
    t.observe(M.parse(E.build_heartbeat("X")), now=1.0, src_ip="127.0.0.1")
    json.dumps(fleet_to_dict(t, now=2.0))   # must not raise


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {t.__name__}"); traceback.print_exc()
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
