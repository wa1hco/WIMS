"""Roster scoring — pluggable, explainable priority (plan §3.5 / §3.11).

The priority algorithm is a matter of judgment (it shifts as a band opens/closes),
so it is deliberately *not* hardcoded:

- A **score is a sum of named, weighted factors** — and the per-factor breakdown is
  kept, so the operator (and we, while tuning) can see exactly *why* a station ranks
  where it does. Understandable beats clever.
- **Factors are small functions** and the **strategy is swappable by name** — change
  the algorithm without touching the engine.
- **Weights vary by band condition** (open / marginal / dead) — the same factors,
  re-tuned for the moment, via config (§3.11).

Nothing here transmits — it only *ranks recommendations*; the operator clicks
(§4.2, no automation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

# ARRL VHF QSO points per band (tunable; higher bands are worth more).
BAND_POINTS = {
    "6m": 1, "2m": 1, "1.25m": 2, "70cm": 2,
    "33cm": 3, "23cm": 3, "13cm": 3,
}


def band_points(band: str) -> int:
    return BAND_POINTS.get(band, 4)  # 4 for the higher microwave bands


# Weight sets per band condition — same factors, different emphasis. Tunable/config.
WEIGHTS = {
    "open":     {"new_mult": 25, "points": 2, "cq": 5, "snr": 1.0, "rover": 10},
    "marginal": {"new_mult": 45, "points": 3, "cq": 4, "snr": 0.4, "rover": 18},
    "dead":     {"new_mult": 60, "points": 4, "cq": 3, "snr": 0.2, "rover": 25},
}


def weights_for(condition: str) -> dict[str, float]:
    return dict(WEIGHTS.get(condition, WEIGHTS["open"]))


@dataclass
class Candidate:
    """A workable station derived from a decode, with log-resolved features."""
    call: str
    grid: str | None
    band: str
    instance_id: str
    snr: int
    is_cq: bool
    is_dupe: bool = False
    is_new_mult: bool = False
    is_rover: bool = False
    reachable: bool = True          # antenna can hear/point at it (§3.14 geometry)


@dataclass
class Factor:
    name: str
    contribution: float
    detail: str


@dataclass
class ScoredCandidate:
    candidate: Candidate
    total: float
    factors: list[Factor]
    excluded: bool
    reason: str = ""                # why excluded (dupe / not-CQ / unreachable)

    def explain(self) -> str:
        c = self.candidate
        head = f"{c.call or '?':10} {c.grid or '-':6} {c.band:5}"
        if self.excluded:
            return f"{head}  EXCLUDED ({self.reason})"
        terms = "  ".join(f"{f.name} {f.contribution:+g}" for f in self.factors)
        return f"{head}  score {self.total:+.1f}  [{terms}]"


@dataclass
class Context:
    weights: dict[str, float] = field(default_factory=lambda: weights_for("open"))
    condition: str = "open"

    def w(self, key: str, default: float = 0.0) -> float:
        return self.weights.get(key, default)


# --------------------------------------------------------------------------- #
# Factors — each returns a Factor or None (no contribution).
# --------------------------------------------------------------------------- #

FactorFn = Callable[[Candidate, Context], "Factor | None"]


def f_new_mult(c: Candidate, ctx: Context) -> Factor | None:
    if c.is_new_mult:
        return Factor("new_mult", ctx.w("new_mult", 25), f"new {c.band} grid {c.grid}")
    return None


def f_points(c: Candidate, ctx: Context) -> Factor | None:
    pts = band_points(c.band)
    return Factor("points", pts * ctx.w("points", 2), f"{c.band}={pts}pt")


def f_snr(c: Candidate, ctx: Context) -> Factor | None:
    # Workability: -24 dB -> 0, +6 dB -> ~10. Weak signals score low (waste cycles).
    work = max(0.0, min(10.0, (c.snr + 24) / 3))
    return Factor("snr", round(work * ctx.w("snr", 1.0), 1), f"{c.snr:+d}dB")


def f_cq(c: Candidate, ctx: Context) -> Factor | None:
    if c.is_cq:
        return Factor("cq", ctx.w("cq", 5), "calling CQ")
    return None


def f_rover(c: Candidate, ctx: Context) -> Factor | None:
    if c.is_rover and c.is_new_mult:
        return Factor("rover", ctx.w("rover", 10), "rover in new grid")
    return None


DEFAULT_FACTORS: list[FactorFn] = [f_new_mult, f_points, f_snr, f_cq, f_rover]


# --------------------------------------------------------------------------- #
# Strategy
# --------------------------------------------------------------------------- #


class ScoringStrategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def score(self, c: Candidate, ctx: Context) -> ScoredCandidate: ...

    def rank(self, candidates: Iterable[Candidate], ctx: Context) -> list[ScoredCandidate]:
        """Score all, drop excluded, sort best-first."""
        scored = [self.score(c, ctx) for c in candidates]
        active = [s for s in scored if not s.excluded]
        return sorted(active, key=lambda s: s.total, reverse=True)


class WeightedFactorStrategy(ScoringStrategy):
    """Transparent default: total = sum of weighted factors; dupes / non-CQ /
    unreachable are excluded (never recommended)."""

    def __init__(self, name: str = "vhf-default", factors: list[FactorFn] | None = None):
        self.name = name
        self.factors = factors if factors is not None else list(DEFAULT_FACTORS)

    def score(self, c: Candidate, ctx: Context) -> ScoredCandidate:
        if c.is_dupe:
            return ScoredCandidate(c, 0.0, [], excluded=True, reason="dupe")
        if not c.is_cq:
            return ScoredCandidate(c, 0.0, [], excluded=True, reason="not calling CQ")
        if not c.reachable:
            return ScoredCandidate(c, 0.0, [], excluded=True, reason="not reachable by antenna")
        factors = [f for f in (fn(c, ctx) for fn in self.factors) if f is not None]
        total = sum(f.contribution for f in factors)
        return ScoredCandidate(c, total, factors, excluded=False)


# Registry — strategies by name; config (§3.11) selects which.
_REGISTRY: dict[str, ScoringStrategy] = {}


def register(strategy: ScoringStrategy) -> ScoringStrategy:
    _REGISTRY[strategy.name] = strategy
    return strategy


def get_strategy(name: str = "vhf-default") -> ScoringStrategy:
    return _REGISTRY[name]


register(WeightedFactorStrategy())


# --------------------------------------------------------------------------- #
# Build a Candidate from a parsed decode + the log store (dupe/mult resolution).
# --------------------------------------------------------------------------- #


def build_candidate(decode, band: str, log=None, reachable: bool = True) -> Candidate:
    """Turn a parsed messages.Decode into a Candidate, resolving dupe/new-mult from
    the log store (§3.6) when provided."""
    call = (decode.dx_call or "").upper()
    grid = decode.grid
    is_dupe = bool(log and call and log.is_dupe(call, band, grid))
    is_new_mult = bool(log and grid and log.is_new_mult(grid, band))
    is_rover = "/R" in call
    return Candidate(
        call=call, grid=grid, band=band, instance_id=decode.id or "?",
        snr=decode.snr, is_cq=decode.is_cq, is_dupe=is_dupe,
        is_new_mult=is_new_mult, is_rover=is_rover, reachable=reachable,
    )
