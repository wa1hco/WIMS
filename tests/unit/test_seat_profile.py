# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""H2 seat-profile.json load/save and config checks."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.config.seat_profile import (  # noqa: E402
    load_seat_profile,
    save_seat_profile_marks,
)


def test_missing_file_defaults_tx_capable():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "seat-profile.json"
        prof = load_seat_profile(p)
        assert prof.exists is False
        assert prof.tx_capable("ANY") is True
        assert prof.rf_path("ANY") is None
        checks = prof.checks()
        assert checks and checks[0]["code"] == "no_profile"


def test_load_marks_and_unset_true():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "seat-profile.json"
        p.write_text(json.dumps({
            "station_class": "shared_trx_dual_rx",
            "wsjt_instances": [
                {"id": "HOME-FT8", "rf_path": "trx", "tx_capable": True},
                {"id": "HOME-SUB", "rf_path": "sdr_rx", "tx_capable": False},
                {"id": "LEGACY"},  # unset → true
            ],
            "transceiver": {"rig_model": "IC-9700"},
        }), encoding="utf-8")
        prof = load_seat_profile(p)
        assert prof.exists is True
        assert prof.station_class == "shared_trx_dual_rx"
        assert prof.tx_capable("HOME-FT8") is True
        assert prof.tx_capable("HOME-SUB") is False
        assert prof.tx_capable("LEGACY") is True
        assert prof.tx_capable("UNKNOWN") is True
        assert prof.rf_path("HOME-SUB") == "sdr_rx"
        assert prof.raw.get("transceiver", {}).get("rig_model") == "IC-9700"


def test_shared_trx_checks_exactly_one_tx():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "seat-profile.json"
        save_seat_profile_marks(
            path=p,
            station_class="shared_trx_dual_rx",
            instances=[
                {"id": "A", "tx_capable": True},
                {"id": "B", "tx_capable": True},
            ],
            clear_missing=True,
        )
        codes = {c["code"] for c in load_seat_profile(p).checks()}
        assert "many_tx_capable" in codes

        save_seat_profile_marks(
            path=p,
            station_class="shared_trx_dual_rx",
            instances=[
                {"id": "A", "tx_capable": False},
                {"id": "B", "tx_capable": False},
            ],
            clear_missing=True,
        )
        codes = {c["code"] for c in load_seat_profile(p).checks()}
        assert "no_tx_capable" in codes

        save_seat_profile_marks(
            path=p,
            station_class="shared_trx_dual_rx",
            instances=[
                {"id": "A", "tx_capable": True, "rf_path": "trx"},
                {"id": "B", "tx_capable": False, "rf_path": "sdr_rx"},
            ],
            clear_missing=True,
        )
        codes = {c["code"] for c in load_seat_profile(p).checks()}
        assert "one_tx_capable" in codes
        assert "many_tx_capable" not in codes
        assert "no_tx_capable" not in codes


def test_save_preserves_unknown_keys():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "seat-profile.json"
        p.write_text(json.dumps({
            "station_class": "shared_trx_second_rx",
            "cat_dwell_s": 0.5,
            "wsjt_instances": [
                {"id": "TX", "tx_capable": True, "modes": ["FT8"]},
            ],
        }), encoding="utf-8")
        save_seat_profile_marks(
            path=p,
            station_class="shared_trx_second_rx",
            instances=[
                {"id": "TX", "tx_capable": True},
                {"id": "SDR", "tx_capable": False},
            ],
            clear_missing=True,
        )
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["cat_dwell_s"] == 0.5
        ids = {e["id"]: e["tx_capable"] for e in raw["wsjt_instances"]}
        assert ids == {"TX": True, "SDR": False}
        assert any(e["id"] == "SDR" and e.get("rf_path") == "sdr_rx"
                   for e in raw["wsjt_instances"])


def test_example_file_loads():
    root = Path(__file__).resolve().parents[2]
    example = root / "examples" / "seat-profile-home-dual-rx.json"
    assert example.is_file()
    prof = load_seat_profile(example)
    assert prof.station_class == "shared_trx_dual_rx"
    assert prof.tx_capable("HOME-FT8") is True
    assert prof.tx_capable("HOME-SUB") is False
    codes = {c["code"] for c in prof.checks()}
    assert "one_tx_capable" in codes


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
