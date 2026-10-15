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

"""``python -m wims.logaudit`` — compare logs. No arguments discovers local ADIF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wims.logaudit.check import (
    Report,
    SourceInfo,
    compare,
    load_adif_source,
    render_text,
    to_json,
)


def _since_filter(rows, since: str):
    if not since:
        return rows
    day = since.replace("-", "")[:8]
    kept = []
    for row in rows:
        # time_text starts YYYY-MM-DD when the ADIF date parsed.
        stamp = (row.time_text or "").replace("-", "")[:8]
        if stamp and stamp < day:
            continue
        kept.append(row)
    return kept


def build_report(argv: list[str] | None = None) -> Report:
    ap = argparse.ArgumentParser(
        prog="python -m wims.logaudit",
        description="Compare WSJT-X, N1MM, GridTracker, and other ADIF logs. Read-only.",
    )
    ap.add_argument("--adif", action="append", default=[], metavar="PATH")
    ap.add_argument("--n1mm-db", default="", metavar="PATH")
    ap.add_argument("--contest-nr", type=int, default=None)
    ap.add_argument("--gridtracker", action="append", default=[], metavar="PATH")
    ap.add_argument("--gridtracker-auto", action="store_true")
    ap.add_argument("--lotw", default="", metavar="PATH")
    ap.add_argument("--since", default="", metavar="YYYY-MM-DD")
    ap.add_argument("--json", dest="json_path", default="", metavar="PATH")
    ap.add_argument("--wsjtx-auto", action="store_true",
                    help="Discover local WSJT-X logs (also the default when no path is given).")
    args = ap.parse_args(argv)

    explicit = bool(args.adif or args.n1mm_db or args.gridtracker or args.lotw)
    groups = []
    lotw_names: set[str] = set()
    notes = []

    if args.wsjtx_auto or not explicit:
        from wims.integrations.wsjtx_logs import discover_access, seed_files
        from wims.rules.choice import load_logs
        logs = load_logs()
        files = seed_files(logs=logs)
        if not files:
            info = SourceInfo(
                name="WSJT-X", path="", status="note",
                detail="no wsjtx_log.adi found",
            )
            groups.append((info, []))
            notes.append("No WSJT-X log found.")
        for path in files:
            access = discover_access(logs=logs)
            label = path.parent.name or "WSJT-X"
            for row in access:
                if row.path == str(path) or row.path == str(Path(path)):
                    label = f"WSJT-X {row.instance}"
                    break
            info, rows = load_adif_source(path, label)
            groups.append((info, _since_filter(rows, args.since)))

    for path in args.adif:
        info, rows = load_adif_source(path, f"ADIF {Path(path).name}")
        groups.append((info, _since_filter(rows, args.since)))

    if args.n1mm_db:
        info, rows = _load_n1mm(args.n1mm_db, args.contest_nr)
        groups.append((info, _since_filter(rows, args.since)))

    gt_paths = list(args.gridtracker)
    if args.gridtracker_auto or not explicit:
        from wims.integrations.wsjtx_logs import discover_gridtracker_adif
        auto = discover_gridtracker_adif()
        if not auto and (args.gridtracker_auto or not explicit):
            notes.append("GridTracker not found — pass --gridtracker with the ADIF path.")
        for path in auto:
            if str(path) not in gt_paths:
                gt_paths.append(str(path))
    for path in gt_paths:
        info, rows = load_adif_source(path, f"GridTracker {Path(path).name}")
        groups.append((info, _since_filter(rows, args.since)))

    if args.lotw:
        info, rows = load_adif_source(args.lotw, "LoTW")
        lotw_names.add("LoTW")
        groups.append((info, _since_filter(rows, args.since)))
    elif not args.lotw:
        notes.append("LoTW file not provided — confirmation was not checked.")

    report = compare(groups, lotw_names=lotw_names)
    report.notes = notes + report.notes
    if args.since:
        report.window = f"since {args.since}"
    report.json_path = args.json_path  # type: ignore[attr-defined]
    return report


def _load_n1mm(path: str, contest_nr: int | None):
    from wims.logaudit.check import SourceInfo, qsos_from_logged
    info = SourceInfo(name="N1MM", path=path)
    if not Path(path).is_file():
        info.status = "unreadable"
        info.detail = "not found"
        return info, []
    try:
        from wims.integrations.n1mm import logdb
        qsos = logdb.read_dxlog(path, contest_nr=contest_nr)
    except Exception as exc:
        info.status = "unreadable"
        info.detail = str(exc)
        return info, []
    info.count = len(qsos)
    info.detail = f"{info.count} contacts"
    return info, qsos_from_logged(qsos, "N1MM")


def main(argv: list[str] | None = None) -> int:
    report = build_report(argv)
    text = render_text(report)
    sys.stdout.write(text)
    json_path = getattr(report, "json_path", "") or ""
    if json_path:
        Path(json_path).write_text(
            json.dumps(to_json(report), indent=2) + "\n", encoding="utf-8",
        )
    return report.exit_code()
