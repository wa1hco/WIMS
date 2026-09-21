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

"""LogSource contract — seed / live / resync for Operate's log copy (§3.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

from wims.integrations.n1mm.qso import LoggedQso


@dataclass(frozen=True)
class LogSourceCandidate:
    """One discoverable log the operator may select."""

    kind: str
    label: str
    path: str | None = None
    contest_nr: int | None = None
    contest_name: str | None = None
    qso_count: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LogEvent:
    """One live change from a log backend.

    ``op`` is ``add``, ``replace``, or ``delete``.
    ``add`` / ``replace`` carry ``qso``; ``delete`` carries ``id``.
    """

    op: str
    qso: LoggedQso | None = None
    id: str | None = None


@runtime_checkable
class LogSource(Protocol):
    """Narrow backend interface. WIMS never writes the external logger."""

    @property
    def kind(self) -> str:
        """Stable id: ``n1mm``, ``wsjtx_adif``, ``adif_drop``, …"""

    @property
    def title(self) -> str:
        """Human label for Setup / status."""

    def discover(self) -> list[LogSourceCandidate]:
        """List selectable logs (may be empty)."""

    def seed(self) -> Iterable[LoggedQso]:
        """Cold-start snapshot for ``LogStore.reconcile``."""

    def resync(self) -> Iterable[LoggedQso]:
        """Full re-read for operator resync (often same as seed)."""

    def status(self) -> dict:
        """Backend health for SSE / Setup (path, filters, errors)."""
