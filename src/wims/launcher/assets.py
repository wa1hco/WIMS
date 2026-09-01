# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect running apps and remember seat **intent** (what this PC will run).

Running list = observational. Intent checkboxes = operator desire (remembered);
WIMS starts the matching agents.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Agent process ids (launcher _procs / roles).
AGENT_LOG = "log"
AGENT_WSJT = "wsjt"
AGENT_KEY = "key"
AGENT_SERVER = "server"

# Seat intent checkbox ids (remembered prefs).
INTENT_N1MM = "n1mm"
INTENT_WSJT = "wsjt"
INTENT_SSB_CW = "ssb_cw"
INTENT_SERVER = "server"

_ALL_AGENTS = (AGENT_LOG, AGENT_WSJT, AGENT_KEY, AGENT_SERVER)
_ALL_INTENTS = (INTENT_N1MM, INTENT_WSJT, INTENT_SSB_CW, INTENT_SERVER)

# Intent → agent to start/stop.
INTENT_TO_AGENT: dict[str, str] = {
    INTENT_N1MM: AGENT_LOG,
    INTENT_WSJT: AGENT_WSJT,
    INTENT_SSB_CW: AGENT_KEY,
    INTENT_SERVER: AGENT_SERVER,
}


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
        if self.n1mm_running:
            return True
        if sys.platform.startswith("win") and self.n1mm_found:
            return True
        return False


def _intent_pref_path() -> Path:
    env = (os.environ.get("WIMS_SEAT_INTENT") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "seat_intent.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "seat_intent.json"
    return Path.home() / ".config" / "wims" / "seat_intent.json"


def load_seat_intent() -> dict[str, bool]:
    """Remembered seat intent checkboxes for this PC."""
    try:
        raw = json.loads(_intent_pref_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {k: False for k in _ALL_INTENTS}
    intent = raw.get("intent") or {}
    return {k: bool(intent.get(k)) for k in _ALL_INTENTS}


def save_seat_intent(intent: dict[str, bool]) -> None:
    path = _intent_pref_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {k: bool(intent.get(k)) for k in _ALL_INTENTS}
        path.write_text(
            json.dumps({"schema": 1, "intent": body}, indent=2) + "\n",
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
            _process_running(("wsjtx.exe", "wsjtx"), substrings=())
        )
        snap.wsjt_ini_count = len(discover_ini_paths())
        names = _wsjtx_running_rig_names()
        if names:
            snap.wsjt_running_names = sorted(names)
    except Exception:
        pass
    return snap


def agents_for_intent(intent: dict[str, bool]) -> dict[str, bool]:
    """Which agents should be running given seat intent."""
    return {
        agent: bool(intent.get(intent_id))
        for intent_id, agent in INTENT_TO_AGENT.items()
    }


# --- Backward-compat stubs (older tests / imports) ----------------------------

def load_wanted_agents() -> dict[str, bool]:
    """Map seat intent → agent wants (compat)."""
    return agents_for_intent(load_seat_intent())


def save_wanted_agents(wanted: dict[str, bool]) -> None:
    """Compat: treat agent ids as intent where names overlap."""
    intent = load_seat_intent()
    if AGENT_LOG in wanted:
        intent[INTENT_N1MM] = bool(wanted[AGENT_LOG])
    if AGENT_WSJT in wanted:
        intent[INTENT_WSJT] = bool(wanted[AGENT_WSJT])
    if AGENT_KEY in wanted:
        intent[INTENT_SSB_CW] = bool(wanted[AGENT_KEY])
    if AGENT_SERVER in wanted:
        intent[INTENT_SERVER] = bool(wanted[AGENT_SERVER])
    save_seat_intent(intent)


def live_checks(
    snap: AssetSnapshot,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Deprecated name — observational only; do not drive intent checkboxes."""
    _ = site_reachable
    return {
        AGENT_LOG: bool(snap.n1mm_running),
        AGENT_WSJT: bool(snap.wsjt_running),
        AGENT_KEY: False,
        AGENT_SERVER: False,
    }


def suggested_checks(
    snap: AssetSnapshot,
    wanted: dict[str, bool] | None = None,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Compat: prefer saved intent over live detection."""
    _ = snap
    _ = site_reachable
    if wanted:
        return {k: bool(wanted.get(k)) for k in _ALL_AGENTS}
    return agents_for_intent(load_seat_intent())
