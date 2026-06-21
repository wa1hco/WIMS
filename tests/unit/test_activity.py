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
