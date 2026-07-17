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

"""Tests for the decode-activity map, fed by real captured decodes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp.activity import ActivityMap, snr_glyph  # noqa: E402

# Real decode captured live: "CQ NJ1H FN42" @ 795 Hz, +20 dB.
DECODES = [
    "adbccbda00000002000000020000000657534a542d5801007c4868000000143f"
    "c99999a00000000000031b000000017e0000000c4351204e4a314820464e34320000",
]


def _decode(hexstr):
    return M.parse(bytes.fromhex(hexstr.replace(" ", "")))


def test_bin_and_bucket_math():
    a = ActivityMap("X", period_s=15, freq_max=3000, n_bins=50)
    assert a.bin_of(0) == 0
    assert a.bin_of(3000) == 49          # clamped to last bin
    assert a.bin_of(795) == 13           # 795/3000*50
    assert a.bucket_of(8_145_000) == 543  # time_ms // 15000


def test_glyphs_monotonic():
    assert snr_glyph(None) == " "
    assert snr_glyph(-24) == "."
    assert snr_glyph(20) == "@"
    # stronger SNR never maps to a "weaker" glyph
    order = ".:-=+*#@"
    idxs = [order.index(snr_glyph(s)) for s in range(-24, 25, 3)]
    assert idxs == sorted(idxs)


def test_real_decode_recorded():
    d = _decode(DECODES[0])
    assert isinstance(d, M.Decode)
    a = ActivityMap(d.id or "?")
    a.add(d)
    assert a.count == 1
    # SNR +20 lands in the strongest glyph at the 795 Hz column.
    bucket = a.bucket_of(d.time_ms)
    col = a.bin_of(d.delta_frequency)
    assert a._rows[bucket][col] == 20
    rendered = a.render()
    assert "@" in rendered
    assert "1 decodes" in rendered


def test_keeps_best_snr_per_cell():
    d = _decode(DECODES[0])  # df 795, snr 20
    a = ActivityMap("X")
    a.add(d)
    # Same cell, weaker signal must not overwrite the stronger one.
    d2 = _decode(DECODES[0])
    d2.snr = -5
    a.add(d2)
    assert a._rows[a.bucket_of(d.time_ms)][a.bin_of(d.delta_frequency)] == 20
    assert a.count == 2


def test_recent_rows_and_state_dict():
    from wims.server.state import activity_to_dict
    d = _decode(DECODES[0])           # df 795, snr 20
    a = ActivityMap(d.id or "?")
    a.add(d)
    # Without now: only stored (non-empty) buckets — offline/legacy path.
    rows = a.recent_rows()
    assert len(rows) == 1
    bucket, snrs = rows[0]
    assert snrs[a.bin_of(d.delta_frequency)] == 20 and len(snrs) == a.n_bins

    js = activity_to_dict(a)
    assert js["instance"] == (d.id or "?") and js["count"] == 1
    assert js["n_bins"] == a.n_bins and js["freq_max"] == a.freq_max
    assert js["rows"][0]["snr"][a.bin_of(d.delta_frequency)] == 20
    import json
    json.dumps(js)                    # must be serializable (None -> null)


def test_continuous_scroll_fills_empty_periods():
    """Dashboard path: n_rows cycles ending at wall clock, blanks without decodes."""
    from wims.server.state import activity_to_dict
    a = ActivityMap("X", period_s=15, n_rows=10)
    # Fixed "now": 12:00:07 UTC -> period index for 12:00:00.
    # 12*3600 = 43200 s -> ms 43200000 -> bucket 43200000/15000 = 2880.
    now = 1_700_000_000.0  # arbitrary epoch; we pin via monkeypatch of helper
    import wims.udp.activity as act
    real = act.utc_ms_since_midnight
    act.utc_ms_since_midnight = lambda t: 12 * 3600 * 1000 + 7_000  # 12:00:07
    try:
        rows = a.recent_rows(now=now)
        assert len(rows) == 10
        # All empty — continuous blank waterfall
        assert all(all(s is None for s in snrs) for _, snrs in rows)
        # Ending bucket is 12:00 period
        assert rows[-1][0] == (12 * 3600) // 15
        # Place a decode in an older period; it must appear in the window
        class D:
            time_ms = (12 * 3600 - 60) * 1000  # 11:59:00
            delta_frequency = 1500
            snr = 5
        a.add(D())
        rows2 = a.recent_rows(now=now)
        assert len(rows2) == 10
        hit = [snrs for bk, snrs in rows2 if snrs[a.bin_of(1500)] == 5]
        assert len(hit) == 1
        js = activity_to_dict(a, now=now)
        assert len(js["rows"]) == 10
    finally:
        act.utc_ms_since_midnight = real


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
