"""TX arbiter + overlap detector — including the 'never two TX per group' proof."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.interlock.arbiter import TxArbiter, OverlapDetector  # noqa: E402


def test_single_grant_per_group():
    g = lambda i: "6m"                      # both instances share one resource group
    a = TxArbiter(g)
    assert a.request("A") is True           # A granted
    assert a.request("B") is False          # B queued (same group)
    assert a.is_granted("A") and not a.is_granted("B")
    assert a.queue("6m") == ["B"]
    promoted = a.release("A")               # A done -> B promoted
    assert promoted == "B" and a.is_granted("B")
    assert a.queue("6m") == []


def test_concurrent_groups():
    g = lambda i: i[0]                       # group by first char -> different groups
    a = TxArbiter(g)
    assert a.request("Ax") is True
    assert a.request("Bx") is True           # different group -> also granted
    assert a.is_granted("Ax") and a.is_granted("Bx")


def test_idempotent_and_withdraw():
    g = lambda i: "6m"
    a = TxArbiter(g)
    assert a.request("A") is True
    assert a.request("A") is True            # idempotent
    assert a.request("B") is False
    a.withdraw("B")                          # B gives up before being promoted
    assert a.queue("6m") == []
    assert a.release("A") is None            # nothing to promote


def test_overlap_detector_flags_two_in_group():
    det = OverlapDetector(lambda i: "G")     # everyone in one group
    assert det.observe("A", True, 1.0) is None   # one TX: fine
    v = det.observe("B", True, 2.0)              # second TX same group: violation
    assert v is not None and set(v.instances) == {"A", "B"} and not det.clean


def test_overlap_detector_ok_across_groups():
    det = OverlapDetector(lambda i: i[0])    # A* and B* are different groups
    assert det.observe("A1", True, 1.0) is None
    assert det.observe("B1", True, 2.0) is None  # different group -> fine
    assert det.clean


def test_stress_never_two_tx_per_group():
    """Randomized request/grant/release across 3 groups; the actual transmit state
    (driven only by arbiter grants/promotions) must never overlap within a group."""
    groups = {f"I{i}": f"G{i % 3}" for i in range(12)}
    gf = lambda i: groups[i]
    a = TxArbiter(gf)
    det = OverlapDetector(gf)
    rng = random.Random(0)
    txing: dict[str, bool] = {}
    insts = list(groups)
    t = 0.0
    for _ in range(5000):
        t += 1
        i = rng.choice(insts)
        if rng.random() < 0.5:                       # try to acquire + transmit
            if not txing.get(i) and a.request(i):
                det.observe(i, True, t)
                txing[i] = True
        else:                                        # stop + release (promote next)
            if txing.get(i):
                det.observe(i, False, t)             # stop BEFORE the next starts
                txing[i] = False
            promoted = a.release(i)
            if promoted:
                det.observe(promoted, True, t)
                txing[promoted] = True
    assert det.clean, f"overlap detected: {det.violations[:3]}"


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
