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

"""TX arbiter + overlap detector (plan §3.4 / §5.1 assertion harness).

The safety-critical heart of WIMS. Transmitters are grouped into **resource
groups** (a transmitter/antenna/PA chain, from the Instance Profile shared-resources
§3.14). The arbiter grants TX to **at most one instance per group at a time** — by
construction, not by timing luck — so two instances in the same group can never be
told to transmit at once. Different groups transmit concurrently by design
(multi-multi: Roy-432 + Chip-1296 + Trailer-6m all at once).

`OverlapDetector` is defence-in-depth: it watches the *observed* transmitting state
and flags any group with >1 transmitter — the "no two instances ever TX at once"
check the test bed asserts (§5.1).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field


def identity_groups(instance_id: str) -> str:
    """Default: every instance is its own group (no shared resources)."""
    return instance_id


class TxArbiter:
    def __init__(self, group_of: Callable[[str], str] = identity_groups):
        self._group_of = group_of
        self._holder: dict[str, str] = {}             # group -> instance currently granted TX
        self._queue: dict[str, list[str]] = defaultdict(list)  # group -> FIFO of waiters

    def group_of(self, instance_id: str) -> str:
        return self._group_of(instance_id)

    def holder(self, group: str) -> str | None:
        return self._holder.get(group)

    def holders(self) -> dict[str, str]:
        """All groups that currently have a granted transmitter (group -> instance)."""
        return {g: h for g, h in self._holder.items() if h is not None}

    def is_granted(self, instance_id: str) -> bool:
        return self._holder.get(self._group_of(instance_id)) == instance_id

    def queue(self, group: str) -> list[str]:
        return list(self._queue[group])

    def request(self, instance_id: str) -> bool:
        """Request TX for an instance. Returns True if granted now, False if queued.

        Idempotent: re-requesting while you hold the grant returns True.
        """
        g = self._group_of(instance_id)
        holder = self._holder.get(g)
        if holder is None:
            self._holder[g] = instance_id
            return True
        if holder == instance_id:
            return True
        if instance_id not in self._queue[g]:
            self._queue[g].append(instance_id)
        return False

    def release(self, instance_id: str) -> str | None:
        """Release TX held by an instance; promote the next queued in its group.

        Returns the newly granted instance id (or None). Releasing when you are not
        the holder is a no-op (e.g. a queued instance giving up — see `withdraw`).
        """
        g = self._group_of(instance_id)
        if self._holder.get(g) != instance_id:
            self.withdraw(instance_id)
            return None
        self._holder[g] = None
        if self._queue[g]:
            nxt = self._queue[g].pop(0)
            self._holder[g] = nxt
            return nxt
        return None

    def withdraw(self, instance_id: str) -> None:
        """Remove an instance from its group's queue (it no longer wants TX)."""
        g = self._group_of(instance_id)
        if instance_id in self._queue[g]:
            self._queue[g].remove(instance_id)


# --------------------------------------------------------------------------- #
# Overlap detector — independent observer of the *actual* transmit state.
# --------------------------------------------------------------------------- #


@dataclass
class OverlapViolation:
    group: str
    instances: list[str]
    at: float


@dataclass
class OverlapDetector:
    group_of: Callable[[str], str] = identity_groups
    _tx: set[str] = field(default_factory=set)            # instances currently transmitting
    violations: list[OverlapViolation] = field(default_factory=list)

    def observe(self, instance_id: str, transmitting: bool, now: float) -> OverlapViolation | None:
        """Record an instance's transmit state; return a violation if its group now
        has more than one transmitter."""
        if transmitting:
            self._tx.add(instance_id)
        else:
            self._tx.discard(instance_id)
        g = self.group_of(instance_id)
        in_group = [i for i in self._tx if self.group_of(i) == g]
        if len(in_group) > 1:
            v = OverlapViolation(group=g, instances=sorted(in_group), at=now)
            self.violations.append(v)
            return v
        return None

    @property
    def transmitting(self) -> set[str]:
        return set(self._tx)

    @property
    def clean(self) -> bool:
        return not self.violations
