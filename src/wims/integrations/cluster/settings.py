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

The usual node is K1TTT (``k1ttt.net`` port 7373), an AR-Cluster that
sends a banner and then spots. Setup also lists NC7J, W3LPL, and VE7CC,
or a host and port the operator types. Spots stay off until Setup turns
them on. The band set defaults to every amateur band WIMS already names.
The mode filter (SSB, CW, FT8, FT4, Other) lives on Operate and is
saved here too. Other is MSK144, Q65, FM, data, and any unknown mode.
A file with no modes key is treated as all modes.

A saved file from the first cluster build used VE7CC on port 23, which
accepted the connection and sent nothing. That factory pair is moved to
K1TTT. A later choice of VE7CC is kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wims.core.bands import BAND_ORDER
from wims.integrations.cluster.parse import valid_login_call

SCHEMA = 2
DEFAULT_HOST = "k1ttt.net"
DEFAULT_PORT = 7373
DEFAULT_TTL_S = 15 * 60
# The first build offered VE7CC. From FN42 it completed TCP and sent no bytes.
_OLD_DEFAULT_HOST = "dxc.ve7cc.net"
_OLD_DEFAULT_PORT = 23

# Public nodes the operator can pick. Custom host:port is the other choice.
KNOWN_NODES = (
    {"id": "k1ttt", "label": "K1TTT (AR-Cluster)", "host": "k1ttt.net", "port": 7373},
    {"id": "nc7j", "label": "NC7J", "host": "dxc.nc7j.com", "port": 7373},
    {"id": "w3lpl", "label": "W3LPL (DX-Spider)", "host": "w3lpl.net", "port": 7373},
    {"id": "ve7cc", "label": "VE7CC (CC Cluster)", "host": "dxc.ve7cc.net", "port": 23},
)
# Points taken off a spot when no live WSJT-X is on that band and mode.
# The scoring weight is the negative of this. See scoring.CLUSTER_WEIGHTS.
DEFAULT_QSY_COST = 8

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_ALL = tuple(BAND_ORDER)

# Operate mode filter. Other is everything that is not SSB, CW, FT8, or FT4.
MODE_FILTERS = ("SSB", "CW", "FT8", "FT4", "Other")


def default_path() -> Path:
    from wims.rules.choice import config_dir
    return config_dir() / "cluster.json"


def all_bands() -> tuple[str, ...]:
    return _ALL


def default_settings() -> dict:
    return {
        "schema": SCHEMA,
        "enabled": False,
        "node": "k1ttt",
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "bands": "all",
        "modes": "all",
        "qsy_cost": DEFAULT_QSY_COST,
        "station_call": "",
    }


def known_nodes() -> list[dict]:
    return [dict(node) for node in KNOWN_NODES]


def match_node(host: str, port: int) -> str:
    host_l = (host or "").strip().lower()
    try:
        port_n = int(port)
    except (TypeError, ValueError):
        port_n = 0
    for node in KNOWN_NODES:
        if node["host"].lower() == host_l and int(node["port"]) == port_n:
            return node["id"]
    return "custom"


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


def _clean_modes(value) -> str | list[str]:
    if value is None or value == "all":
        return "all"
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {"", "all", "*"}:
            return "all"
        value = [part.strip() for part in text.split(",")]
    if not isinstance(value, (list, tuple)):
        return "all"
    known = {name.lower(): name for name in MODE_FILTERS}
    out = []
    seen = set()
    for item in value:
        mode = known.get(str(item or "").strip().lower())
        if mode and mode not in seen:
            seen.add(mode)
            out.append(mode)
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


def clean_station_call(value) -> str:
    """A callsign we will send as the cluster login, or blank."""
    return str(value or "").strip().upper() if valid_login_call(value) else ""


def effective_call(settings: dict | None, live_call: str | None = "") -> str:
    """Setup station call first; otherwise the live WSJT-X / logger call."""
    setup = clean_station_call((settings or {}).get("station_call"))
    if setup:
        return setup
    return clean_station_call(live_call)


def call_mismatch_warning(setup_call: str, live_calls) -> str:
    """Plain-language warning when Setup and a live WSJT-X disagree.

    Nothing is changed automatically. An empty Setup call is not a mismatch.
    """
    setup = clean_station_call(setup_call)
    if not setup:
        return ""
    others: list[str] = []
    seen: set[str] = set()
    for item in live_calls or []:
        call = clean_station_call(item)
        if call and call != setup and call not in seen:
            seen.add(call)
            others.append(call)
    if not others:
        return ""
    if len(others) == 1:
        reported = others[0]
    elif len(others) == 2:
        reported = f"{others[0]} and {others[1]}"
    else:
        reported = ", ".join(others[:-1]) + f", and {others[-1]}"
    return (
        f"Station call {setup} is different from the call WSJT-X reports "
        f"({reported}). The cluster will use {setup}."
    )


def _migrate(data: dict) -> dict:
    """Move the old factory node (VE7CC port 23, schema 1) to K1TTT."""
    raw = dict(data)
    try:
        schema = int(raw.get("schema") or 1)
    except (TypeError, ValueError):
        schema = 1
    host = str(raw.get("host") or "").strip().lower()
    try:
        port = int(raw.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if schema < 2 and host == _OLD_DEFAULT_HOST and port == _OLD_DEFAULT_PORT:
        raw["host"] = DEFAULT_HOST
        raw["port"] = DEFAULT_PORT
        raw["node"] = "k1ttt"
    return raw


def sanitize(data: dict | None) -> dict:
    raw = _migrate(data) if isinstance(data, dict) else {}
    out = default_settings()
    out["enabled"] = bool(raw.get("enabled"))
    node_id = str(raw.get("node") or "").strip().lower()
    by_id = {node["id"]: node for node in KNOWN_NODES}
    if node_id in by_id:
        picked = by_id[node_id]
        out["host"] = picked["host"]
        out["port"] = int(picked["port"])
        out["node"] = node_id
    else:
        out["host"] = _clean_host(raw.get("host"))
        out["port"] = _clean_port(raw.get("port"))
        out["node"] = match_node(out["host"], out["port"])
    out["bands"] = _clean_bands(raw.get("bands", "all"))
    out["modes"] = _clean_modes(raw.get("modes", "all"))
    if "qsy_cost" in raw:
        out["qsy_cost"] = _clean_qsy(raw.get("qsy_cost"))
    out["station_call"] = clean_station_call(raw.get("station_call"))
    return out


def allowed_bands(settings: dict) -> set[str] | None:
    """Bands the operator wants. None means every amateur band."""
    bands = (settings or {}).get("bands", "all")
    if bands == "all":
        return None
    return set(bands or [])


def allowed_modes(settings: dict) -> set[str] | None:
    """Mode boxes the operator left on. None means every mode."""
    modes = (settings or {}).get("modes", "all")
    if modes == "all":
        return None
    return set(modes or [])


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
