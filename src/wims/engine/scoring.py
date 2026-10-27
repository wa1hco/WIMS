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
    need_reason: str = ""
    mult_reason: str = ""
    qso_points: int | None = None
    # "" | "needed" | "unconfirmed". Empty on contest rows.
    chase: str = ""


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
        detail = c.mult_reason or f"new {c.band} grid {c.grid}"
        return Factor("new_mult", ctx.w("new_mult", 25), detail)
    return None


def f_points(c: Candidate, ctx: Context) -> Factor | None:
    pts = band_points(c.band) if c.qso_points is None else int(c.qso_points)
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


def build_candidate(decode, band: str, log=None, reachable: bool = True,
                    grid: str | None = None) -> Candidate:
    """Turn a parsed messages.Decode into a Candidate, resolving dupe/new-mult from
    the log store (§3.6) when provided.

    `grid` overrides `decode.grid` so the roster can keep a last-known Maidenhead
    after a no-grid report (RR73 / R-10) folded into the same row.
    """
    call = (decode.dx_call or "").upper()
    grid = (grid or decode.grid or None)
    if grid:
        grid = str(grid).strip().upper() or None
    mode = getattr(decode, "mode", None)
    need_reason = ""
    mult_reason = ""
    qso_points = None
    chase = ""
    if log is not None and hasattr(log, "classify"):
        verdict = log.classify(call, band, grid, mode)
        is_dupe = bool(verdict.is_dupe)
        is_new_mult = bool(verdict.is_new_mult)
        need_reason = verdict.need_reason or ""
        mult_reason = verdict.mult_reason or ""
        qso_points = verdict.points
        chase = getattr(verdict, "chase", "") or ""
    else:
        is_dupe = bool(log and call and log.is_dupe(call, band, grid))
        is_new_mult = bool(log and grid and log.is_new_mult(grid, band))
    is_rover = "/R" in call
    return Candidate(
        call=call, grid=grid, band=band, instance_id=decode.id or "?",
        snr=decode.snr, is_cq=decode.is_cq, is_dupe=is_dupe,
        is_new_mult=is_new_mult, is_rover=is_rover, reachable=reachable,
        need_reason=need_reason, mult_reason=mult_reason, qso_points=qso_points,
        chase=chase,
    )


# --------------------------------------------------------------------------- #
# DX cluster spots (design §2.15). A separate list from the live roster.
# A QSY spot stays eligible. ``qsy`` is a cost (negative), not a gate.
# The live-roster WEIGHTS above are not used here.
# --------------------------------------------------------------------------- #

# Default weights. Setup can change the QSY cost (stored as a positive
# number of points; the weight applied here is negative).
CLUSTER_WEIGHTS = {
    "need_new": 40,          # new grid / multiplier / entity on that band
    "need_call": 18,         # needed, and not a new multiplier
    "need_unconfirmed": 12,  # worked place, not confirmed, still chased
    "recency": 15,           # 1 when the spot just arrived, 0 at the 15 min age
    "spotters": 10,          # 1 spotter is 1/3, 3 or more is full
    "spotter_near": 8,       # a spotter within 500 km of us
    "distance": 12,          # inside the sweet spot for that band
    "rover": 15,             # /R, or a call already heard as a rover
    "qsy": -8,               # no live WSJT-X on this band and mode
}


def cluster_weights(qsy_cost: float | None = None) -> dict[str, float]:
    """Named spot weights. ``qsy_cost`` is points taken off (0 or more)."""
    weights = dict(CLUSTER_WEIGHTS)
    if qsy_cost is not None:
        weights["qsy"] = -abs(float(qsy_cost))
    return weights


@dataclass
class SpotFeatures:
    """What the spot scorer needs. The filter has already dropped dupes."""

    is_new_mult: bool = False
    chase: str = ""
    is_rover: bool = False
    needs_qsy: bool = False
    age_s: float = 0.0
    ttl_s: float = 15 * 60
    spotter_count: int = 1
    spotter_near: float = 0.0       # 0..1
    distance_fit: float = 0.0       # 0..1
    need_detail: str = ""
    mult_detail: str = ""
    near_detail: str = ""
    distance_detail: str = ""


@dataclass
class SpotScore:
    total: float
    factors: list[Factor]

    def explain(self) -> str:
        terms = "  ".join(f"{f.name} {f.contribution:+g}" for f in self.factors)
        return f"score {self.total:+.1f}  [{terms}]"


def _round1(value: float) -> float:
    return round(float(value), 1)


def _age_words(age_s: float) -> str:
    age = max(0, int(age_s))
    if age < 60:
        return f"{age}s old"
    return f"{age // 60} min old"


def score_spot(features: SpotFeatures,
               weights: dict[str, float] | None = None) -> SpotScore:
    """Rank one needed spot. Nothing here transmits."""
    w = weights if weights is not None else cluster_weights()
    factors: list[Factor] = []

    def add(name: str, amount: float, detail: str) -> None:
        if amount <= 0 and name != "qsy":
            return
        contribution = _round1(amount * float(w.get(name, 0.0)))
        if contribution == 0:
            return
        factors.append(Factor(name, contribution, detail))

    if features.is_new_mult:
        detail = features.mult_detail or features.need_detail or "new multiplier"
        add("need_new", 1.0, detail)
    elif (features.chase or "") == "unconfirmed":
        add("need_unconfirmed", 1.0, features.need_detail or "unconfirmed")
    else:
        add("need_call", 1.0, features.need_detail or "needed")

    ttl = features.ttl_s if features.ttl_s > 0 else 1.0
    fresh = max(0.0, 1.0 - max(0.0, features.age_s) / ttl)
    add("recency", fresh, _age_words(features.age_s))

    heard = min(1.0, max(0, features.spotter_count) / 3.0)
    n = max(0, int(features.spotter_count))
    word = "spotter" if n == 1 else "spotters"
    add("spotters", heard, f"{n} {word}")

    if features.spotter_near > 0:
        add("spotter_near", min(1.0, features.spotter_near),
            features.near_detail or "spotter near us")

    if features.distance_fit > 0:
        add("distance", min(1.0, features.distance_fit),
            features.distance_detail or "distance for this band")

    if features.is_rover:
        add("rover", 1.0, "rover")

    if features.needs_qsy:
        # Weight is stored negative. Pass amount 1 and let the sign stand,
        # including a cost of 0 which adds nothing.
        cost = float(w.get("qsy", 0.0))
        if cost > 0:
            cost = -cost
        if cost != 0:
            factors.append(Factor("qsy", _round1(cost), "QSY"))

    total = _round1(sum(f.contribution for f in factors))
    return SpotScore(total, factors)
