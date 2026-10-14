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

"""Which seats report radio IF instead of RF.

Flex / SmartSDR XVTR slices (and most Icom+wfview seats) put RF on the
WSJT-X dial and in N1MM RadioInfo. A few seats do not: Roy's 222 radio
reports 21 MHz and the 432 transverter reports 28 MHz. Those ids are listed
here. Everyone else is left alone — 28.074 MHz stays 10m.

Path (override with ``WIMS_IF_SEATS_FILE`` for tests):
  * Linux/macOS: ``$XDG_CONFIG_HOME/wims/if_seats.json`` or ``~/.config/wims/…``
  * Windows: ``%APPDATA%\\wims\\if_seats.json``

Schema v1::

    {"schema": 1, "instances": ["ROY-432", "MGEF-222"]}

Keys are WSJT-X UDP ids (``--rig-name``, with or without a ``WSJT-X - ``
prefix) and N1MM StationName / NetBIOS. Match is case-insensitive. The same
file is read by the site server (decode/status labels) and by the log agent
on that PC (RadioInfo live band + ADIF). Each host has its own file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SCHEMA = 1

# WSJT-X puts "WSJT-X - " in front of --rig-name on the UDP id.
_ID_PREFIX = re.compile(r"^(?:WSJT-X|JTDX)\s*[-–—]\s*", re.IGNORECASE)


def default_path() -> Path:
    """Host-local list of IF-reporting ids."""
    env = (os.environ.get("WIMS_IF_SEATS_FILE") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "if_seats.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "if_seats.json"
    return Path.home() / ".config" / "wims" / "if_seats.json"


def identity_keys(instance: str | None) -> set[str]:
    """Comparable forms of a rig-name, UDP id, or N1MM station.

    ``ROY-432`` and ``WSJT-X - ROY-432`` are the same seat. Bare ``WSJT-X``
    (no rig-name) stays as itself.
    """
    s = (instance or "").strip()
    if not s:
        return set()
    keys = {s.casefold()}
    stripped = _ID_PREFIX.sub("", s).strip()
    if stripped:
        keys.add(stripped.casefold())
    return keys


def load(path: Path | str | None = None) -> list[str]:
    """Configured ids that report IF. Missing or broken file → empty."""
    p = Path(path) if path is not None else default_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("instances") or []
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        s = str(item or "").strip()
        if not s:
            continue
        fold = s.casefold()
        if fold in seen:
            continue
        seen.add(fold)
        out.append(s)
    return out


def configured_ids(path: Path | str | None = None) -> list[str]:
    """Copy of the saved id list (Setup page / snapshot)."""
    return load(path)


def save(ids: list[str], path: Path | str | None = None) -> Path | None:
    """Write the id list. Returns the path, or None if the write failed."""
    p = Path(path) if path is not None else default_path()
    clean: list[str] = []
    seen: set[str] = set()
    for item in ids:
        s = str(item or "").strip()
        if not s:
            continue
        fold = s.casefold()
        if fold in seen:
            continue
        seen.add(fold)
        clean.append(s)
    clean.sort(key=str.casefold)
    payload = {"schema": SCHEMA, "instances": clean}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
        return p
    except OSError:
        return None


def reports_if(instance: str | None, *, path: Path | str | None = None) -> bool:
    """True when this id is listed as reporting IF (file only; no env override)."""
    want = identity_keys(instance)
    if not want:
        return False
    for saved in load(path):
        if want & identity_keys(saved):
            return True
    return False


def set_reports_if(instance: str, enabled: bool,
                   path: Path | str | None = None) -> list[str]:
    """Add or remove one id. Matching forms (prefix / case) collapse to one row.

    Returns the list now on disk. A failed write returns the previous list.
    """
    instance = (instance or "").strip()
    cur = load(path)
    if not instance:
        return cur
    keys = identity_keys(instance)
    kept = [i for i in cur if not (identity_keys(i) & keys)]
    if enabled:
        kept.append(instance)
    written = save(kept, path)
    if written is None:
        return cur
    return load(path)
