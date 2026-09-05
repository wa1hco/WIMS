# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Same-band inhibit target discovery — pure table, no I/O.

Correlate plane-A Status (band from dial frequency) with InhibitStatus type 17
(inhibit UDP port). Addressing is host from the UDP source address + inhibit_port.

Policy for the Key path: ``targets_for_band(live_band)`` — only instances whose
Status band matches and that have announced an inhibit port.
"""

from __future__ import annotations

from dataclasses import dataclass

# Plane A is a single port (decision 2026-09-05). All band labels join 2237.
PLANE_A_PORT = 2237
BAND_STREAM_PORTS: dict[str, int] = {
    "6m": PLANE_A_PORT,
    "2m": PLANE_A_PORT,
    "1.25m": PLANE_A_PORT,
    "70cm": PLANE_A_PORT,
    "33cm": PLANE_A_PORT,
    "23cm": PLANE_A_PORT,
}

DEFAULT_STALE_S = 90.0  # drop rows quiet this long


@dataclass
class DigiTarget:
    instance_id: str
    host: str
    inhibit_port: int
    band: str


@dataclass
class _Row:
    host: str = ""
    band: str | None = None
    inhibit_port: int | None = None
    status_at: float = -1.0  # <0 = never seen
    inhibit_at: float = -1.0
    inhibited: bool = False
    source_station: str = ""


class InhibitTargetTable:
    """In-memory id → host/band/inhibit_port map."""

    def __init__(self, *, stale_s: float = DEFAULT_STALE_S):
        self.stale_s = float(stale_s)
        self._rows: dict[str, _Row] = {}

    def on_status(self, instance_id: str, band: str, host: str, now: float) -> None:
        if not instance_id or not host or not band or band == "?":
            return
        row = self._rows.setdefault(instance_id, _Row())
        row.host = host
        row.band = band
        row.status_at = now

    def on_inhibit_status(
        self,
        instance_id: str,
        inhibit_port: int,
        host: str,
        now: float,
        *,
        inhibited: bool = False,
        source_station: str = "",
    ) -> None:
        if not instance_id or not host:
            return
        port = int(inhibit_port)
        if port <= 0 or port > 65535:
            return
        row = self._rows.setdefault(instance_id, _Row())
        row.host = host
        row.inhibit_port = port
        row.inhibit_at = now
        row.inhibited = bool(inhibited)
        row.source_station = source_station or ""

    def _alive(self, row: _Row, now: float) -> bool:
        times = [t for t in (row.status_at, row.inhibit_at) if t >= 0.0]
        if not times:
            return False
        return (now - max(times)) <= self.stale_s

    def targets_for_band(self, band: str | None, now: float) -> list[DigiTarget]:
        """Resolved inhibit destinations on ``band`` (require Status band + type-17 port)."""
        if not band:
            return []
        out: list[DigiTarget] = []
        for iid, row in self._rows.items():
            if not self._alive(row, now):
                continue
            if row.band != band:
                continue
            if row.inhibit_port is None or not row.host:
                continue
            out.append(DigiTarget(iid, row.host, row.inhibit_port, row.band))
        out.sort(key=lambda t: (t.host, t.inhibit_port, t.instance_id))
        return out

    def sweep(self, now: float) -> int:
        """Drop stale rows. Returns number removed."""
        dead = [iid for iid, row in self._rows.items() if not self._alive(row, now)]
        for iid in dead:
            del self._rows[iid]
        return len(dead)

    def snapshot(self, now: float) -> list[dict]:
        rows = []
        for iid, row in sorted(self._rows.items()):
            rows.append({
                "id": iid,
                "host": row.host,
                "band": row.band,
                "inhibit_port": row.inhibit_port,
                "alive": self._alive(row, now),
                "inhibited": row.inhibited,
                "source_station": row.source_station,
            })
        return rows


def stream_port_for_band(band: str | None) -> int | None:
    """Multicast UDP port for a band label, or None if unknown."""
    if not band:
        return None
    return BAND_STREAM_PORTS.get(band)
