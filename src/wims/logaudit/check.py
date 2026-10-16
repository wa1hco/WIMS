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

"""Compare ADIF logs. Read-only. Does not rewrite any file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wims.adif import load_qsos, qso_time

WINDOW_S = 180.0


@dataclass
class AuditQso:
    call: str
    band: str
    mode: str
    when: float | None
    time_text: str
    grid: str | None
    source: str

    def row(self) -> dict:
        return {
            "call": self.call,
            "band": self.band,
            "mode": self.mode,
            "time": self.time_text,
            "grid": self.grid or "",
            "source": self.source,
        }


@dataclass
class SourceInfo:
    name: str
    path: str
    count: int = 0
    status: str = "ok"
    detail: str = ""


@dataclass
class Report:
    sources: list[SourceInfo] = field(default_factory=list)
    window: str = "all contacts"
    matched: list[dict] = field(default_factory=list)
    only: list[dict] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unreadable: bool = False

    def exit_code(self) -> int:
        if self.unreadable:
            return 2
        if self.only or self.disagreements or self.duplicates:
            return 1
        return 0


def _grid4(grid: str | None) -> str | None:
    g = (grid or "").strip().upper()
    if not g:
        return None
    return g[:4]


def _when_from_logged(q) -> tuple[str, float | None]:
    fields = {
        "qso_date": q.qso_date or "",
        "time_on": q.time_on or "",
    }
    if fields["qso_date"]:
        return qso_time(fields)
    ts = (q.timestamp or "").strip()
    if not ts:
        return "?", None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d %H%M%S"):
        try:
            dt = datetime.strptime(ts[:19], fmt).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M"), dt.timestamp()
        except ValueError:
            continue
    return ts, None


def qsos_from_logged(qsos, source: str) -> list[AuditQso]:
    out = []
    for q in qsos:
        text, when = _when_from_logged(q)
        out.append(AuditQso(
            call=(q.call or "").upper().replace(" ", ""),
            band=q.band or "?",
            mode=(q.submode or q.mode or "").upper(),
            when=when,
            time_text=text,
            grid=_grid4(q.grid),
            source=source,
        ))
    return out


def load_adif_source(path: str | Path, name: str) -> tuple[SourceInfo, list[AuditQso]]:
    p = Path(path)
    info = SourceInfo(name=name, path=str(p))
    if not p.is_file():
        info.status = "unreadable"
        info.detail = "not found"
        return info, []
    qsos, problem = load_qsos(p)
    if problem:
        info.status = problem
        info.detail = problem
        return info, []
    info.count = len(qsos)
    info.detail = f"{info.count} contacts"
    return info, qsos_from_logged(qsos, name)


def _close(a: AuditQso, b: AuditQso) -> bool:
    if a.when is None or b.when is None:
        return False
    return abs(a.when - b.when) <= WINDOW_S


def _same_key(a: AuditQso, b: AuditQso) -> bool:
    return a.call == b.call and a.band == b.band and a.mode == b.mode and _close(a, b)


def _internal_dupes(rows: list[AuditQso]) -> list[dict]:
    used = [False] * len(rows)
    found = []
    for i, a in enumerate(rows):
        if used[i]:
            continue
        group = [a]
        used[i] = True
        for j in range(i + 1, len(rows)):
            if used[j]:
                continue
            if _same_key(a, rows[j]):
                used[j] = True
                group.append(rows[j])
        if len(group) > 1:
            found.append({
                "call": a.call, "band": a.band, "mode": a.mode,
                "time": a.time_text, "source": a.source, "count": len(group),
            })
    return found


def _is_lotw(name: str, lotw_names: set[str]) -> bool:
    return name in lotw_names or name.lower().startswith("lotw")


def compare(groups: list[tuple[SourceInfo, list[AuditQso]]], *, lotw_names: set[str]) -> Report:
    """Pair contacts across sources. One record is used at most once."""
    report = Report()
    report.sources = [info for info, _rows in groups]
    if any(s.status in {"unreadable", "locked"} for s in report.sources):
        report.unreadable = True
    rows: list[AuditQso] = []
    for info, group_rows in groups:
        if info.status != "ok":
            continue
        report.duplicates.extend(_internal_dupes(group_rows))
        rows.extend(group_rows)
    real_sources = [
        info.name for info, _rows in groups
        if info.status == "ok" and not _is_lotw(info.name, lotw_names)
    ]
    used = [False] * len(rows)
    for i, seed in enumerate(rows):
        if used[i]:
            continue
        cluster = [seed]
        used[i] = True
        seen = {seed.source}
        for j in range(i + 1, len(rows)):
            if used[j]:
                continue
            other = rows[j]
            if other.source in seen:
                continue
            if not _same_key(seed, other):
                continue
            used[j] = True
            seen.add(other.source)
            cluster.append(other)
        if len(cluster) == 1:
            used[i] = False
            continue
        grids = {q.grid for q in cluster if q.grid}
        if len(grids) > 1:
            report.disagreements.append({
                "call": seed.call,
                "band": seed.band,
                "mode": seed.mode,
                "time": seed.time_text,
                "grid": "   ".join(f"{q.source} {q.grid}" for q in cluster if q.grid),
                "source": seed.source,
                "detail": "grid",
            })
        else:
            report.matched.append({
                "call": seed.call,
                "band": seed.band,
                "mode": seed.mode,
                "time": seed.time_text,
                "grid": next(iter(grids), "") if grids else "",
                "source": " + ".join(q.source for q in cluster),
            })
            if any(q.grid is None for q in cluster) and grids:
                missing = ", ".join(q.source for q in cluster if q.grid is None)
                report.notes.append(
                    f"{seed.time_text} {seed.call} {seed.band} {seed.mode}: {missing} has no grid."
                )
    # Mode clash: same call, band, and time, different mode, still unpaired.
    for i, seed in enumerate(rows):
        if used[i]:
            continue
        for j in range(i + 1, len(rows)):
            if used[j]:
                continue
            other = rows[j]
            if other.source == seed.source:
                continue
            if seed.call != other.call or seed.band != other.band or not _close(seed, other):
                continue
            if seed.mode == other.mode:
                continue
            used[i] = True
            used[j] = True
            report.disagreements.append({
                "call": seed.call,
                "band": seed.band,
                "mode": f"{seed.mode} vs {other.mode}",
                "time": seed.time_text,
                "grid": "",
                "source": seed.source,
                "detail": f"mode  {seed.source} {seed.mode}   {other.source} {other.mode}",
            })
            break
        else:
            continue
    for i, row in enumerate(rows):
        if not used[i]:
            _file_only(report, row, real_sources, lotw_names)
    return report


def _file_only(report: Report, row: AuditQso, real_sources: list[str], lotw_names: set[str]) -> None:
    if _is_lotw(row.source, lotw_names):
        report.notes.append(
            f"Only in {row.source}: {row.time_text} {row.call} {row.band} {row.mode}"
        )
        return
    others = [name for name in real_sources if name != row.source]
    if not others:
        if lotw_names:
            report.notes.append(
                f"Not in this LoTW download: {row.time_text} {row.call} {row.band} {row.mode}"
            )
        return
    report.only.append(row.row())


def render_text(report: Report) -> str:
    lines = ["WIMS log check", "==============", "Sources"]
    for src in report.sources:
        if src.status == "ok":
            mark = "[OK]"
            tail = src.detail or f"{src.count} contacts"
        elif src.status == "note":
            mark = "[! ]"
            tail = src.detail
        else:
            mark = "[XX]" if src.status in {"unreadable", "locked"} else "[! ]"
            tail = src.detail or src.status
        path = f"  {src.path}" if src.path else ""
        lines.append(f"  {mark} {src.name}{path}  ({tail})")
    lines.append("")
    lines.append(f"Window: {report.window}")
    lines.append("")
    only_by: dict[str, list] = {}
    for row in report.only:
        only_by.setdefault(row["source"], []).append(row)
    lines.append(f"Matched: {len(report.matched)}")
    for name, rows in only_by.items():
        lines.append(f"Only in {name}: {len(rows)}")
    lines.append(f"Disagreements: {len(report.disagreements)}")
    lines.append(f"Duplicates inside one file: {len(report.duplicates)}")
    for name, rows in only_by.items():
        lines.append("")
        lines.append(f"Only in {name}")
        for row in rows:
            grid = f"  {row['grid']}" if row.get("grid") else ""
            lines.append(
                f"  {row['time']}  {row['call']}  {row['band']}  {row['mode']}{grid}"
            )
    if report.disagreements:
        lines.append("")
        lines.append("Disagreements")
        for row in report.disagreements:
            lines.append(
                f"  {row['time']}  {row['call']}  {row['band']}  {row['mode']}"
            )
            if row.get("detail") == "grid":
                lines.append(f"    grid  {row.get('grid') or ''}")
            elif row.get("detail"):
                lines.append(f"    {row['detail']}")
    if report.notes:
        lines.append("")
        lines.append("Notes")
        for note in report.notes:
            lines.append(f"  {note}")
    return "\n".join(lines) + "\n"


def to_json(report: Report) -> dict:
    return {
        "sources": [
            {"name": s.name, "path": s.path, "count": s.count, "status": s.status, "detail": s.detail}
            for s in report.sources
        ],
        "window": report.window,
        "matched": report.matched,
        "only": report.only,
        "disagreements": report.disagreements,
        "duplicates": report.duplicates,
        "notes": report.notes,
    }
