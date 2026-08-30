# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect local apps/assets and remember which agents the operator wants.

No fixed “seat role” — N1MM, WSJT-X, Key, and Site server are independent.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

AGENT_LOG = "log"
AGENT_WSJT = "wsjt"
AGENT_KEY = "key"
AGENT_SERVER = "server"

_ALL_AGENTS = (AGENT_LOG, AGENT_WSJT, AGENT_KEY, AGENT_SERVER)


@dataclass
class AssetSnapshot:
    n1mm_running: bool = False
    n1mm_found: bool = False
    wsjt_running: bool = False
    wsjt_ini_count: int = 0
    wsjt_running_names: list[str] = field(default_factory=list)

    @property
    def wsjt_present(self) -> bool:
        return self.wsjt_running or self.wsjt_ini_count > 0

    @property
    def n1mm_present(self) -> bool:
        # Linux: process only (leftover Documents tree is not enough).
        if self.n1mm_running:
            return True
        if sys.platform.startswith("win") and self.n1mm_found:
            return True
        return False


def _pref_path() -> Path:
    env = (os.environ.get("WIMS_AGENT_BOXES") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "agent_boxes.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "agent_boxes.json"
    return Path.home() / ".config" / "wims" / "agent_boxes.json"


def load_wanted_agents() -> dict[str, bool]:
    """Last checkbox state (which agents the op wants)."""
    try:
        raw = json.loads(_pref_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    wanted = raw.get("wanted") or {}
    return {k: bool(wanted.get(k)) for k in _ALL_AGENTS if k in wanted}


def save_wanted_agents(wanted: dict[str, bool]) -> None:
    path = _pref_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": 1, "wanted": dict(wanted)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def detect_assets() -> AssetSnapshot:
    snap = AssetSnapshot()
    try:
        from wims.agent.report import _process_running, _wsjtx_running_rig_names
        from wims.agent.n1mm_probe import probe_n1mm
        from wims.integrations.wsjtx_config import discover_ini_paths

        snap.n1mm_running = bool(
            _process_running(
                ("n1mmlogger.net.exe", "n1mmlogger.net", "n1mm logger+.exe",
                 "n1mmlogger+.exe", "n1mm logger.exe"),
                substrings=("n1mmlogger",),
            )
        )
        snap.n1mm_found = bool(probe_n1mm().get("found"))
        snap.wsjt_running = bool(
            _process_running(("wsjtx.exe", "wsjtx", "jt9.exe", "jt9"),
                             substrings=("wsjtx", "jt9"))
        )
        snap.wsjt_ini_count = len(discover_ini_paths())
        names = _wsjtx_running_rig_names()
        if names:
            snap.wsjt_running_names = sorted(names)
    except Exception:
        pass
    return snap


def suggested_checks(snap: AssetSnapshot, wanted: dict[str, bool]) -> dict[str, bool]:
    """Merge detection with saved wants.

    Detected apps force their agent box on. Saved wants keep Key/Server across
    restarts. Manual uncheck after detect is allowed until next detect pulse
    re-asserts (caller can track user_overrides).
    """
    out = {k: bool(wanted.get(k)) for k in _ALL_AGENTS}
    if snap.n1mm_present:
        out[AGENT_LOG] = True
    if snap.wsjt_present:
        out[AGENT_WSJT] = True
    # Key / server: prefs only (no app to auto-detect for Key).
    return out
