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

"""Live call roster — retain recent decodes, score & rank them (plan §3.5 / §2.2).

GridTracker-style: rows are **stations heard** (every decode with a callsign, CQ or
mid-exchange), keyed by `(instance, call, grid)`, aged out after `ttl`. On demand each
row is resolved against the N1MM log copy (dupe / new-mult) and scored by the pure
decision engine (`scoring.py`) so the operator keeps the explained priority **and** can
filter by "needed" (not yet worked). The console decides what to show; this layer ships
the facts (score, needed, band, azimuth inputs) for all retained rows.

Keyed on `(instance, call, grid)` so a **rover in a new grid** is a distinct, fresh row
(a new mult), never collapsed onto its old grid. Nothing here transmits — it only ranks
recommendations for the operator (§4.2). Time is injected (`now`) for replayability.
"""

from __future__ import annotations

from dataclasses import dataclass

from wims.engine import scoring as S


@dataclass
class _Entry:
    decode: object        # parsed messages.Decode (dx_call/to_call/grid/snr/is_cq/id)
    band: str
    last_seen: float
    dial_hz: int = 0      # instance dial at receipt -> RF freq = dial + decode df
    de_grid: str | None = None   # instance's own grid -> azimuth reference


class RosterBuilder:
    def __init__(self, log=None, strategy_name: str = "vhf-default", ttl: float = 300.0):
        self.log = log
        self.strategy = S.get_strategy(strategy_name)
        self.ttl = ttl
        self._entries: dict[tuple[str, str, str], _Entry] = {}

    def observe_decode(self, decode, band: str, now: float,
                       *, dial_hz: int = 0, de_grid: str | None = None) -> None:
        """Retain a decoded station as a roster row. Every decode carrying a callsign
        is kept (CQ or mid-exchange) so the console can show all activity and filter by
        need; a decode with no resolvable call is dropped."""
        if not decode.dx_call:
            return
        key = (decode.id or "?", (decode.dx_call or "").upper(), decode.grid or "")
        self._entries[key] = _Entry(decode=decode, band=band, last_seen=now,
                                    dial_hz=dial_hz, de_grid=de_grid)

    def _prune(self, now: float) -> None:
        dead = [k for k, e in self._entries.items() if now - e.last_seen > self.ttl]
        for k in dead:
            del self._entries[k]

    def entry_for(self, row_id: str) -> "_Entry | None":
        """Look up a retained row by its `instance|call|grid` id (see `roster_to_dict`).

        The id mirrors the entry key; `rsplit` from the right so an instance id that
        itself contains '|' still resolves (call/grid never do). Returns the `_Entry`
        (carrying the raw `Decode` needed to echo a Reply) or None if aged out / unknown."""
        parts = row_id.rsplit("|", 2)
        if len(parts) != 3:
            return None
        inst, call, grid = parts
        return self._entries.get((inst, call.upper(), grid))

    def reband_unknown(self, instance_id: str, band: str) -> int:
        """Assign `band` to rows for this instance that were tagged ``?`` (decode
        arrived before the first Status). Does not drop anything.
        """
        if not instance_id or not band or band == "?":
            return 0
        n = 0
        for k, e in self._entries.items():
            if k[0] != instance_id:
                continue
            if e.band in ("?", "", None):
                e.band = band
                n += 1
        return n

    def drop_other_bands(self, instance_id: str, band: str) -> int:
        """Drop retained rows for `instance_id` that are not on `band`.

        Call only on a **real QSY** (known old band → different known new band).
        Do not use on every Status — provisional ``?`` rows should be rebanded, not
        dropped. Returns how many rows were removed.
        """
        if not instance_id or not band or band == "?":
            return 0
        dead = [k for k, e in self._entries.items()
                if k[0] == instance_id
                and e.band and e.band not in ("?", "")
                and e.band != band]
        for k in dead:
            del self._entries[k]
        return len(dead)

    def ranked(self, now: float, ctx: S.Context | None = None) -> tuple[list[tuple], int]:
        """Score every retained row against the log. Returns
        `([(ScoredCandidate, _Entry), ...], not_needed_count)`. **All** rows are
        returned (needed and already-worked); `not_needed_count` is how many are dupes
        (already worked — the console's default view hides them). Sorted needed-first,
        then by score, as a sensible default before the console re-sorts."""
        self._prune(now)
        ctx = ctx or S.Context()
        rows: list[tuple] = []
        not_needed = 0
        for e in self._entries.values():
            cand = S.build_candidate(e.decode, e.band, self.log)
            sc = self.strategy.score(cand, ctx)
            if cand.is_dupe:
                not_needed += 1
            rows.append((sc, e))
        rows.sort(key=lambda t: (not t[0].candidate.is_dupe, t[0].total), reverse=True)
        return rows, not_needed
