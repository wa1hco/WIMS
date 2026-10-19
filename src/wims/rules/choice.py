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

"""Operator goal choice and which log WIMS checks.

Same directory as ``last_log.json``. ``WIMS_CONTEST_RULES`` and ``WIMS_LOGS``
exist so tests can point at a temp file. Operator docs do not mention them.

``logs.json`` schema 2 stores three separate facts: the log, an optional
count-since time, and an optional count-until time. The goal does not pick
the log. A saved choice wins over a suggestion.

Schema 5 stores a goal (contest, award, just operating, or custom) plus the
second-menu id. Older files only had ``contest``; loading them keeps that
choice. A saved ``wsjtx-colors`` goal is rewritten once as checklist lines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from wims.state.last_log import default_path as last_log_path

SCHEMA = 5


def config_dir() -> Path:
    return last_log_path().parent


def choice_path() -> Path:
    env = (os.environ.get("WIMS_CONTEST_RULES") or "").strip()
    if env:
        return Path(env)
    return config_dir() / "contest_rules.json"


def custom_path() -> Path:
    return choice_path().parent / "custom_rules.json"


def logs_path() -> Path:
    env = (os.environ.get("WIMS_LOGS") or "").strip()
    if env:
        return Path(env)
    return config_dir() / "logs.json"


def default_choice() -> dict:
    from wims.engine.goal_rules import normalize_checklist

    return {
        "schema": SCHEMA,
        "goal": "operating",
        "goal_id": "checklist",
        "contest": None,
        "explicit": False,
        "suggested": False,
        "fallback": "",
        "wsjtx_override": None,
        "gridtracker_path": "",
        "station_state": "",
        "station_county": "",
        "checklist": normalize_checklist(None),
    }


def load_choice(path: Path | str | None = None) -> dict:
    from wims.engine.goal_rules import shape_choice

    p = Path(path) if path is not None else choice_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    return shape_choice(data if isinstance(data, dict) else None)


def needs_migration(path: Path | str | None = None) -> bool:
    """True when a saved file is older than the checklist goal, or still Colors."""
    p = Path(path) if path is not None else choice_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    schema = int(data.get("schema") or 0)
    if str(data.get("goal_id") or "") == "wsjtx-colors":
        return True
    return schema < SCHEMA or "goal" not in data


def save_choice(data: dict, path: Path | str | None = None) -> Path:
    from wims.engine.goal_rules import shape_choice

    p = Path(path) if path is not None else choice_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    incoming = dict(data or {})
    # shape_choice keeps an explicit goal. A legacy contest-only dict is migrated.
    if "schema" not in incoming and incoming.get("goal"):
        incoming["schema"] = SCHEMA
    out = shape_choice(incoming)
    out["schema"] = SCHEMA
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return p


def load_custom(path: Path | str | None = None) -> dict | None:
    p = Path(path) if path is not None else custom_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def save_custom(data: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else custom_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


LOGS_SCHEMA = 2
_LOG_KINDS = {"n1mm", "wsjtx", "adif", "gridtracker"}
_LOG_PRIMARIES = {"auto", "n1mm", "wsjtx", "adif"}
_CUTOFFS = {"whole", "start_now", "this_year", "custom"}


def blank_logs() -> dict:
    """Schema 2. The log, the start time, and the optional end time are separate.

    ``explicit`` false means the goal may suggest a log. A saved choice wins.
    ``count_since`` / ``count_until`` are UTC ``YYYY-MM-DDTHH:MM:SSZ`` or empty.
    Empty means that side of the window is open. The lookup uses the times,
    not the preset name.
    """
    return {
        "schema": LOGS_SCHEMA,
        "primary": "auto",
        "explicit": False,
        "selection": None,
        "count_since": "",
        "count_until": "",
        "cutoff": "whole",
        "shared_path": "",
        "overrides": {},
    }


def clean_selection(raw) -> dict | None:
    """One chosen log. No start time in here — that is ``count_since``."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind not in _LOG_KINDS:
        return None
    contest_nr = raw.get("contest_nr")
    if contest_nr is None or contest_nr == "":
        contest_nr = None
    else:
        try:
            contest_nr = int(contest_nr)
        except (TypeError, ValueError):
            contest_nr = None
    return {
        "id": str(raw.get("id") or "").strip(),
        "kind": kind,
        "path": str(raw.get("path") or "").strip(),
        "label": str(raw.get("label") or "").strip(),
        "contest_nr": contest_nr,
        "contest_name": str(raw.get("contest_name") or "").strip(),
    }


def load_logs(path: Path | str | None = None) -> dict:
    p = Path(path) if path is not None else logs_path()
    base = blank_logs()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict):
        return base
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    primary = str(data.get("primary") or "auto").strip() or "auto"
    if primary not in _LOG_PRIMARIES:
        primary = "auto"
    # Schema 1 had no explicit flag. primary other than auto was a saved choice
    # (Use this WSJT-X log). auto stays a suggestion and does not keep a stale file.
    if "explicit" in data:
        explicit = bool(data.get("explicit"))
    else:
        explicit = primary != "auto"
    since = str(data.get("count_since") or "").strip()
    until = str(data.get("count_until") or "").strip()
    cutoff = str(data.get("cutoff") or "").strip()
    if cutoff not in _CUTOFFS:
        cutoff = "custom" if (since or until) else "whole"
    if cutoff == "whole" and (since or until):
        cutoff = "custom"
    base.update({
        "schema": int(data.get("schema") or 1),
        "primary": primary,
        "explicit": explicit,
        "selection": clean_selection(data.get("selection")),
        "count_since": since,
        "count_until": until,
        "cutoff": cutoff,
        "shared_path": str(data.get("shared_path") or "").strip(),
        "overrides": {str(k): str(v) for k, v in overrides.items()},
    })
    return base


def save_logs(data: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else logs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = load_logs(p)
    incoming = dict(data or {})
    out.update(incoming)
    out["selection"] = clean_selection(out.get("selection"))
    out["explicit"] = bool(out.get("explicit"))
    out["count_since"] = str(out.get("count_since") or "").strip()
    out["count_until"] = str(out.get("count_until") or "").strip()
    primary = str(out.get("primary") or "auto").strip() or "auto"
    if primary not in _LOG_PRIMARIES:
        primary = "auto"
    out["primary"] = primary
    cutoff = str(out.get("cutoff") or "whole").strip() or "whole"
    if cutoff not in _CUTOFFS:
        cutoff = "custom"
    if cutoff == "whole" and (out["count_since"] or out["count_until"]):
        cutoff = "custom"
    out["cutoff"] = cutoff
    out["shared_path"] = str(out.get("shared_path") or "").strip()
    if not isinstance(out.get("overrides"), dict):
        out["overrides"] = {}
    else:
        out["overrides"] = {str(k): str(v) for k, v in out["overrides"].items()}
    payload = {
        "schema": LOGS_SCHEMA,
        "primary": out["primary"],
        "explicit": out["explicit"],
        "selection": out["selection"],
        "count_since": out["count_since"],
        "count_until": out["count_until"],
        "cutoff": out["cutoff"],
        "shared_path": out["shared_path"],
        "overrides": out["overrides"],
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p
