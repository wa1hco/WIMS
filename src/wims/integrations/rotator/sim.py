# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""In-process rotator simulator for unit tests and lab (no RF / no K3NG)."""

from __future__ import annotations

import time


class SimRotator:
    """Slews toward the last commanded az at ``rate_dps`` degrees per second."""

    def __init__(self, *, az: float = 0.0, rate_dps: float = 30.0,
                 settle_tol: float = 1.0):
        self._az = float(az) % 360.0
        self._el: float | None = None
        self._target = self._az
        self._rate = max(1.0, float(rate_dps))
        self._tol = max(0.1, float(settle_tol))
        self._t = time.monotonic()
        self.link_ok = True

    def _step(self) -> None:
        now = time.monotonic()
        dt = now - self._t
        self._t = now
        if dt <= 0:
            return
        cur, tgt = self._az, self._target
        # Shortest-path delta (-180, 180]
        d = (tgt - cur + 180.0) % 360.0 - 180.0
        if abs(d) <= self._tol:
            self._az = tgt % 360.0
            return
        step = min(abs(d), self._rate * dt)
        self._az = (cur + (step if d > 0 else -step)) % 360.0

    def read(self) -> tuple[float | None, float | None]:
        self._step()
        return self._az, self._el

    def move_az(self, az: float) -> None:
        self._target = float(az) % 360.0
        self._t = time.monotonic()

    def stop(self) -> None:
        self._step()
        self._target = self._az

    @property
    def target_az(self) -> float:
        return self._target

    @property
    def moving(self) -> bool:
        self._step()
        d = abs((self._target - self._az + 180.0) % 360.0 - 180.0)
        return d > self._tol
