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

"""Compare logs. With no arguments, use the logs already on this PC.

Operators start this from Check logs or from Setup. The flags below are for
people changing WIMS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wims.logaudit.check import Report, render_text, to_json
from wims.logaudit.files import (
    STAT_TIMEOUT_S,
    Candidate,
    default_cache_path,
    run_audit,
    run_bounded,
)


def build_report(argv: list[str] | None = None, *, progress=None,
                  cache_path: Path | str | None = None,
                  stat_timeout: float = STAT_TIMEOUT_S) -> Report:
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
    candidates: list[Candidate] = []
    notes: list[str] = []

    if args.wsjtx_auto or not explicit:
        candidates.extend(_wsjtx_candidates(notes, timeout=stat_timeout))
    for path in args.adif:
        candidates.append(Candidate(f"ADIF {Path(path).name}", path, "adif"))
    if args.n1mm_db:
        candidates.append(Candidate("N1MM", args.n1mm_db, "n1mm", contest_nr=args.contest_nr))
    elif not explicit:
        _add_n1mm(candidates, notes)

    gt_paths = list(args.gridtracker)
    if args.gridtracker_auto or not explicit:
        gt_paths.extend(_gridtracker_paths(notes, timeout=stat_timeout, already=gt_paths))
    for path in gt_paths:
        candidates.append(Candidate(f"GridTracker {Path(path).name}", path, "adif"))

    lotw_names: set[str] = set()
    if args.lotw:
        candidates.append(Candidate("LoTW", args.lotw, "lotw"))
        lotw_names.add("LoTW")
    elif not explicit:
        notes.append("LoTW was not checked.")

    cache = default_cache_path() if cache_path is None else cache_path
    report = run_audit(
        candidates,
        cache_path=cache,
        progress=progress,
        stat_timeout=stat_timeout,
        since=args.since,
        lotw_names=lotw_names,
    )
    report.notes = notes + report.notes
    report.json_path = args.json_path  # type: ignore[attr-defined]
    return report


def _wsjtx_candidates(notes: list[str], *, timeout: float) -> list[Candidate]:
    def work() -> list[Candidate]:
        from wims.integrations.wsjtx_logs import _id_from_dir, adi_path, installed_dirs
        from wims.rules.choice import load_logs
        logs = load_logs()
        found: list[Candidate] = []
        ids: list[str] = []
        for folder in installed_dirs():
            ident = _id_from_dir(folder)
            if ident not in ids:
                ids.append(ident)
        if not ids:
            ids = ["WSJT-X"]
        overrides = logs.get("overrides") or {}
        for ident in ids:
            override = (overrides.get(ident) or "").strip()
            path = override or str(adi_path(ident))
            label = "WSJT-X" if ident in {"", "WSJT-X"} else f"WSJT-X {ident}"
            found.append(Candidate(label, path, "adif"))
        shared = (logs.get("shared_path") or "").strip()
        if shared:
            found.append(Candidate("WSJT-X shared", shared, "adif"))
        return found

    kind, value = run_bounded(work, timeout)
    if kind == "timeout":
        notes.append("WSJT-X folders did not answer. Connect that drive and check again.")
        return []
    if kind == "error":
        notes.append("WSJT-X logs could not be found on this PC.")
        return []
    rows = value or []
    if not rows:
        notes.append("No WSJT-X log found.")
    return rows


def _add_n1mm(candidates: list[Candidate], notes: list[str]) -> None:
    try:
        from wims.state.last_log import load as load_last
        pref = load_last()
    except Exception:
        pref = None
    if not pref or not (pref.get("db_path") or "").strip():
        notes.append("N1MM was not checked. Choose the contest log in WIMS, then check again.")
        return
    nr = pref.get("contest_nr")
    try:
        contest_nr = int(nr) if nr is not None else None
    except (TypeError, ValueError):
        contest_nr = None
    candidates.append(Candidate("N1MM", str(pref["db_path"]), "n1mm", contest_nr=contest_nr))


def _gridtracker_paths(notes: list[str], *, timeout: float, already: list[str]) -> list[str]:
    def work() -> list[str]:
        from wims.integrations.wsjtx_logs import discover_gridtracker_adif
        return [str(path) for path in discover_gridtracker_adif()]

    kind, value = run_bounded(work, timeout)
    if kind == "timeout":
        notes.append("GridTracker folders did not answer. Connect that drive and check again.")
        return []
    if kind == "error" or not value:
        notes.append("GridTracker was not found on this PC.")
        return []
    extra = []
    seen = set(already)
    for path in value:
        if path not in seen:
            seen.add(path)
            extra.append(path)
    if not extra and not already:
        notes.append("GridTracker was not found on this PC.")
    return extra


def main(argv: list[str] | None = None) -> int:
    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    report = build_report(argv, progress=progress)
    sys.stdout.write(render_text(report))
    json_path = getattr(report, "json_path", "") or ""
    if json_path:
        Path(json_path).write_text(
            json.dumps(to_json(report), indent=2) + "\n", encoding="utf-8",
        )
    return report.exit_code()
