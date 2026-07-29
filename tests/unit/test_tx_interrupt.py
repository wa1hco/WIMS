"""Unit tests for the pure puncture() helper in testbed/tx_interrupt_bench.py.

Covers only the fast-mute actuator model (raised-cosine gated gap in int16 PCM);
no ft8sim/jt9 binaries required. The signal-level experiment itself lives in
the bench and runs on demand.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "testbed"))

from tx_interrupt_bench import puncture  # noqa: E402

FS = 1000                     # 1 kHz keeps sample indices == milliseconds
RAMP = 0.010                  # 10 ms ramp -> 10 samples, exact boundaries
AMPL = 10000


def make_const(n=1000, value=AMPL):
    return [value] * n


def test_gap_zero_returns_input_unchanged():
    x = make_const()
    y = puncture(x, FS, 0.100, 0.0, ramp_s=RAMP)
    assert y == x
    assert y is not x                       # pure: new object, no aliasing


def test_input_not_mutated():
    x = make_const()
    before = list(x)
    puncture(x, FS, 0.100, 0.050, ramp_s=RAMP)
    assert x == before


def test_full_attenuation_inside_gap():
    # gap [0.100, 0.150) -> samples 100..149 must be exactly zero
    y = puncture(make_const(), FS, 0.100, 0.050, ramp_s=RAMP)
    assert all(y[i] == 0 for i in range(100, 150))


def test_untouched_outside_gap_plus_ramps():
    # ramps occupy [0.090, 0.100) and [0.150, 0.160); everything else untouched
    x = make_const()
    y = puncture(x, FS, 0.100, 0.050, ramp_s=RAMP)
    assert y[:90] == x[:90]
    assert y[160:] == x[160:]


def test_ramp_length_and_cosine_shape():
    # Down-ramp samples 90..99: gain = 0.5*(1+cos(pi*u)), u = (i-90)/10.
    # Up-ramp samples 150..159: gain = 0.5*(1-cos(pi*u)), u = (i-150)/10.
    y = puncture(make_const(), FS, 0.100, 0.050, ramp_s=RAMP)
    for i in range(90, 100):
        u = (i - 90) / 10.0
        expect = round(AMPL * 0.5 * (1.0 + math.cos(math.pi * u)))
        assert y[i] == expect, (i, y[i], expect)
    for i in range(150, 160):
        u = (i - 150) / 10.0
        expect = round(AMPL * 0.5 * (1.0 - math.cos(math.pi * u)))
        assert y[i] == expect, (i, y[i], expect)


def test_ramps_monotonic():
    y = puncture(make_const(), FS, 0.100, 0.050, ramp_s=RAMP)
    down = y[90:100]
    up = y[150:160]
    assert all(a >= b for a, b in zip(down, down[1:])), down     # 1 -> 0
    assert all(a <= b for a, b in zip(up, up[1:])), up           # 0 -> 1
    assert down[0] == AMPL and up[0] == 0                        # endpoints


def test_gap_at_file_start():
    # Down-ramp would begin before t=0; must clamp, not crash.
    y = puncture(make_const(), FS, 0.0, 0.050, ramp_s=RAMP)
    assert all(y[i] == 0 for i in range(0, 50))                  # gap muted
    assert y[60:] == make_const()[60:]                           # after up-ramp
    assert len(y) == 1000


def test_gap_at_file_end():
    # Gap runs to exactly the last sample; up-ramp falls off the end.
    y = puncture(make_const(), FS, 0.950, 0.050, ramp_s=RAMP)
    assert all(y[i] == 0 for i in range(950, 1000))
    assert y[:940] == make_const()[:940]
    assert len(y) == 1000


def test_gap_extends_beyond_file_end():
    y = puncture(make_const(), FS, 0.900, 5.0, ramp_s=RAMP)
    assert all(y[i] == 0 for i in range(900, 1000))
    assert y[:890] == make_const()[:890]
    assert len(y) == 1000


def test_gap_entirely_beyond_file_is_noop():
    x = make_const()
    y = puncture(x, FS, 2.0, 0.5, ramp_s=RAMP)
    assert y == x


def test_negative_gap_length_is_noop():
    x = make_const()
    assert puncture(x, FS, 0.100, -0.5, ramp_s=RAMP) == x


def test_zero_ramp_hard_gate():
    # ramp_s = 0: hard mute, no division-by-zero, edges exactly at gap bounds.
    x = make_const()
    y = puncture(x, FS, 0.100, 0.050, ramp_s=0.0)
    assert all(y[i] == 0 for i in range(100, 150))
    assert y[:100] == x[:100] and y[150:] == x[150:]


def test_empty_input():
    assert puncture([], FS, 0.1, 0.05, ramp_s=RAMP) == []


def test_sine_attenuated_not_shifted():
    # Non-constant input: outside gap+ramps the waveform is bit-exact.
    n = 1000
    x = [int(8000 * math.sin(2 * math.pi * 100 * i / FS)) for i in range(n)]
    y = puncture(x, FS, 0.400, 0.100, ramp_s=RAMP)
    assert y[:390] == x[:390]
    assert y[510:] == x[510:]
    assert all(v == 0 for v in y[400:500])


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
