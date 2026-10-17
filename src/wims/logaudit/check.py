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

"""Compare ADIF logs. Read-only. Does not rewrite any file.

Pairing is grouped by call, band, and mode, then a time window. A measured
all-pairs scan took 0.08 s for 1,000 contacts, 1.9 s for 5,000, and 19.7 s
for 15,000 (two copies). Reading each of those files took about 0.3 s.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wims.adif import load_qsos, qso_time

WINDOW_S = 180.0
DETAIL_CAP = 40


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
    shared_by: list[str] = field(default_factory=list)
    cached: bool = False
    identity: str = ""


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
    missing_from: dict[str, list] = field(default_factory=dict)
    logs_read: int = 0
    shared_count: int = 0
    summary: str = ""
    elapsed_s: float = 0.0

    def exit_code(self) -> int:
        if self.unreadable:
            return 2
        if any(self.missing_from.values()) or self.only or self.disagreements or self.duplicates:
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
    info.detail = "1 contact" if info.count == 1 else f"{info.count} contacts"
    return info, qsos_from_logged(qsos, name)


def filter_since(rows: list[AuditQso], since: str) -> list[AuditQso]:
    if not since:
        return rows
    day = since.replace("-", "")[:8]
    kept = []
    for row in rows:
        stamp = (row.time_text or "").replace("-", "")[:8]
        if stamp and stamp < day:
            continue
        kept.append(row)
    return kept


def _close(a: AuditQso, b: AuditQso) -> bool:
    if a.when is None or b.when is None:
        return False
    return abs(a.when - b.when) <= WINDOW_S


def collapse_exact(rows: list[AuditQso]) -> tuple[list[AuditQso], list[dict]]:
    """Keep one copy of a contact inside the time window and count the rest."""
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        buckets[(row.call, row.band, row.mode)].append(i)
    drop: set[int] = set()
    found: list[dict] = []
    for idxs in buckets.values():
        idxs.sort(key=lambda i: (rows[i].when is None, rows[i].when or 0.0))
        used = [False] * len(idxs)
        for a_pos, i in enumerate(idxs):
            if used[a_pos]:
                continue
            seed = rows[i]
            group = [i]
            used[a_pos] = True
            if seed.when is None:
                continue
            for b_pos in range(a_pos + 1, len(idxs)):
                if used[b_pos]:
                    continue
                other = rows[idxs[b_pos]]
                if other.when is None:
                    continue
                if other.when - seed.when > WINDOW_S:
                    break
                used[b_pos] = True
                group.append(idxs[b_pos])
            if len(group) > 1:
                found.append({
                    "call": seed.call,
                    "band": seed.band,
                    "mode": seed.mode,
                    "time": seed.time_text,
                    "source": seed.source,
                    "count": len(group),
                })
                drop.update(group[1:])
    kept = [row for i, row in enumerate(rows) if i not in drop]
    return kept, found


def _is_lotw(name: str, lotw_names: set[str]) -> bool:
    return name in lotw_names or name.lower().startswith("lotw")


def _indexes(rows: list[AuditQso]):
    """Time-sorted buckets. ``when`` uses +inf when the clock did not parse."""
    by_key: dict[tuple, list[tuple[float, int]]] = defaultdict(list)
    by_call_band: dict[tuple, list[tuple[float, int]]] = defaultdict(list)
    for i, qso in enumerate(rows):
        when = qso.when if qso.when is not None else float("inf")
        by_key[(qso.call, qso.band, qso.mode)].append((when, i))
        by_call_band[(qso.call, qso.band)].append((when, i))
    for bucket in by_key.values():
        bucket.sort()
    for bucket in by_call_band.values():
        bucket.sort()
    return by_key, by_call_band


def _in_window(bucket: list[tuple[float, int]], when: float):
    lo = when - WINDOW_S
    hi = when + WINDOW_S
    left = bisect_left(bucket, (lo, -1))
    for pos in range(left, len(bucket)):
        stamp, idx = bucket[pos]
        if stamp > hi:
            break
        yield stamp, idx


def _partners(seed_i: int, seed: AuditQso, rows: list[AuditQso], bucket, used: list[bool]) -> list[int]:
    if seed.when is None:
        return []
    best: dict[str, int] = {}
    for _stamp, idx in _in_window(bucket, seed.when):
        if idx <= seed_i or used[idx]:
            continue
        src = rows[idx].source
        if src == seed.source:
            continue
        prev = best.get(src)
        if prev is None or idx < prev:
            best[src] = idx
    return [best[src] for src in sorted(best, key=lambda name: best[name])]


def _mode_partner(seed_i: int, seed: AuditQso, rows: list[AuditQso], bucket, used: list[bool]) -> int | None:
    if seed.when is None:
        return None
    best = None
    for _stamp, idx in _in_window(bucket, seed.when):
        if idx <= seed_i or used[idx]:
            continue
        other = rows[idx]
        if other.source == seed.source or other.mode == seed.mode:
            continue
        if best is None or idx < best:
            best = idx
    return best


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


def _fill_missing(report: Report, rows: list[AuditQso], clusters: list[list[int]],
                  real_sources: list[str], lotw_names: set[str]) -> None:
    for cluster in clusters:
        local = [rows[i] for i in cluster if not _is_lotw(rows[i].source, lotw_names)]
        if not local:
            continue
        present = {qso.source for qso in local}
        seed = local[0]
        found = ", ".join(qso.source for qso in local)
        item = {
            "call": seed.call,
            "band": seed.band,
            "mode": seed.mode,
            "time": seed.time_text,
            "grid": seed.grid or "",
            "source": seed.source,
            "found_in": found,
        }
        for name in real_sources:
            if name in present:
                continue
            report.missing_from.setdefault(name, []).append(item)


def compare(groups: list[tuple[SourceInfo, list[AuditQso]]], *, lotw_names: set[str]) -> Report:
    """Pair contacts across sources. One record is used at most once.

    Same call, band, and mode land in one bucket sorted by time, so a contact
    looks only at the few other rows inside three minutes.
    """
    report = Report()
    report.sources = [info for info, _rows in groups]
    if any(s.status in {"unreadable", "locked", "timeout"} for s in report.sources):
        report.unreadable = True
    rows: list[AuditQso] = []
    for info, group_rows in groups:
        if info.status != "ok":
            continue
        kept, dupes = collapse_exact(group_rows)
        report.duplicates.extend(dupes)
        rows.extend(kept)
    real_sources = [
        info.name for info, _rows in groups
        if info.status == "ok" and not _is_lotw(info.name, lotw_names)
    ]
    by_key, by_call_band = _indexes(rows)
    used = [False] * len(rows)
    clusters: list[list[int]] = []
    for i, seed in enumerate(rows):
        if used[i]:
            continue
        partners = _partners(i, seed, rows, by_key[(seed.call, seed.band, seed.mode)], used)
        if not partners:
            continue
        cluster = [i, *partners]
        for j in cluster:
            used[j] = True
        clusters.append(cluster)
        grids = {rows[j].grid for j in cluster if rows[j].grid}
        if len(grids) > 1:
            report.disagreements.append({
                "call": seed.call,
                "band": seed.band,
                "mode": seed.mode,
                "time": seed.time_text,
                "grid": "   ".join(
                    f"{rows[j].source} {rows[j].grid}" for j in cluster if rows[j].grid
                ),
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
                "source": " + ".join(rows[j].source for j in cluster),
            })
            if any(rows[j].grid is None for j in cluster) and grids:
                missing = ", ".join(rows[j].source for j in cluster if rows[j].grid is None)
                report.notes.append(
                    f"{seed.time_text} {seed.call} {seed.band} {seed.mode}: {missing} has no grid."
                )
    for i, seed in enumerate(rows):
        if used[i]:
            continue
        other_i = _mode_partner(i, seed, rows, by_call_band[(seed.call, seed.band)], used)
        if other_i is None:
            continue
        used[i] = True
        used[other_i] = True
        other = rows[other_i]
        clusters.append([i, other_i])
        report.disagreements.append({
            "call": seed.call,
            "band": seed.band,
            "mode": f"{seed.mode} vs {other.mode}",
            "time": seed.time_text,
            "grid": "",
            "source": seed.source,
            "detail": f"mode  {seed.source} {seed.mode}   {other.source} {other.mode}",
        })
    for i, row in enumerate(rows):
        if used[i]:
            continue
        clusters.append([i])
        _file_only(report, row, real_sources, lotw_names)
    _fill_missing(report, rows, clusters, real_sources, lotw_names)
    report.logs_read = sum(1 for src in report.sources if src.status == "ok")
    report.shared_count = sum(1 for src in report.sources if len(src.shared_by) >= 2 and src.status == "ok")
    if report.logs_read <= 0:
        report.unreadable = True
    report.summary = format_summary(report)
    return report


def _n(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def format_summary(report: Report) -> str:
    """One plain sentence, then anything the operator should do next."""
    if report.logs_read <= 0:
        lead = "No logs could be read."
    else:
        bits = [f"{_n(report.logs_read, 'log')} read"]
        if report.shared_count:
            bits.append(_n(report.shared_count, "shared file"))
        for name, rows in report.missing_from.items():
            if rows:
                bits.append(f"{_n(len(rows), 'contact')} missing from {name}")
        lead = ", ".join(bits)
        clean = (
            not any(report.missing_from.values())
            and not report.disagreements
            and not report.duplicates
            and not report.unreadable
        )
        lead += ". The logs agree." if clean else "."
    extras: list[str] = []
    if report.disagreements:
        extras.append(f"{_n(len(report.disagreements), 'contact')} with a different grid or mode.")
    extra_copies = sum(max(0, int(row.get("count") or 0) - 1) for row in report.duplicates)
    if extra_copies:
        extras.append(f"{_n(extra_copies, 'extra copy', 'extra copies')} collapsed.")
    if any(src.status == "timeout" for src in report.sources):
        extras.append(
            "A log on a shared drive did not answer. Connect that drive and check again."
        )
    if extras:
        return lead + " " + " ".join(extras)
    return lead


def _mark(src: SourceInfo) -> tuple[str, str]:
    if src.status == "ok":
        tail = src.detail or f"{src.count} contacts"
        if len(src.shared_by) >= 2:
            tail = f"{tail}; shared by {', '.join(src.shared_by)}"
        if src.cached:
            tail = f"{tail}; unchanged, not read again"
        return "[OK]", tail
    if src.status == "note":
        return "[! ]", src.detail
    if src.status in {"unreadable", "locked", "timeout"}:
        return "[XX]", src.detail or src.status
    return "[! ]", src.detail or src.status


def render_text(report: Report) -> str:
    summary = report.summary or format_summary(report)
    lines = ["WIMS log check", "==============", summary, "", "Sources"]
    for src in report.sources:
        mark, tail = _mark(src)
        path = f"  {src.path}" if src.path else ""
        lines.append(f"  {mark} {src.name}{path}  ({tail})")
    lines.append("")
    lines.append(f"Window: {report.window}")
    lines.append("")
    lines.append(f"Matched: {len(report.matched)}")
    for name, rows in report.missing_from.items():
        if rows:
            lines.append(f"Missing from {name}: {len(rows)}")
    lines.append(f"Disagreements: {len(report.disagreements)}")
    extra_copies = sum(max(0, int(row.get("count") or 0) - 1) for row in report.duplicates)
    lines.append(f"Extra copies collapsed: {extra_copies}")
    for name, rows in report.missing_from.items():
        if not rows:
            continue
        lines.append("")
        lines.append(f"Missing from {name}")
        shown = rows[:DETAIL_CAP]
        for row in shown:
            grid = f"  {row['grid']}" if row.get("grid") else ""
            found = f"  (in {row['found_in']})" if row.get("found_in") else ""
            lines.append(
                f"  {row['time']}  {row['call']}  {row['band']}  {row['mode']}{grid}{found}"
            )
        left = len(rows) - len(shown)
        if left > 0:
            lines.append(f"  And {left} more. Use Show details to filter them.")
    if report.disagreements:
        lines.append("")
        lines.append("Disagreements")
        shown = report.disagreements[:DETAIL_CAP]
        for row in shown:
            lines.append(
                f"  {row['time']}  {row['call']}  {row['band']}  {row['mode']}"
            )
            if row.get("detail") == "grid":
                lines.append(f"    grid  {row.get('grid') or ''}")
            elif row.get("detail"):
                lines.append(f"    {row['detail']}")
        left = len(report.disagreements) - len(shown)
        if left > 0:
            lines.append(f"  And {left} more.")
    if report.duplicates:
        lines.append("")
        lines.append("Extra copies collapsed")
        for row in report.duplicates[:DETAIL_CAP]:
            lines.append(
                f"  {row['time']}  {row['call']}  {row['band']}  {row['mode']}"
                f"  ×{row['count']} in {row['source']}"
            )
    if report.notes:
        lines.append("")
        lines.append("Notes")
        for note in report.notes:
            lines.append(f"  {note}")
    return "\n".join(lines) + "\n"


def ui_payload(report: Report) -> dict:
    """What Setup and the Check logs window show. Matched contacts stay out."""
    return {
        "ok": report.exit_code() == 0,
        "exit_code": report.exit_code(),
        "state": "done",
        "summary": report.summary or format_summary(report),
        "window": report.window,
        "sources": [
            {
                "name": src.name,
                "path": src.path,
                "count": src.count,
                "status": src.status,
                "detail": src.detail,
                "shared_by": list(src.shared_by),
                "cached": bool(src.cached),
            }
            for src in report.sources
        ],
        "missing": report.missing_from,
        "disagreements": report.disagreements,
        "duplicates": report.duplicates,
        "notes": report.notes,
        "matched_count": len(report.matched),
        "elapsed_s": round(report.elapsed_s, 2),
    }


def to_json(report: Report) -> dict:
    data = ui_payload(report)
    data["matched"] = report.matched
    data["only"] = report.only
    return data
