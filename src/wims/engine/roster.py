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
mid-exchange, except our own TX heard on another radio), keyed by
`(instance, call, grid)`, aged out after `ttl`. On demand each
row is resolved against the N1MM log copy (dupe / new-mult) and scored by the pure
decision engine (`scoring.py`) so the operator keeps the explained priority **and** can
filter by "needed" (not yet worked). The console decides what to show; this layer ships
the facts (score, needed, band, azimuth inputs) for all retained rows.

Keyed on `(instance, call, grid)` so a **rover in a new grid** is a distinct, fresh row
(a new mult), never collapsed onto its old grid. A later report **without** a grid
(``R-10``, ``RR73``, ``73``) updates that station's existing row instead of opening a
second empty-grid line — otherwise one QSO paints two red "calling us" rows.

FT8/FT4 compound calls are one station. ``<P4/WE9V>`` is ``P4/WE9V``. A home-call
token (``WE9V``) joins that compound only on the same instance and band within
``COMPOUND_LINK_S``, and only when a CQ of the bare call has not shown a different
station. ``<...>`` never opens a row. A compound CQ carries no grid, so the row
stays blank — country still follows the full call — and is not marked grid assumed.
Nothing here transmits — it only ranks recommendations for the operator (§4.2).
Time is injected (`now`) for replayability.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from wims.engine import scoring as S
from wims.engine.callsign import (
    COMPOUND_LINK_S,
    home_call,
    is_compound_call,
    is_unresolved_hash,
    plain_call,
)
from wims.engine.geo import base_call as _base_call


def is_own_tx_decode(decode, own_calls: Iterable[str] | None) -> bool:
    """True when the transmitting station is us (other radio hearing our TX)."""
    dx = _base_call(getattr(decode, "dx_call", None))
    if not dx:
        return False
    owns = {_base_call(c) for c in (own_calls or ()) if c}
    owns.discard("")
    return bool(owns) and dx in owns


@dataclass
class _Entry:
    decode: object        # parsed messages.Decode (dx_call/to_call/grid/snr/is_cq/id)
    band: str
    last_seen: float
    dial_hz: int = 0      # instance dial at receipt -> RF freq = dial + decode df
    de_grid: str | None = None   # instance's own grid -> azimuth reference
    grid: str | None = None      # last known Maidenhead; kept across no-grid reports
    grid_remembered: bool = False  # grid is from memory, not this decode
    grid_assumed: bool = False     # rover square from an earlier hearing
    grid_tip: str = ""             # hover: when and on what band
    grid_stale: bool = False       # rover square too old to use


@dataclass
class _CompoundLink:
    """A full compound call that can explain a later home-call token."""

    full: str
    heard: float
    ambiguous: bool = False
    bare_cq: bool = False


def _band_key(band: str | None) -> str:
    text = (band or "").strip()
    if not text or text == "?":
        return "?"
    return text


class RosterBuilder:
    def __init__(self, log=None, strategy_name: str = "vhf-default", ttl: float = 300.0):
        self.log = log
        self.strategy = S.get_strategy(strategy_name)
        self.ttl = ttl
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        # (instance, band, home call) → full compound heard recently.
        self._links: dict[tuple[str, str, str], _CompoundLink] = {}

    def canonicalize(self, decode, band: str, now: float,
                     own_calls: Iterable[str] | None = None) -> str | None:
        """Point ``decode.dx_call`` at one full call, or clear it.

        Strips hash brackets. Maps a home-call token onto a compound heard on
        this instance and band inside ``COMPOUND_LINK_S``, unless a CQ of the
        bare call showed a different station. Returns the call to key, or None
        when the transmitter is unknown (``<...>``). Does not invent a grid.
        Our own compound call is not used as a link for other stations.
        """
        self._prune_links(now)
        raw = getattr(decode, "dx_call", None)
        if is_unresolved_hash(raw):
            decode.dx_call = None
            self._plain_to_call(decode)
            return None
        call = plain_call(raw)
        if not call:
            if raw:
                decode.dx_call = None
            self._plain_to_call(decode)
            return None
        self._plain_to_call(decode)
        decode.dx_call = call
        # Our own TX must not become the link that renames someone else.
        if is_own_tx_decode(decode, own_calls):
            return call
        inst = getattr(decode, "id", None) or "?"
        bkey = _band_key(band)
        home = home_call(call)
        if is_compound_call(call) and home:
            self._remember_compound(inst, bkey, home, call, now)
            link = self._links.get((inst, bkey, home))
            if link is not None and not link.ambiguous and not link.bare_cq:
                self._absorb_bare(inst, bkey, home, call, now)
            decode.dx_call = call
            return call
        if home and home == call:
            link = self._fresh_link(inst, bkey, home, now)
            if link is not None and not getattr(decode, "is_cq", False):
                decode.dx_call = link.full
                return link.full
            if getattr(decode, "is_cq", False):
                self._note_bare_cq(inst, bkey, home, now)
        return call

    def observe_decode(self, decode, band: str, now: float,
                       *, dial_hz: int = 0, de_grid: str | None = None,
                       own_calls: Iterable[str] | None = None,
                       heard_grid: str | None = None,
                       heard_tip: str = "",
                       heard_stale: bool = False,
                       heard_assumed: bool = False) -> None:
        """Retain a decoded station as a roster row. Every decode carrying a callsign
        is kept (CQ or mid-exchange) so the console can show all activity and filter by
        need; a decode with no resolvable call is dropped.

        Own-station TX (the other radio on this band hearing us) is not a DX row.

        ``heard_grid`` is a square remembered from an earlier decode when this
        message has none. ``heard_assumed`` is that square for a rover when it
        was not heard in the current QSO. ``heard_stale`` leaves the cell
        blank: a rover square that is too old to guess.

        A hashed or home-call form of a compound station updates that station's
        row. A grid remembered for a different token is not copied across, and
        a missing grid is left blank rather than marked assumed.
        """
        before = plain_call(getattr(decode, "dx_call", None))
        call = self.canonicalize(decode, band, now, own_calls=own_calls)
        if not call:
            return
        if is_own_tx_decode(decode, own_calls):
            return
        # heard_grid was looked up under the pre-alias token. A home-call
        # square (WE9V in the States) must not become P4/WE9V's grid.
        if before and before != call:
            heard_grid = None
            heard_tip = ""
            heard_stale = False
            heard_assumed = False
        inst = decode.id or "?"
        decode_grid = (decode.grid or "").strip().upper()
        grid = decode_grid
        from_memory = False
        tip = heard_tip or ""
        stale = False
        if not decode_grid and heard_stale:
            stale = True
            grid = ""
        elif not decode_grid and heard_grid:
            grid = heard_grid.strip().upper()
            from_memory = True
        if grid:
            # A grid is now known: drop the placeholder empty-grid row if we had one.
            empty_key = (inst, call, "")
            if empty_key in self._entries:
                del self._entries[empty_key]
            key = (inst, call, grid)
        elif stale:
            # Do not keep an older square on a line we are refusing to guess.
            for k in [k for k in self._entries if k[0] == inst and k[1] == call]:
                del self._entries[k]
            key = (inst, call, "")
        else:
            # RR73 / R-10 / 73 carry no grid — fold into the latest row for this
            # instance+call (rover with two grids: the most recently heard one).
            existing = [k for k in self._entries if k[0] == inst and k[1] == call]
            key = (max(existing, key=lambda k: self._entries[k].last_seen)
                   if existing else (inst, call, ""))
        prev = self._entries.get(key)
        keep_grid = None if stale else (grid or (prev.grid if prev else "") or None)
        remembered = bool(
            not decode_grid and not stale and (from_memory or keep_grid)
        )
        if decode_grid:
            tip = ""
        self._entries[key] = _Entry(
            decode=decode, band=band, last_seen=now,
            dial_hz=dial_hz, de_grid=de_grid, grid=keep_grid,
            grid_remembered=remembered,
            grid_assumed=bool(remembered and heard_assumed),
            grid_tip=tip if remembered or stale else "",
            grid_stale=stale,
        )

    def drop_own_station(self, own_calls: Iterable[str] | None) -> int:
        """Remove retained rows whose DX call is our station. Returns how many dropped."""
        owns = {_base_call(c) for c in (own_calls or ()) if c}
        owns.discard("")
        if not owns:
            return 0
        dead = [k for k in self._entries if _base_call(k[1]) in owns]
        for k in dead:
            del self._entries[k]
        return len(dead)

    def _prune(self, now: float) -> None:
        dead = [k for k, e in self._entries.items() if now - e.last_seen > self.ttl]
        for k in dead:
            del self._entries[k]
        self._prune_links(now)

    def _prune_links(self, now: float) -> None:
        dead = [k for k, link in self._links.items()
                if now - link.heard > COMPOUND_LINK_S]
        for k in dead:
            del self._links[k]

    def _plain_to_call(self, decode) -> None:
        to = getattr(decode, "to_call", None)
        if not to:
            return
        if is_unresolved_hash(to):
            decode.to_call = None
            return
        plain = plain_call(to)
        if plain:
            decode.to_call = plain

    def _remember_compound(self, inst: str, band: str, home: str, full: str,
                           now: float) -> None:
        key = (inst, band, home)
        link = self._links.get(key)
        if link is None:
            self._links[key] = _CompoundLink(full=full, heard=now)
            return
        if link.full and link.full != full:
            link.ambiguous = True
            link.heard = now
            return
        link.full = full or link.full
        link.heard = now

    def _note_bare_cq(self, inst: str, band: str, home: str, now: float) -> None:
        """A CQ of the bare call is that station, not the compound."""
        key = (inst, band, home)
        link = self._links.get(key)
        if link is None:
            self._links[key] = _CompoundLink(full="", heard=now, bare_cq=True)
            return
        link.bare_cq = True

    def _fresh_link(self, inst: str, band: str, home: str, now: float):
        link = self._links.get((inst, band, home))
        if link is None or not link.full or link.ambiguous or link.bare_cq:
            return None
        if now - link.heard > COMPOUND_LINK_S:
            return None
        return link

    def _absorb_bare(self, inst: str, band: str, home: str, full: str,
                     now: float) -> None:
        """Fold a recent home-call exchange into the compound row.

        A CQ of the bare call is left where it is. An assumed square is not
        carried over: the compound row keeps a grid only when that transmission
        itself contained one.
        """
        victims = []
        for key, entry in self._entries.items():
            if key[0] != inst or key[1] != home:
                continue
            if _band_key(entry.band) != band:
                continue
            if now - entry.last_seen > COMPOUND_LINK_S:
                continue
            if self._entry_is_bare_cq(entry):
                continue
            victims.append(key)
        for key in victims:
            entry = self._entries.pop(key)
            self._drop_unheard_grid(entry)
            if getattr(entry.decode, "dx_call", None):
                entry.decode.dx_call = full
            new_key = (inst, full, entry.grid or "")
            prev = self._entries.get(new_key)
            if prev is None:
                self._entries[new_key] = entry
                continue
            if entry.last_seen >= prev.last_seen:
                if not entry.grid and prev.grid:
                    entry.grid = prev.grid
                    entry.grid_remembered = prev.grid_remembered
                    entry.grid_assumed = False
                    entry.grid_tip = prev.grid_tip
                self._entries[new_key] = entry
            elif not prev.grid and entry.grid:
                prev.grid = entry.grid
                prev.grid_assumed = False
                prev.grid_remembered = False

    @staticmethod
    def _entry_is_bare_cq(entry) -> bool:
        dec = entry.decode
        if not getattr(dec, "is_cq", False):
            return False
        call = plain_call(getattr(dec, "dx_call", None)) or ""
        return bool(call) and not is_compound_call(call)

    @staticmethod
    def _drop_unheard_grid(entry) -> None:
        """Keep a square only when this decode actually sent one."""
        heard = (getattr(entry.decode, "grid", None) or "").strip().upper()
        if heard:
            entry.grid = heard
            entry.grid_assumed = False
            entry.grid_remembered = False
            entry.grid_stale = False
            return
        entry.grid = None
        entry.grid_assumed = False
        entry.grid_remembered = False
        entry.grid_tip = ""
        entry.grid_stale = False

    def last_grid(self, call: str, band: str | None = None) -> str | None:
        """Last Maidenhead heard for this call, preferring the same band.

        N1MM often logs a contact with an empty grid. The decode on the roster
        is the grid the operator just worked, so the multiplier can clear.
        """
        call_u = (call or "").upper()
        if not call_u:
            return None
        best = None
        best_ts = -1.0
        fallback = None
        fallback_ts = -1.0
        for key, entry in self._entries.items():
            if key[1] != call_u or not entry.grid:
                continue
            if band and entry.band == band:
                if entry.last_seen >= best_ts:
                    best_ts = entry.last_seen
                    best = entry.grid
            elif entry.last_seen >= fallback_ts:
                fallback_ts = entry.last_seen
                fallback = entry.grid
        return best or fallback

    def grid_on_band(self, call: str, band: str | None) -> str | None:
        """Grid heard for this call on this band.

        A roster row whose band is still unknown can fill a log line. A grid
        heard on a different band cannot: a 40 m square does not credit 20 m.
        """
        call_u = (call or "").upper()
        if not call_u:
            return None
        best = None
        best_ts = -1.0
        for key, entry in self._entries.items():
            if key[1] != call_u or not entry.grid:
                continue
            heard = entry.band or ""
            if band and heard not in {band, "?", ""}:
                continue
            if entry.last_seen >= best_ts:
                best_ts = entry.last_seen
                best = entry.grid
        return best

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
            cand = S.build_candidate(e.decode, e.band, self.log, grid=e.grid)
            sc = self.strategy.score(cand, ctx)
            if cand.is_dupe:
                not_needed += 1
            rows.append((sc, e))
        rows.sort(key=lambda t: (not t[0].candidate.is_dupe, t[0].total), reverse=True)
        return rows, not_needed
