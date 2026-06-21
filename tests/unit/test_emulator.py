"""Tests for the WSJT-X emulator's pure logic (no networking)."""

import random
import sys
from pathlib import Path

# Importing the emulator adds src/ to sys.path (its own bootstrap), so wims imports work after.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "testbed" / "simulators"))
import emulator as EM  # noqa: E402

from wims.udp import messages as M  # noqa: E402
from wims.udp import encode as E  # noqa: E402


def test_parse_instances_default():
    insts = EM.parse_instances(None)
    assert len(insts) >= 3
    assert any(i.id == "SIM-6M" and i.dial_hz == 50_313_000 for i in insts)


def test_parse_instances_spec():
    insts = EM.parse_instances("A:50313000:FT8,B:144174000")
    assert insts[0].id == "A" and insts[0].dial_hz == 50_313_000 and insts[0].mode == "FT8"
    assert insts[1].id == "B" and insts[1].mode == "FT8"  # mode defaulted


def test_generated_messages_are_valid_and_some_carry_grid():
    rng = random.Random(7)
    saw_cq_grid = saw_rover = False
    for c in range(80):
        msg = EM.make_decode_message(rng, c)
        d = M.parse(E.build_decode("SIM", time_ms=0, snr=-5, delta_time=0.1,
                                   delta_frequency=1500, message=msg))
        assert d.message == msg                       # round-trips through the wire format
        if d.is_cq and d.grid:
            saw_cq_grid = True
        if "/R" in (d.dx_call or ""):
            saw_rover = True
    assert saw_cq_grid          # CQ-with-grid decodes are produced (grid extraction path)
    assert saw_rover            # rover (/R) appears in the stream


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
