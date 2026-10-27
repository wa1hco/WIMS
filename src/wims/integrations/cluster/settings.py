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

"""DX cluster choices, saved beside the Goal.

``cluster.json`` lives in the same directory as ``contest_rules.json``.
The operator sets it on Setup. There is no command-line flag and no
environment variable.

Default node is VE7CC (``dxc.ve7cc.net`` port 23), a public CC Cluster
many loggers already use. Spots stay off until Setup turns them on.
The band set defaults to every amateur band WIMS already names.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wims.core.bands import BAND_ORDER

SCHEMA = 1
DEFAULT_HOST = "dxc.ve7cc.net"
DEFAULT_PORT = 23
DEFAULT_TTL_S = 15 * 60
# Points taken off a spot when no live WSJT-X is on that band and mode.
# The scoring weight is the negative of this. See scoring.CLUSTER_WEIGHTS.
DEFAULT_QSY_COST = 8

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_ALL = tuple(BAND_ORDER)


def default_path() -> Path:
    from wims.rules.choice import config_dir
    return config_dir() / "cluster.json"


def all_bands() -> tuple[str, ...]:
    return _ALL


def default_settings() -> dict:
    return {
        "schema": SCHEMA,
        "enabled": False,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "bands": "all",
        "qsy_cost": DEFAULT_QSY_COST,
    }


def _clean_host(value) -> str:
    host = str(value or "").strip()
    if not host or not _HOST.match(host) or ".." in host:
        return DEFAULT_HOST
    return host


def _clean_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    if port < 1 or port > 65535:
        return DEFAULT_PORT
    return port


def _clean_bands(value) -> str | list[str]:
    if value is None or value == "all":
        return "all"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"", "all", "*"}:
            return "all"
        value = [part.strip() for part in text.split(",")]
    if not isinstance(value, (list, tuple)):
        return "all"
    known = set(_ALL)
    out = []
    seen = set()
    for item in value:
        band = str(item or "").strip()
        if band in known and band not in seen:
            seen.add(band)
            out.append(band)
    return out


def _clean_qsy(value) -> int:
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return DEFAULT_QSY_COST
    if cost < 0:
        cost = 0
    if cost > 80:
        cost = 80
    return int(round(cost))


def sanitize(data: dict | None) -> dict:
    raw = data if isinstance(data, dict) else {}
    out = default_settings()
    out["enabled"] = bool(raw.get("enabled"))
    out["host"] = _clean_host(raw.get("host"))
    out["port"] = _clean_port(raw.get("port"))
    out["bands"] = _clean_bands(raw.get("bands", "all"))
    if "qsy_cost" in raw:
        out["qsy_cost"] = _clean_qsy(raw.get("qsy_cost"))
    return out


def allowed_bands(settings: dict) -> set[str] | None:
    """Bands the operator wants. None means every amateur band."""
    bands = (settings or {}).get("bands", "all")
    if bands == "all":
        return None
    return set(bands or [])


def load(path: Path | str | None = None) -> dict:
    p = Path(path) if path is not None else default_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    return sanitize(data if isinstance(data, dict) else None)


def save(data: dict, path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = sanitize(data)
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return p
