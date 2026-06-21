"""RosterBuilder: retain CQs, age out, resolve dupe/mult, rank (engine/roster.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402


def _decode(mid, msg, *, snr=-5, df=1500):
    return M.parse(E.build_decode(mid, time_ms=0, snr=snr, delta_time=0.1,
                                  delta_frequency=df, message=msg))


def test_retains_only_cq_and_ranks_by_score():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42", snr=-2), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "CQ W2XYZ FN20", snr=-18), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "WA1HCO K3DEF FN30", snr=0), "6m", now=10.0)  # not CQ
    scored, excluded = rb.ranked(now=11.0)
    calls = [s.candidate.call for s, _ in scored]
    assert calls == ["K1ABC", "W2XYZ"]          # non-CQ never enters; stronger first
    assert excluded == 0


def test_rover_new_grid_is_distinct_row():
    rb = RosterBuilder(log=None)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ROV/R FN31"), "6m", now=10.0)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ROV/R FN32"), "6m", now=10.0)  # new grid
    scored, _ = rb.ranked(now=11.0)
    grids = sorted(s.candidate.grid for s, _ in scored)
    assert grids == ["FN31", "FN32"]            # two rows, not collapsed
    assert all(s.candidate.is_rover for s, _ in scored)


def test_dupe_from_log_is_excluded():
    log = LogStore(":memory:")
    log.upsert(LoggedQso(id="q1", call="K1ABC", band="6m", grid="FN42", mode="FT8",
                         points=1, is_mult=True, contest="VHF", timestamp="", operator="",
                         rover_location=None, source="test"))
    rb = RosterBuilder(log=log)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42"), "6m", now=10.0)   # already worked
    rb.observe_decode(_decode("SIM-6M", "CQ N1NEW FN43"), "6m", now=10.0)   # fresh + new mult
    scored, excluded = rb.ranked(now=11.0)
    assert [s.candidate.call for s, _ in scored] == ["N1NEW"]
    assert excluded == 1
    assert scored[0][0].candidate.is_new_mult is True


def test_stale_entries_age_out():
    rb = RosterBuilder(log=None, ttl=60.0)
    rb.observe_decode(_decode("SIM-6M", "CQ K1ABC FN42"), "6m", now=10.0)
    assert rb.ranked(now=50.0)[0]                  # still present at +40s
    scored, _ = rb.ranked(now=200.0)               # past ttl
    assert scored == []


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
