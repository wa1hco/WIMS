"""Tests for the durable console API contract (server/state.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M, encode as E  # noqa: E402
from wims.discovery.fleet import FleetTracker  # noqa: E402
from wims.interlock.arbiter import OverlapDetector, identity_groups  # noqa: E402
from wims.server.state import (  # noqa: E402
    fleet_to_dict, interlock_to_dict, roster_to_dict, decodes_to_dict,
    n1mm_sync_to_dict, API_VERSION)
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

    inst = d["instances"][0]
    assert inst["id"] == "SIM-6M" and inst["band"] == "6m" and inst["mode"] == "FT8"
    assert inst["state"] == "DEC" and inst["health"] == "ALIVE"
    assert inst["dial_hz"] == 50_313_000 and inst["host"] == "192.168.10.21"
    assert isinstance(inst["decodes_per_period"], float)

    lg = d["loggers"][0]
    assert lg["kind"] == "N1MM" and lg["id"] == "ROY-PC" and lg["last_call"] == "K1ABC"
    assert lg["last_band"] == "6m"


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


def test_livefleet_roster_ranks_cq_decodes():
    # Status gives the instance a band; CQ decodes then populate a scored roster.
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-1, delta_time=0.1,
                                              delta_frequency=1600, message="WA1HCO W2XYZ FN20")),
                       now=1.1, src_ip="192.168.10.21")  # not a CQ -> excluded from roster
    r = live.snapshot(2.0)["roster"]
    assert r["strategy"] == "vhf-default" and r["condition"] == "open"
    assert [c["call"] for c in r["candidates"]] == ["K1ABC"]
    top = r["candidates"][0]
    assert top["band"] == "6m" and top["is_new_mult"] is True   # empty log -> new mult
    assert any(f["name"] == "new_mult" for f in top["factors"])  # breakdown is present


def test_livefleet_logged_qso_marks_dupe():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-3, delta_time=0.1,
                                              delta_frequency=1500, message="CQ K1ABC FN42")),
                       now=1.1, src_ip="192.168.10.21")
    # N1MM logs the QSO -> roster must drop K1ABC as a dupe.
    live.observe_n1mm("<contactinfo><app>N1MM</app><ID>abc-1</ID><call>K1ABC</call>"
                      "<band>50</band><gridsquare>FN42</gridsquare></contactinfo>",
                      now=1.5, src_ip="192.168.10.22")
    r = live.snapshot(2.0)["roster"]
    assert [c["call"] for c in r["candidates"]] == []
    assert r["excluded"] == 1


def test_livefleet_activity_tile():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status("SIM-6M", 50_313_000, mode="FT8", decoding=True)),
                       now=1.0, src_ip="192.168.10.21")
    live.observe_wsjtx(M.parse(E.build_decode("SIM-6M", time_ms=8_145_000, snr=12, delta_time=0.1,
                                              delta_frequency=795, message="CQ NJ1H FN42")),
                       now=1.1, src_ip="192.168.10.21")
    act = live.snapshot(2.0)["activity"]
    assert len(act) == 1 and act[0]["instance"] == "SIM-6M" and act[0]["count"] == 1
    row = act[0]["rows"][0]
    col = int(795 / act[0]["freq_max"] * act[0]["n_bins"])
    assert row["snr"][col] == 12


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
        # seeded QSO makes the matching CQ a dupe -> excluded from the roster
        assert [c["call"] for c in s["roster"]["candidates"]] == []
        assert s["roster"]["excluded"] == 1
    finally:
        os.unlink(db)


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
