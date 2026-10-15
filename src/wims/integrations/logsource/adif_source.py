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

"""WSJT-X ADIF log source. Read-only. Poll when the file changes."""

from __future__ import annotations

from pathlib import Path

from wims.adif import load_qsos
from wims.integrations.logsource.base import LogSourceCandidate
from wims.integrations.n1mm.qso import LoggedQso


class WsjtxAdifLogSource:
    """Cold-start and poll for one or more ``wsjtx_log.adi`` files.

    A shared path is the only file. Otherwise each instance file is read once
    per resolved path. WIMS never writes these files.
    """

    kind = "wsjtx_adif"
    title = "WSJT-X ADIF"

    def __init__(self, paths: list[str | Path] | None = None):
        self.paths = [Path(p) for p in (paths or [])]
        self._mtime: dict[str, float] = {}
        self._error: str | None = None
        self._count = 0

    def discover(self) -> list[LogSourceCandidate]:
        rows = []
        for path in self.paths:
            rows.append(LogSourceCandidate(
                kind=self.kind,
                label=path.name,
                path=str(path),
            ))
        return rows

    def seed(self) -> list[LoggedQso]:
        seen: set[str] = set()
        out: list[LoggedQso] = []
        errors = []
        for path in self.paths:
            qsos, problem = load_qsos(path, source="adif")
            if problem:
                errors.append(f"{path}: {problem}")
                continue
            try:
                self._mtime[str(path)] = path.stat().st_mtime
            except OSError:
                pass
            for q in qsos:
                if q.id in seen:
                    continue
                seen.add(q.id)
                out.append(q)
        self._count = len(out)
        self._error = "; ".join(errors) or None
        return out

    def resync(self) -> list[LoggedQso]:
        return self.seed()

    def poll_changed(self) -> bool:
        """True when a file's mtime moved or a new file appeared."""
        changed = False
        for path in self.paths:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            prev = self._mtime.get(key)
            if prev is None or mtime != prev:
                changed = True
                self._mtime[key] = mtime
        return changed

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "paths": [str(p) for p in self.paths],
            "qso_count": self._count,
            "error": self._error,
        }
