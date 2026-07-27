# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rotator state shape shared by sim, agent reports, and the server registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RotatorState:
    """Live picture of one physical rotator (plan §2.10)."""

    id: str
    az: float | None = None
    el: float | None = None
    target_az: float | None = None
    moving: bool = False
    health: str = "UNKNOWN"       # OK | STALE | DEAD | UNKNOWN | FAULT
    link_ok: bool = False
    soft_min: float = 0.0
    soft_max: float = 360.0
    instances: list[str] = field(default_factory=list)  # WSJT-X ids mapped to this mast
    label: str | None = None
    source: str = "unknown"       # sim | agent | tcp
    agent_id: str | None = None
    ts: float = 0.0               # last update epoch

    def clamp_az(self, az: float) -> tuple[float, str | None]:
        """Apply soft limits. Returns (clamped_az, reason_or_None)."""
        a = float(az) % 360.0
        lo, hi = float(self.soft_min), float(self.soft_max)
        if lo <= hi:
            if a < lo:
                return lo, f"clamped to soft_min {lo:g}"
            if a > hi and hi < 360.0:
                return hi, f"clamped to soft_max {hi:g}"
            return a, None
        # wrap-around limit range (rare)
        return a, None


class RotatorBackend(Protocol):
    """Minimal backend: read position, move, stop (agent or server-local)."""

    def read(self) -> tuple[float | None, float | None]:
        """Return (az, el)."""
        ...

    def move_az(self, az: float) -> None:
        ...

    def stop(self) -> None:
        ...
