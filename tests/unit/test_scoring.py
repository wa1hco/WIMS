"""Scoring framework: ranking, explainability, condition weights, pluggability."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine import scoring as S  # noqa: E402
from wims.engine.scoring import Candidate, Context, ScoredCandidate, ScoringStrategy  # noqa: E402
from wims.udp import messages as M, encode as E  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402


def _cand(call, *, grid=None, band="6m", snr=0, is_cq=True, dupe=False, mult=False,
          rover=False, reachable=True):
    return Candidate(call=call, grid=grid, band=band, instance_id="SIM", snr=snr,
                     is_cq=is_cq, is_dupe=dupe, is_new_mult=mult, is_rover=rover,
                     reachable=reachable)


def test_excludes_dupe_noncq_unreachable():
    strat = S.get_strategy()
    ctx = Context()
    cands = [
        _cand("DUPE1", dupe=True),
        _cand("NOCQ", is_cq=False),
        _cand("FAR", reachable=False),
        _cand("GOOD", grid="FN31", mult=True, snr=0),
    ]
    ranked = strat.rank(cands, ctx)
    assert [r.candidate.call for r in ranked] == ["GOOD"]   # only the workable one
    # excluded ones carry a reason
    scored = {c.call: strat.score(c, ctx) for c in cands}
    assert scored["DUPE1"].excluded and scored["DUPE1"].reason == "dupe"
    assert scored["NOCQ"].reason == "not calling CQ"
    assert scored["FAR"].reason == "not reachable by antenna"


def test_new_mult_outranks_plain_and_explains():
    strat = S.get_strategy()
    ctx = Context()
    mult = _cand("K1ROV", grid="FN31", mult=True, rover=True, snr=-10)
    plain = _cand("W2XYZ", grid="FN20", snr=+8)
    ranked = strat.rank([plain, mult], ctx)
    assert ranked[0].candidate.call == "K1ROV"            # mult+rover wins despite weaker signal
    text = ranked[0].explain()
    assert "new_mult" in text and "rover" in text and "score" in text


def test_condition_weights_change_score():
    strat = S.get_strategy()
    c = _cand("K1ABC", grid="FN31", mult=True, snr=-10)
    open_total = strat.score(c, Context(weights=S.weights_for("open"), condition="open")).total
    marg_total = strat.score(c, Context(weights=S.weights_for("marginal"), condition="marginal")).total
    assert marg_total > open_total                         # mults weighted higher when marginal


def test_pluggable_custom_strategy():
    class OnlySnr(ScoringStrategy):
        name = "snr-only"
        def score(self, c, ctx):
            return ScoredCandidate(c, float(c.snr), [], excluded=not c.is_cq)
    S.register(OnlySnr())
    assert S.get_strategy("snr-only").name == "snr-only"
    ranked = S.get_strategy("snr-only").rank([_cand("A", snr=3), _cand("B", snr=9)], Context())
    assert [r.candidate.call for r in ranked] == ["B", "A"]


def test_build_candidate_from_decode_and_log():
    log = LogStore(":memory:")
    # Worked K1ABC on 6m/FN42 already -> a fresh CQ from them is a dupe.
    log.upsert(LoggedQso(id="q1", call="K1ABC", band="6m", grid="FN42", mode="FT8",
                         points=1, is_mult=True, contest="VHF", timestamp="", operator="",
                         rover_location=None, source="test"))
    dupe_dec = M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-5, delta_time=0.1,
                                      delta_frequency=1500, message="CQ K1ABC FN42"))
    c = S.build_candidate(dupe_dec, "6m", log)
    assert c.call == "K1ABC" and c.is_dupe is True

    rover_dec = M.parse(E.build_decode("SIM-6M", time_ms=0, snr=-12, delta_time=0.1,
                                       delta_frequency=1600, message="CQ K1ROV/R FN31"))
    r = S.build_candidate(rover_dec, "6m", log)
    assert r.is_rover is True and r.is_new_mult is True and r.grid == "FN31"


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
