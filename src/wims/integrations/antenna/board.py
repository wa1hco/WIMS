# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Live antennas reported by seat agents (plan §2.10).

The site server stores the public view. It does not open rotctld, a
serial port, or a switch.
"""

from __future__ import annotations

import time

from wims.integrations.antenna.model import public_antennas


class AntennaBoard:
    """Last antenna report from each seat agent. The caller holds the lock."""

    def __init__(self, *, stale_after: float = 15.0) -> None:
        self._by_agent: dict[str, dict] = {}
        self.stale_after = stale_after

    def ingest(self, items: list | None, *, agent_id: str | None,
               now: float | None = None) -> int:
        """Replace this agent's antennas. ``None`` leaves them alone.

        An empty list means the antenna side is off, so that agent's rows
        drop. A down rotator arrives with a null heading.
        """
        if items is None or not isinstance(items, list) or not agent_id:
            return 0
        now = time.time() if now is None else now
        if not items:
            self._by_agent.pop(agent_id, None)
            return 0
        cleaned = public_antennas(items)
        self._by_agent[agent_id] = {"ts": now, "antennas": cleaned}
        return len(cleaned)

    def snapshot(self, now: float | None = None) -> list[dict]:
        """Antennas for the live state. A quiet agent loses the heading."""
        now = time.time() if now is None else now
        out: list[dict] = []
        for agent_id in sorted(self._by_agent):
            block = self._by_agent[agent_id]
            age = now - float(block.get("ts") or now)
            stale = age > self.stale_after
            for ant in block.get("antennas") or []:
                devices = []
                for dev in ant.get("devices") or []:
                    row = dict(dev)
                    if stale:
                        row["az"] = None
                        row["el"] = None
                        row["link"] = "down"
                        row["link_ok"] = False
                        row["connection"] = "stale"
                        row["moving"] = False
                        if not row.get("detail"):
                            row["detail"] = "Heading unknown."
                    devices.append(row)
                out.append({
                    "id": ant.get("id"),
                    "name": ant.get("name") or "Antenna",
                    "agent_id": agent_id,
                    "age": round(age, 1),
                    "devices": devices,
                })
        return out
