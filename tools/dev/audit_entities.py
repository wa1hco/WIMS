#!/usr/bin/env python3
# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compare the call-to-entity resolver with countries stored in a log.

Reads an ADIF file and, when given, an N1MM .s3db. Does not write either.
A missing DXCC or COUNTRY field is skipped, not treated as a disagreement.

    python3 tools/dev/audit_entities.py LOG.adi [--cty cty.dat] [--s3db x.s3db]

The country file defaults to the cty.dat WIMS would read on this PC.
Without one, the builtin prefix list is the resolver and the report says so.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from wims.adif import iter_records  # noqa: E402
from wims.engine.dxcc import entity_name, lookup  # noqa: E402
from wims.rules.callsign import location_body  # noqa: E402
from wims.rules.cty import CtyIndex, find_cty_dat  # noqa: E402

_NAME_COLS = ("country", "countryname")
_NUMBER_COLS = ("dxcc",)
_PREFIX_COLS = ("countryprefix", "dxccprefix")


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def _same(a: str | None, b: str | None) -> bool:
    left, right = _norm(a), _norm(b)
    return bool(left) and left == right


def _same_family(a: str, b: str) -> bool:
    """Spelling of one entity (Germany / Fed. Rep. of Germany), not two entities."""
    left, right = _norm(a), _norm(b)
    if not left or not right or left == right:
        return False
    return left in right or right in left


def _resolver(cty):
    def resolve(call: str) -> str:
        if cty is not None:
            return cty.entity_name(call) or ""
        return lookup(call) or ""

    return resolve


def _dxcc_name(number: str) -> str:
    return entity_name(number) or ""


def _field_rows(records, resolve) -> tuple[list[dict], int, int]:
    rows = []
    with_dxcc = 0
    with_country = 0
    seen: set[tuple] = set()
    for rec in records:
        call = (rec.get("call") or "").strip().upper()
        if not call:
            continue
        stored_dxcc = (rec.get("dxcc") or "").strip()
        stored_country = (rec.get("country") or "").strip()
        if stored_dxcc:
            with_dxcc += 1
        if stored_country:
            with_country += 1
        if not stored_dxcc and not stored_country:
            continue
        got = resolve(call)
        notes = []
        if stored_country and not _same(stored_country, got):
            notes.append(f"COUNTRY {stored_country}")
        if stored_dxcc:
            named = _dxcc_name(stored_dxcc)
            if named:
                if not _same(named, got):
                    notes.append(f"DXCC {stored_dxcc} ({named})")
            elif got:
                notes.append(f"DXCC {stored_dxcc}")
        if not notes:
            continue
        key = (call, got, tuple(notes))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "call": call,
            "resolver": got or "(blank)",
            "stored": "; ".join(notes),
        })
    return rows, with_dxcc, with_country


def _n1mm_rows(path: Path, resolve) -> tuple[list[dict], str]:
    uri = f"file:{path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            row[0].lower()
            for row in con.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        if "dxlog" not in tables:
            return [], "no DXLOG table"
        info = con.execute("pragma table_info(DXLOG)").fetchall()
    finally:
        con.close()
    columns = {row[1].lower(): row[1] for row in info}
    name_col = next((columns[c] for c in _NAME_COLS if c in columns), None)
    number_col = next((columns[c] for c in _NUMBER_COLS if c in columns), None)
    prefix_col = next((columns[c] for c in _PREFIX_COLS if c in columns), None)
    if not any((name_col, number_col, prefix_col)):
        found = ", ".join(sorted(columns)) or "(none)"
        return [], f"no country column in DXLOG ({found})"
    select = ["Call"]
    labels = []
    if name_col:
        select.append(name_col)
        labels.append(name_col)
    if number_col:
        select.append(number_col)
        labels.append(number_col)
    if prefix_col:
        select.append(prefix_col)
        labels.append(prefix_col)
    con = sqlite3.connect(uri, uri=True)
    try:
        fetched = con.execute(
            "select " + ", ".join(select) + " from DXLOG"
        ).fetchall()
    finally:
        con.close()
    rows = []
    seen: set[tuple] = set()
    for rec in fetched:
        call = str(rec[0] or "").strip().upper()
        if not call:
            continue
        values = {labels[i]: rec[i + 1] for i in range(len(labels))}
        got = resolve(call)
        notes = []
        if name_col:
            stored = str(values.get(name_col) or "").strip()
            if stored and not _same(stored, got):
                notes.append(f"{name_col} {stored}")
        if number_col:
            stored = str(values.get(number_col) or "").strip()
            if stored:
                named = _dxcc_name(stored)
                if named and not _same(named, got):
                    notes.append(f"{number_col} {stored} ({named})")
                elif not named and got:
                    notes.append(f"{number_col} {stored}")
        if prefix_col and not name_col and not number_col:
            stored = str(values.get(prefix_col) or "").strip().upper()
            body = location_body(call)
            if stored and not body.startswith(stored) and not call.startswith(stored):
                notes.append(f"{prefix_col} {stored}")
        if not notes:
            continue
        key = (call, got, tuple(notes))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "call": call,
            "resolver": got or "(blank)",
            "stored": "; ".join(notes),
        })
    used = ", ".join(labels)
    return rows, f"DXLOG columns {used}"


def _fallback_section(calls: list[str], cty) -> dict:
    spelling: Counter = Counter()
    entity: Counter = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for call in calls:
        builtin = lookup(call) or "(blank)"
        got = cty.entity_name(call) or "(blank)"
        if _same(builtin, got) or (builtin == "(blank)" and got == "(blank)"):
            continue
        pair = (builtin, got)
        if builtin != "(blank)" and got != "(blank)" and _same_family(builtin, got):
            spelling[pair] += 1
            continue
        entity[pair] += 1
        if len(examples[pair]) < 12:
            examples[pair].append(call)
    return {
        "spelling": [
            {"builtin": a, "resolver": b, "count": n}
            for (a, b), n in spelling.most_common()
        ],
        "entity": [
            {
                "builtin": a,
                "resolver": b,
                "count": n,
                "calls": examples[(a, b)],
            }
            for (a, b), n in entity.most_common()
        ],
    }


def audit(adif_path, cty_path=None, s3db_path=None) -> dict:
    path = Path(adif_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    records = list(iter_records(text))
    cty = None
    cty_label = "builtin prefix list (no cty.dat)"
    if cty_path:
        cty = CtyIndex.load(cty_path)
        cty_label = str(cty_path)
    else:
        found = find_cty_dat()
        if found is not None:
            cty = CtyIndex.load(found)
            cty_label = str(found)
    resolve = _resolver(cty)
    calls = []
    seen = set()
    unresolved = []
    for rec in records:
        call = (rec.get("call") or "").strip().upper()
        if not call or call in seen:
            continue
        seen.add(call)
        calls.append(call)
        if not resolve(call):
            unresolved.append(call)
    field_rows, with_dxcc, with_country = _field_rows(records, resolve)
    n1mm_rows: list[dict] = []
    n1mm_note = "not given"
    if s3db_path:
        n1mm_rows, n1mm_note = _n1mm_rows(Path(s3db_path), resolve)
    fallback = _fallback_section(calls, cty) if cty is not None else None
    return {
        "adif": str(path),
        "cty": cty_label,
        "qsos": len(records),
        "unique_calls": len(calls),
        "unresolved": unresolved,
        "with_dxcc": with_dxcc,
        "with_country": with_country,
        "field_disagreements": field_rows,
        "n1mm_note": n1mm_note,
        "n1mm_disagreements": n1mm_rows,
        "fallback": fallback,
    }


def format_report(report: dict) -> str:
    lines = [
        "Call entity audit",
        f"Log: {report['adif']}",
        f"Resolver: {report['cty']}",
        f"QSOs: {report['qsos']}",
        f"Unique calls: {report['unique_calls']}",
        f"Unresolved: {len(report['unresolved'])}",
        f"Stored DXCC field: {report['with_dxcc']}",
        f"Stored COUNTRY field: {report['with_country']}",
        f"Disagreements with stored fields: {len(report['field_disagreements'])}",
    ]
    for row in report["field_disagreements"]:
        lines.append(
            f"  {row['call']}: resolver {row['resolver']}; log {row['stored']}"
        )
    if report["unresolved"]:
        sample = ", ".join(report["unresolved"][:20])
        lines.append(f"Unresolved calls: {sample}")
    lines.append(f"N1MM: {report['n1mm_note']}")
    lines.append(
        f"Disagreements with N1MM: {len(report['n1mm_disagreements'])}"
    )
    for row in report["n1mm_disagreements"]:
        lines.append(
            f"  {row['call']}: resolver {row['resolver']}; N1MM {row['stored']}"
        )
    fallback = report.get("fallback")
    if fallback is not None:
        lines.append(
            "Builtin fallback vs this resolver "
            "(not a field in the log; spelling pairs are counted, not listed)"
        )
        lines.append(f"Spelling pairs: {len(fallback['spelling'])}")
        for row in fallback["spelling"][:15]:
            lines.append(
                f"  {row['count']:4}  {row['builtin']}  vs  {row['resolver']}"
            )
        lines.append(f"Different entity pairs: {len(fallback['entity'])}")
        for row in fallback["entity"]:
            shown = ", ".join(row["calls"])
            lines.append(
                f"  {row['count']:4}  fallback {row['builtin']}  "
                f"vs resolver {row['resolver']}: {shown}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adif", help="ADIF log to read")
    parser.add_argument("--cty", help="country file (default: the one WIMS would find)")
    parser.add_argument("--s3db", help="optional N1MM log database")
    args = parser.parse_args(argv)
    report = audit(args.adif, cty_path=args.cty, s3db_path=args.s3db)
    sys.stdout.write(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
