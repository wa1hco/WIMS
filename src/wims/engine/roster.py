"""Live call roster — retain recent CQ decodes, score & rank them (plan §3.5 / §2.2).

The decision engine (`scoring.py`) is pure: given Candidates + a Context it returns a
ranked, explained list. This builder is the *stateful* layer that feeds it — it keeps
the most recent workable CQ per `(instance, call, grid)`, ages stale ones out, and on
demand resolves each against the log store (dupe / new-mult) and scores it.

Keyed on `(instance, call, grid)` so a **rover in a new grid** is a distinct, fresh
row (a new mult), never collapsed onto its old grid. Nothing here transmits — it only
ranks recommendations for the operator (§4.2).

Time is injected (`now`) so it is testable and replayable.
"""

from __future__ import annotations

from dataclasses import dataclass

from wims.engine import scoring as S


@dataclass
class _Entry:
    decode: object        # parsed messages.Decode (dx_call/grid/snr/is_cq/id)
    band: str
    last_seen: float


class RosterBuilder:
    def __init__(self, log=None, strategy_name: str = "vhf-default", ttl: float = 300.0):
        self.log = log
        self.strategy = S.get_strategy(strategy_name)
        self.ttl = ttl
        self._entries: dict[tuple[str, str, str], _Entry] = {}

    def observe_decode(self, decode, band: str, now: float) -> None:
        """Retain a CQ decode as a workable candidate (non-CQ decodes are ignored —
        you answer callers, you don't recommend stations already in a QSO)."""
        if not (decode.is_cq and decode.dx_call):
            return
        key = (decode.id or "?", (decode.dx_call or "").upper(), decode.grid or "")
        self._entries[key] = _Entry(decode=decode, band=band, last_seen=now)

    def _prune(self, now: float) -> None:
        dead = [k for k, e in self._entries.items() if now - e.last_seen > self.ttl]
        for k in dead:
            del self._entries[k]

    def ranked(self, now: float, ctx: S.Context | None = None) -> tuple[list[tuple], int]:
        """Score every retained candidate against the log. Returns
        `([(ScoredCandidate, last_seen), ...] best-first, excluded_count)` — excluded
        (dupe / unreachable) candidates are counted but not returned."""
        self._prune(now)
        ctx = ctx or S.Context()
        scored: list[tuple] = []
        excluded = 0
        for e in self._entries.values():
            cand = S.build_candidate(e.decode, e.band, self.log)
            sc = self.strategy.score(cand, ctx)
            if sc.excluded:
                excluded += 1
            else:
                scored.append((sc, e.last_seen))
        scored.sort(key=lambda t: t[0].total, reverse=True)
        return scored, excluded
