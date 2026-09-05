# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Inhibit target discovery — Status band + InhibitStatus port."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.key.discovery import (  # noqa: E402
    BAND_STREAM_PORTS,
    InhibitTargetTable,
    stream_port_for_band,
)


def test_stream_ports():
    assert stream_port_for_band("2m") == 2237  # all bands → plane A 2237
    assert stream_port_for_band("6m") == 2237
    assert stream_port_for_band(None) is None
    assert set(BAND_STREAM_PORTS) >= {"6m", "2m", "1.25m", "70cm"}


def test_needs_both_status_and_inhibit_status():
    t = InhibitTargetTable(stale_s=60)
    t.on_status("A", "2m", "192.168.1.10", 1.0)
    assert t.targets_for_band("2m", 1.0) == []
    t.on_inhibit_status("A", 22372, "192.168.1.10", 1.1)
    got = t.targets_for_band("2m", 1.1)
    assert len(got) == 1
    assert got[0].host == "192.168.1.10" and got[0].inhibit_port == 22372
    assert got[0].instance_id == "A" and got[0].band == "2m"


def test_band_filter():
    t = InhibitTargetTable()
    t.on_status("A", "2m", "10.0.0.1", 0.0)
    t.on_inhibit_status("A", 22372, "10.0.0.1", 0.0)
    t.on_status("B", "6m", "10.0.0.2", 0.0)
    t.on_inhibit_status("B", 22372, "10.0.0.2", 0.0)
    assert [x.instance_id for x in t.targets_for_band("2m", 0.0)] == ["A"]
    assert [x.instance_id for x in t.targets_for_band("6m", 0.0)] == ["B"]
    assert t.targets_for_band(None, 0.0) == []


def test_stale_expiry():
    t = InhibitTargetTable(stale_s=10)
    t.on_status("A", "2m", "10.0.0.1", 0.0)
    t.on_inhibit_status("A", 22372, "10.0.0.1", 0.0)
    assert t.targets_for_band("2m", 5.0)
    assert not t.targets_for_band("2m", 11.0)
    assert t.sweep(11.0) == 1


def test_host_updates_from_either_message():
    t = InhibitTargetTable()
    t.on_status("A", "2m", "10.0.0.1", 0.0)
    t.on_inhibit_status("A", 22372, "10.0.0.9", 1.0)  # new source IP
    got = t.targets_for_band("2m", 1.0)
    assert got[0].host == "10.0.0.9"


def test_bad_port_ignored():
    t = InhibitTargetTable()
    t.on_status("A", "2m", "10.0.0.1", 0.0)
    t.on_inhibit_status("A", 0, "10.0.0.1", 0.0)
    assert t.targets_for_band("2m", 0.0) == []


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
