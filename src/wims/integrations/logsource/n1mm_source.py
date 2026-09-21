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

"""N1MM+ LogSource — .s3db seed/resync + Broadcast contact XML (T1)."""

from __future__ import annotations

from pathlib import Path

from wims.integrations.logsource.base import LogEvent, LogSourceCandidate
from wims.integrations.n1mm import logdb
from wims.integrations.n1mm.qso import (
    LoggedQso,
    id_from_contactdelete,
)


class N1mmLogSource:
    """Read-only N1MM backend for Operate's ``LogStore``.

    Seed/resync: DXLOG via ``logdb.read_dxlog``.
    Live: parse Contacts Broadcast XML into ``LogEvent`` (caller applies to store).
    """

    kind = "n1mm"
    title = "N1MM+"

    def __init__(
        self,
        *,
        db_path: str | None = None,
        contest_nr: int | None = None,
        contest_name: str | None = None,
        seed_db_dir: str | None = None,
        seed_db_hint: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._contest_nr = contest_nr
        self._contest_name = contest_name
        self._seed_db_dir = seed_db_dir
        self._seed_db_hint = seed_db_hint
        self._last_error: str | None = None

    def configure(
        self,
        *,
        db_path: str | None = None,
        contest_nr: int | None = None,
        contest_name: str | None = None,
    ) -> None:
        """Set the active contest file / filter for seed and resync."""
        if db_path is not None:
            self._db_path = db_path
        if contest_nr is not None or db_path is not None:
            self._contest_nr = contest_nr
        if contest_name is not None or db_path is not None:
            self._contest_name = contest_name

    @property
    def db_path(self) -> str | None:
        return self._db_path

    @property
    def contest_nr(self) -> int | None:
        return self._contest_nr

    @property
    def contest_name(self) -> str | None:
        return self._contest_name

    def discover(self) -> list[LogSourceCandidate]:
        self._last_error = None
        try:
            disc = logdb.discover(self._seed_db_dir, self._seed_db_hint)
        except Exception as e:
            self._last_error = str(e)
            return []
        out: list[LogSourceCandidate] = []
        for c in disc.get("contests") or []:
            if isinstance(c, dict):
                d = c
            else:
                d = c.to_dict() if hasattr(c, "to_dict") else {}
            out.append(
                LogSourceCandidate(
                    kind=self.kind,
                    label=str(d.get("label") or d.get("contest_name") or "N1MM"),
                    path=d.get("db_path"),
                    contest_nr=d.get("contest_nr"),
                    contest_name=d.get("contest_name"),
                    qso_count=d.get("qso_count"),
                    extra={
                        "db_label": d.get("db_label"),
                        "scan_dirs": disc.get("scan_dirs") or [],
                    },
                )
            )
        return out

    def seed(self) -> list[LoggedQso]:
        """Cold-start read. Raises on I/O / DB errors (same as ``logdb.read_dxlog``)."""
        return self._read_dxlog(soft=False)

    def resync(self) -> list[LoggedQso]:
        """Operator resync read. Soft errors → empty list + ``status()['error']``."""
        return self._read_dxlog(soft=True)

    def _read_dxlog(self, *, soft: bool) -> list[LoggedQso]:
        self._last_error = None
        if not self._db_path:
            self._last_error = "no_active_log"
            if soft:
                return []
            raise ValueError("no_active_log")
        if not Path(self._db_path).is_file():
            self._last_error = "db_not_found"
            if soft:
                return []
            raise FileNotFoundError(self._db_path)
        try:
            return list(
                logdb.read_dxlog(
                    self._db_path,
                    contest_nr=self._contest_nr,
                    contest_name=(
                        self._contest_name if self._contest_nr is None else None
                    ),
                )
            )
        except Exception as e:
            self._last_error = str(e)
            if soft:
                return []
            raise

    def parse_live(self, xml_text: str) -> LogEvent | None:
        """Map one N1MM Contacts datagram to a ``LogEvent``, or None if ignored."""
        if not xml_text:
            return None
        low = xml_text.lower()
        try:
            if "<contactdelete" in low:
                qid = id_from_contactdelete(xml_text)
                if not qid:
                    return None
                return LogEvent(op="delete", id=qid)
            if "<contactinfo" in low or "<contactreplace" in low:
                q = LoggedQso.from_contactinfo(xml_text)
                if not q.id:
                    return None
                op = "replace" if "<contactreplace" in low else "add"
                return LogEvent(op=op, qso=q, id=q.id)
        except Exception as e:
            self._last_error = str(e)
            return None
        return None

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "db_path": self._db_path,
            "contest_nr": self._contest_nr,
            "contest_name": self._contest_name,
            "error": self._last_error,
        }
