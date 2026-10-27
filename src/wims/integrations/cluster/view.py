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

"""Turn stored spots into the Operate list.

A spot on another band or mode stays. It is marked QSY and the score pays
the QSY cost. It is not dropped for that. Dropped spots are: off the bands
the operator selected, older than 15 minutes, no grid, out of range for that
band, or not needed under the Goal (already worked, or a mode the Goal
does not count).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wims.engine import scoring as S
from wims.engine.geo import distance_km
from wims.integrations.cluster.modes import canonical_mode, infer_mode
from wims.integrations.cluster.parse import ParsedSpot
from wims.integrations.cluster.ranges import distance_fit, in_range, spotter_near_amount
from wims.integrations.cluster.settings import DEFAULT_TTL_S, all_bands


@dataclass
class OnAir:
    """One live WSJT-X instance, used only for the on-band / QSY flag."""

    band: str
    mode: str


@dataclass
class SpotGroup:
    call: str
    band: str
    mode: str
    freq_hz: int
    comment: str
    grid: str | None
    spotters: dict[str, float] = field(default_factory=dict)
    last_seen: float = 0.0
    hhmm: str = ""


class SpotBook:
    """One row per call and band. Later spots refresh the row."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], SpotGroup] = {}

    def add(self, spot: ParsedSpot, now: float) -> None:
        mode = infer_mode(spot.freq_hz, spot.comment, spot.band)
        key = (spot.call, spot.band)
        row = self._rows.get(key)
        if row is None:
            row = SpotGroup(
                call=spot.call, band=spot.band, mode=mode, freq_hz=spot.freq_hz,
                comment=spot.comment, grid=spot.grid, last_seen=now, hhmm=spot.hhmm,
            )
            self._rows[key] = row
        else:
            row.mode = mode
            row.freq_hz = spot.freq_hz
            row.comment = spot.comment
            row.last_seen = now
            row.hhmm = spot.hhmm
            if spot.grid and (not row.grid or len(spot.grid) >= len(row.grid)):
                row.grid = spot.grid
        row.spotters[spot.spotter] = now

    def prune(self, now: float, ttl: float = DEFAULT_TTL_S) -> None:
        dead = [key for key, row in self._rows.items() if now - row.last_seen > ttl]
        for key in dead:
            del self._rows[key]

    def rows(self) -> list[SpotGroup]:
        return list(self._rows.values())

    def clear(self) -> None:
        self._rows.clear()


def on_band(band: str, mode: str, operations: list[OnAir] | None) -> bool:
    want = canonical_mode(mode)
    for op in operations or []:
        if op.band == band and op.mode and canonical_mode(op.mode) == want:
            return True
    return False


def short_why(verdict, grid: str | None) -> str:
    if getattr(verdict, "is_new_mult", False):
        square = (grid or "")[:4]
        return f"new {square}" if square else "new mult"
    if (getattr(verdict, "chase", "") or "") == "unconfirmed":
        return "unconfirmed"
    reason = (getattr(verdict, "need_reason", "") or "").lower()
    if "new call" in reason or ("call" in reason and "new" in reason):
        return "new call"
    return "needed"


def _mhz(freq_hz: int) -> str:
    return f"{freq_hz / 1_000_000:.3f}"


def _spotter_key(call: str) -> str:
    return (call or "").upper().split("-", 1)[0].strip()


def status_line(*, enabled: bool, phase: str, host: str, port: int,
                callsign: str, retry_s: float, reason: str,
                spot_count: int, needed_count: int,
                bands_empty: bool, have_grid: bool) -> str:
    """One line for Operate. A failure names what to do next."""
    if not enabled:
        return "Cluster: off. Turn it on in Setup."
    if bands_empty:
        return "Cluster: no bands are selected. Choose bands in Setup."
    if phase == "need_call":
        return "Cluster: waiting for your callsign. WSJT-X has not sent one yet."
    if phase in {"off", "connecting"}:
        return f"Cluster: connecting to {host}..."
    if phase == "refused":
        who = callsign or "that callsign"
        return f"Cluster: {host} refused {who}. Check the callsign in WSJT-X."
    if phase == "extra":
        return (
            "Cluster: the node asked for more than a callsign. "
            "WIMS only sends your callsign. Pick another node in Setup."
        )
    if phase == "retry":
        wait = f" Trying again in {max(0, int(retry_s))} seconds." if retry_s else ""
        if reason == "dns":
            return (
                f"Cluster: the name {host} did not resolve. "
                f"Check the node address in Setup.{wait}"
            )
        if reason == "refused_port":
            return (
                f"Cluster: {host} refused the connection on port {port}. "
                f"Check the port in Setup.{wait}"
            )
        if reason == "quiet":
            return f"Cluster: {host} went quiet.{wait}"
        return (
            f"Cluster: can't reach {host} port {port}. "
            f"Check the node address in Setup.{wait}"
        )
    if not have_grid:
        return (
            f"Cluster: connected, {spot_count} spots. "
            "No grid from WSJT-X yet, so range cannot be checked."
        )
    return f"Cluster: connected, {spot_count} spots, {needed_count} needed"


def status_detail(*, host: str, port: int, callsign: str, qsy_cost: int,
                  bands, ttl_s: int, drops: dict, weights: dict) -> str:
    if bands is None:
        band_words = "every amateur band"
    elif not bands:
        band_words = "no bands"
    else:
        band_words = ", ".join(bands)
    parts = [
        f"Node {host} port {port}.",
        f"Login {callsign}." if callsign else "No callsign yet.",
        "Read-only. WIMS sends only your callsign, then listens.",
        "It does not post spots. A click does not transmit or retune a radio.",
        "VE7CC asks for one connection per callsign.",
        f"Spots drop off after {max(1, ttl_s // 60)} minutes.",
        "QSY means no live WSJT-X is on that band and mode. On band means one is.",
        f"QSY cost is {qsy_cost} points.",
        f"Bands: {band_words}.",
    ]
    if drops:
        bits = []
        labels = (
            ("no_grid", "no grid"),
            ("range", "out of range"),
            ("worked", "already worked"),
            ("no_station_grid", "station grid unknown"),
        )
        for key, label in labels:
            n = int(drops.get(key) or 0)
            if n:
                bits.append(f"{n} {label}")
        if bits:
            parts.append("Not listed: " + ", ".join(bits) + ".")
    named = ", ".join(f"{name} {value:g}" for name, value in weights.items())
    parts.append("Weights: " + named + ".")
    return " ".join(parts)


def build_list(
    groups: list[SpotGroup],
    *,
    now: float,
    ttl_s: float,
    our_grid: str | None,
    allowed: set[str] | None,
    operations: list[OnAir] | None,
    classify,
    grid_for=None,
    rover_for=None,
    spotter_grid=None,
    qsy_cost: float = 8,
) -> tuple[list[dict], dict]:
    """Rows for the Spotted list, and counts of why others were left off.

    ``spot_count`` is every fresh spot on a selected band. ``needed`` is the
    list the operator sees.
    """
    weights = S.cluster_weights(qsy_cost)
    rows: list[dict] = []
    drops = {"no_grid": 0, "range": 0, "worked": 0, "no_station_grid": 0, "spot_count": 0}
    home = (our_grid or "").strip().upper() or None
    for group in groups:
        age = now - group.last_seen
        if age > ttl_s or age < -5:
            continue
        if allowed is not None and group.band not in allowed:
            continue
        drops["spot_count"] += 1
        grid = (group.grid or "").strip().upper() or None
        if grid is None and grid_for is not None:
            remembered = grid_for(group.call)
            if remembered:
                grid = str(remembered).strip().upper() or None
        if not home:
            drops["no_station_grid"] += 1
            continue
        if not grid:
            drops["no_grid"] += 1
            continue
        km = distance_km(home, grid)
        if not in_range(km, group.band, group.mode):
            drops["range"] += 1
            continue
        verdict = classify(group.call, group.band, grid, group.mode)
        if getattr(verdict, "is_dupe", False):
            drops["worked"] += 1
            continue
        needs_qsy = not on_band(group.band, group.mode, operations)
        rover = "/R" in group.call.upper()
        if not rover and rover_for is not None:
            rover = bool(rover_for(group.call))
        near_amt = 0.0
        near_detail = ""
        best = None
        best_call = ""
        if spotter_grid is not None:
            for spotter in group.spotters:
                square = spotter_grid(_spotter_key(spotter))
                if not square:
                    continue
                dist = distance_km(home, str(square))
                if dist is None:
                    continue
                if best is None or dist < best:
                    best = dist
                    best_call = _spotter_key(spotter)
        if best is not None:
            near_amt = spotter_near_amount(best)
            near_detail = f"{best_call} {int(best)} km away"
        fit = distance_fit(km, group.band, group.mode)
        scored = S.score_spot(S.SpotFeatures(
            is_new_mult=bool(getattr(verdict, "is_new_mult", False)),
            chase=getattr(verdict, "chase", "") or "",
            is_rover=rover,
            needs_qsy=needs_qsy,
            age_s=age,
            ttl_s=ttl_s,
            spotter_count=len(group.spotters),
            spotter_near=near_amt,
            distance_fit=fit,
            need_detail=getattr(verdict, "need_reason", "") or "",
            mult_detail=getattr(verdict, "mult_reason", "") or "",
            near_detail=near_detail,
            distance_detail=f"{int(km)} km",
        ), weights)
        why = short_why(verdict, grid)
        full = (getattr(verdict, "need_reason", "") or
                getattr(verdict, "mult_reason", "") or why)
        rows.append({
            "call": group.call,
            "grid": grid,
            "band": group.band,
            "mode": group.mode,
            "freq_hz": group.freq_hz,
            "freq": _mhz(group.freq_hz),
            "where": "QSY" if needs_qsy else "on band",
            "needs_qsy": needs_qsy,
            "why": why,
            "why_full": full,
            "score": scored.total,
            "age_s": int(max(0, age)),
            "spotters": len(group.spotters),
            "spotter_calls": sorted(group.spotters),
            "km": int(round(km or 0)),
            "factors": [
                {"name": f.name, "contribution": f.contribution, "detail": f.detail}
                for f in scored.factors
            ],
        })
    rows.sort(key=lambda row: (-row["score"], row["age_s"], row["call"]))
    return rows, drops


def band_choices(selected) -> list[dict]:
    chosen = None if selected == "all" else set(selected or [])
    out = []
    for band in all_bands():
        out.append({
            "band": band,
            "on": chosen is None or band in chosen,
        })
    return out
