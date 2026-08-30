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
        """Installed or running — for labels. Auto-start uses ``wsjt_running``."""
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
    """Deprecated — checkboxes are live status, not prefs. Always empty."""
    return {}


def save_wanted_agents(wanted: dict[str, bool]) -> None:
    """Deprecated no-op — checkboxes are not remembered across launches."""
    return


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


def live_checks(
    snap: AssetSnapshot,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Which boxes should be on from **live** seat reality (not prefs).

    - N1MM / WSJT-X: companion process running → agent required.
    - Key: never auto (no companion app).
    - Site server: console reachable → status checked (do not imply we own it).
    """
    return {
        AGENT_LOG: bool(snap.n1mm_present),
        AGENT_WSJT: bool(snap.wsjt_running),
        AGENT_KEY: False,
        AGENT_SERVER: bool(site_reachable),
    }


def suggested_checks(
    snap: AssetSnapshot,
    wanted: dict[str, bool] | None = None,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Compatibility wrapper — ``wanted`` is ignored (checkboxes are not prefs)."""
    _ = wanted
    return live_checks(snap, site_reachable=site_reachable)
