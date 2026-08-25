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

"""Remember the operator's last selected N1MM contest log across restarts.

Auto-seed prefers a dated contest name (e.g. ARRLVHFJUN) over a casual DX log.
Home / multi-band ops often want the everyday log (wa1hco.s3db · DX) instead.
After the operator picks a log in Setup (or passes ``--seed-db``), we persist
``db_path`` + ``contest_nr`` so the next server start on this PC reloads it.

Path (override with ``WIMS_LAST_LOG`` for tests or custom layout):
  * Linux/macOS: ``$XDG_CONFIG_HOME/wims/last_log.json`` or ``~/.config/wims/…``
  * Windows: ``%APPDATA%\\wims\\last_log.json``

Schema v1::

    {"schema": 1, "db_path": "...", "contest_nr": 0, "contest_name": "DX", ...}
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA = 1


def default_path() -> Path:
    """Host-local preference file (not the N1MM DB, not the repo tree)."""
    env = (os.environ.get("WIMS_LAST_LOG") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "last_log.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "last_log.json"
    return Path.home() / ".config" / "wims" / "last_log.json"


def load(path: Path | str | None = None) -> dict[str, Any] | None:
    """Return the saved preference dict, or None if missing/invalid."""
    p = Path(path) if path is not None else default_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    db_path = (data.get("db_path") or "").strip()
    if not db_path:
        return None
    out: dict[str, Any] = {
        "schema": int(data.get("schema") or SCHEMA),
        "db_path": db_path,
        "contest_nr": data.get("contest_nr"),
        "contest_name": data.get("contest_name"),
        "db_label": data.get("db_label") or Path(db_path).name,
        "label": data.get("label"),
        "saved_ts": data.get("saved_ts"),
    }
    return out


def save(pref: dict[str, Any], path: Path | str | None = None) -> Path | None:
    """Write preference; returns path written, or None on failure.

    ``pref`` must include ``db_path``. ``contest_nr`` may be 0 (casual DX).
    """
    db_path = (pref.get("db_path") or "").strip()
    if not db_path:
        return None
    p = Path(path) if path is not None else default_path()
    payload = {
        "schema": SCHEMA,
        "db_path": db_path,
        "contest_nr": pref.get("contest_nr"),
        "contest_name": pref.get("contest_name"),
        "db_label": pref.get("db_label") or Path(db_path).name,
        "label": pref.get("label"),
        "saved_ts": pref.get("saved_ts") if pref.get("saved_ts") is not None
                    else time.time(),
    }
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        tmp.replace(p)
        return p
    except OSError:
        return None


def match_in_catalog(pref: dict[str, Any],
                     contests: list[dict]) -> dict | None:
    """Resolve a saved preference against the current discovery catalog.

    Prefer exact ``db_path`` + ``contest_nr``. Fall back to same basename + nr
    if the file moved under another scan root. Returns a contest dict or None.
    """
    if not pref or not contests:
        return None
    want_path = (pref.get("db_path") or "").strip()
    if not want_path:
        return None
    want_nr = pref.get("contest_nr")
    try:
        want_nr_i = int(want_nr) if want_nr is not None else None
    except (TypeError, ValueError):
        want_nr_i = None
    want_name = (pref.get("contest_name") or "").strip().upper() or None
    want_base = Path(want_path).name.lower()

    def nr_ok(c: dict) -> bool:
        if want_nr_i is None:
            return True
        try:
            return int(c.get("contest_nr")) == want_nr_i
        except (TypeError, ValueError):
            return False

    def name_ok(c: dict) -> bool:
        if not want_name:
            return True
        return (c.get("contest_name") or "").strip().upper() == want_name

    # 1) Exact path + contest_nr
    for c in contests:
        if (c.get("db_path") or "") == want_path and nr_ok(c):
            return c
    # 2) Same basename + contest_nr (DB moved to another known folder)
    for c in contests:
        if Path(c.get("db_path") or "").name.lower() == want_base and nr_ok(c):
            return c
    # 3) Exact path + contest name (nr missing from old prefs)
    if want_nr_i is None and want_name:
        for c in contests:
            if (c.get("db_path") or "") == want_path and name_ok(c):
                return c
        for c in contests:
            if (Path(c.get("db_path") or "").name.lower() == want_base
                    and name_ok(c)):
                return c
    return None


def is_db_usable(db_path: str) -> bool:
    """True if the saved .s3db path still exists as a file."""
    try:
        return Path(db_path).is_file()
    except OSError:
        return False
