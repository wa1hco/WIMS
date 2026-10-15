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

"""Operator contest choice and the optional shared-log file.

Same directory as ``last_log.json``. ``WIMS_CONTEST_RULES`` and ``WIMS_LOGS``
exist so tests can point at a temp file. Operator docs do not mention them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from wims.state.last_log import default_path as last_log_path

SCHEMA = 3


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
    return {
        "schema": SCHEMA,
        "contest": None,
        "explicit": False,
        "suggested": False,
        "fallback": "wsjtx-colors",
        "wsjtx_override": None,
        "gridtracker_path": "",
        "station_state": "",
        "station_county": "",
    }


def load_choice(path: Path | str | None = None) -> dict:
    p = Path(path) if path is not None else choice_path()
    base = default_choice()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict):
        return base
    contest = data.get("contest")
    if contest == "":
        contest = None
    base.update({
        "schema": int(data.get("schema") or SCHEMA),
        "contest": contest,
        "explicit": bool(data.get("explicit")),
        "suggested": bool(data.get("suggested")),
        "fallback": data.get("fallback") or "wsjtx-colors",
        "wsjtx_override": data.get("wsjtx_override"),
        "gridtracker_path": data.get("gridtracker_path") or "",
        "station_state": data.get("station_state") or "",
        "station_county": data.get("station_county") or "",
    })
    return base


def save_choice(data: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else choice_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = default_choice()
    out.update(data or {})
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


def load_logs(path: Path | str | None = None) -> dict:
    p = Path(path) if path is not None else logs_path()
    base = {"schema": 1, "primary": "auto", "shared_path": "", "overrides": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict):
        return base
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    base.update({
        "schema": int(data.get("schema") or 1),
        "primary": (data.get("primary") or "auto").strip() or "auto",
        "shared_path": (data.get("shared_path") or "").strip(),
        "overrides": {str(k): str(v) for k, v in overrides.items()},
    })
    return base


def save_logs(data: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else logs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = load_logs(p)
    out.update(data or {})
    out["schema"] = 1
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return p
