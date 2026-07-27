# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""In-memory rotator registry — status + point/stop (plan §3.8 / §2.10).

Agents (or a local SimRotator) push position; the console commands point/stop
through the site server. Soft az limits enforced here before any backend move.
"""

from __future__ import annotations

import time
from typing import Any

from wims.integrations.rotator.protocol import RotatorState
from wims.integrations.rotator.sim import SimRotator


class RotatorRegistry:
    """Thread-safety is the caller's job (LiveFleet holds the lock)."""

    def __init__(self, *, settle_tol: float = 2.0, stale_after: float = 15.0):
        self._states: dict[str, RotatorState] = {}
        self._sims: dict[str, SimRotator] = {}
        self.settle_tol = settle_tol
        self.stale_after = stale_after

    def ensure_sim(self, rid: str, *, az: float = 0.0,
                   instances: list[str] | None = None,
                   label: str | None = None,
                   soft_min: float = 0.0, soft_max: float = 360.0) -> RotatorState:
        """Create or return a server-local simulated rotator (lab / validate)."""
        rid = (rid or "").strip() or "SIM-ROT"
        if rid not in self._sims:
            self._sims[rid] = SimRotator(az=az)
        if rid not in self._states:
            self._states[rid] = RotatorState(
                id=rid, az=float(az) % 360.0, link_ok=True, health="OK",
                source="sim", instances=list(instances or []),
                label=label or rid, soft_min=soft_min, soft_max=soft_max,
                ts=time.time(),
            )
        else:
            st = self._states[rid]
            if instances is not None:
                st.instances = list(instances)
            if label:
                st.label = label
            st.soft_min, st.soft_max = soft_min, soft_max
        return self._states[rid]

    def ingest_report(self, items: list | None, *, agent_id: str | None,
                      now: float | None = None) -> int:
        """Merge rotator status objects from a seat agent report. Returns count."""
        if not items:
            return 0
        now = time.time() if now is None else now
        n = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            rid = str(raw.get("id") or "").strip()
            if not rid:
                continue
            st = self._states.get(rid) or RotatorState(id=rid)
            st.source = "agent"
            st.agent_id = agent_id
            st.ts = now
            if raw.get("az") is not None:
                try:
                    st.az = float(raw["az"]) % 360.0
                except (TypeError, ValueError):
                    pass
            if raw.get("el") is not None:
                try:
                    st.el = float(raw["el"])
                except (TypeError, ValueError):
                    pass
            if raw.get("target_az") is not None:
                try:
                    st.target_az = float(raw["target_az"]) % 360.0
                except (TypeError, ValueError):
                    pass
            if "moving" in raw:
                st.moving = bool(raw["moving"])
            st.link_ok = bool(raw.get("link_ok", True))
            st.health = str(raw.get("health") or ("OK" if st.link_ok else "FAULT"))
            if raw.get("instances") is not None:
                st.instances = [str(x) for x in (raw.get("instances") or [])]
            if raw.get("label"):
                st.label = str(raw["label"])
            if raw.get("soft_min") is not None:
                try:
                    st.soft_min = float(raw["soft_min"])
                except (TypeError, ValueError):
                    pass
            if raw.get("soft_max") is not None:
                try:
                    st.soft_max = float(raw["soft_max"])
                except (TypeError, ValueError):
                    pass
            # Recompute moving from az/target when agent omitted the flag.
            if st.target_az is not None and st.az is not None and "moving" not in raw:
                d = abs((st.target_az - st.az + 180.0) % 360.0 - 180.0)
                st.moving = d > self.settle_tol
            self._states[rid] = st
            n += 1
        return n

    def tick_sims(self, now: float | None = None) -> None:
        """Advance local simulators and refresh their RotatorState."""
        now = time.time() if now is None else now
        for rid, sim in self._sims.items():
            az, el = sim.read()
            st = self._states.get(rid)
            if st is None:
                continue
            st.az = az
            st.el = el
            st.target_az = sim.target_az
            st.moving = sim.moving
            st.link_ok = True
            st.health = "OK"
            st.source = "sim"
            st.ts = now

    def for_instance(self, instance_id: str) -> RotatorState | None:
        """First rotator that lists this WSJT-X instance id."""
        if not instance_id:
            return None
        for st in self._states.values():
            if instance_id in (st.instances or []):
                return st
        return None

    def get(self, rid: str) -> RotatorState | None:
        return self._states.get(rid)

    def all(self) -> list[RotatorState]:
        return list(self._states.values())

    def point(self, rid: str, az: float, *, now: float | None = None) -> dict:
        """Command move to az. Enforces soft limits. Human-initiated only."""
        now = time.time() if now is None else now
        st = self._states.get(rid)
        if st is None:
            return {"ok": False, "error": "unknown_rotator",
                    "detail": f"No rotator id={rid!r}."}
        if not st.link_ok and st.source != "sim":
            return {"ok": False, "error": "link_down",
                    "detail": f"Rotator {rid} link not OK."}
        clamped, reason = st.clamp_az(az)
        st.target_az = clamped
        st.ts = now
        if rid in self._sims:
            self._sims[rid].move_az(clamped)
            st.moving = True
            st.health = "OK"
            st.link_ok = True
        else:
            # Agent-owned: mark target; agent must pick up command (or TCP later).
            st.moving = True
            st.health = st.health if st.health != "DEAD" else "OK"
        out: dict[str, Any] = {
            "ok": True, "rotator": rid, "az": clamped, "moving": True,
        }
        if reason:
            out["clamped"] = True
            out["detail"] = reason
        return out

    def stop(self, rid: str | None = None, *, now: float | None = None) -> dict:
        """Stop one rotator or all. Returns list of halted ids."""
        now = time.time() if now is None else now
        targets = [rid] if rid else list(self._states)
        halted = []
        for r in targets:
            st = self._states.get(r)
            if st is None:
                continue
            if r in self._sims:
                self._sims[r].stop()
            st.target_az = st.az
            st.moving = False
            st.ts = now
            halted.append(r)
        return {"ok": True, "halted": halted}

    def refresh_health(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for st in self._states.values():
            if st.source == "sim":
                continue
            age = now - (st.ts or 0)
            if age > self.stale_after * 2:
                st.health = "DEAD"
                st.link_ok = False
            elif age > self.stale_after:
                st.health = "STALE"
