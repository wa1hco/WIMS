# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect whether this PC is an N1MM seat or a WSJT seat (tired-operator home).

Preference file (override path with WIMS_SEAT_TYPE_FILE):
  Linux/macOS: $XDG_CONFIG_HOME/wims/seat_type.json or ~/.config/wims/…
  Windows: %APPDATA%\\wims\\seat_type.json

Env force: WIMS_SEAT_TYPE=n1mm|wsjt|site
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SEAT_N1MM = "n1mm"
SEAT_WSJT = "wsjt"
SEAT_SITE = "site"
SEAT_AMBIGUOUS = "ambiguous"

_VALID = frozenset({SEAT_N1MM, SEAT_WSJT, SEAT_SITE})


@dataclass(frozen=True)
class SeatProbe:
    seat_type: str  # n1mm | wsjt | site | ambiguous
    wsjt_ini: bool
    wsjt_running: bool
    n1mm_found: bool
    n1mm_running: bool
    source: str  # env | pref | detect | ambiguous
    detail: str = ""


def _pref_path() -> Path:
    env = (os.environ.get("WIMS_SEAT_TYPE_FILE") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "seat_type.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "seat_type.json"
    return Path.home() / ".config" / "wims" / "seat_type.json"


def load_seat_type() -> str | None:
    try:
        raw = json.loads(_pref_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    val = (raw.get("seat_type") or "").strip().lower()
    return val if val in _VALID else None


def save_seat_type(seat_type: str) -> None:
    seat_type = (seat_type or "").strip().lower()
    if seat_type not in _VALID:
        return
    path = _pref_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": 1, "seat_type": seat_type}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _wsjt_signals() -> tuple[bool, bool]:
    ini = False
    running = False
    try:
        from wims.integrations.wsjtx_config import discover_ini_paths
        ini = bool(discover_ini_paths())
    except Exception:
        ini = False
    try:
        from wims.agent.report import _process_running
        running = bool(
            _process_running(("wsjtx.exe", "wsjtx", "jt9.exe", "jt9"),
                             substrings=("wsjtx", "jt9"))
        )
    except Exception:
        running = False
    return ini, running


def _n1mm_signals() -> tuple[bool, bool]:
    found = False
    running = False
    try:
        from wims.agent.n1mm_probe import probe_n1mm
        found = bool(probe_n1mm().get("found"))
    except Exception:
        found = False
    try:
        from wims.agent.report import _process_running
        running = bool(
            _process_running(
                ("n1mmlogger.net.exe", "n1mmlogger.net", "n1mm logger+.exe",
                 "n1mmlogger+.exe", "n1mm logger.exe"),
                substrings=("n1mmlogger",),
            )
        )
    except Exception:
        running = False
    return found, running


def probe_seat() -> SeatProbe:
    """Return seat type from env, saved pref, or live detection."""
    env = (os.environ.get("WIMS_SEAT_TYPE") or "").strip().lower()
    if env in _VALID:
        return SeatProbe(
            seat_type=env, wsjt_ini=False, wsjt_running=False,
            n1mm_found=False, n1mm_running=False, source="env",
            detail=f"WIMS_SEAT_TYPE={env}",
        )

    pref = load_seat_type()
    wsjt_ini, wsjt_running = _wsjt_signals()
    n1mm_found, n1mm_running = _n1mm_signals()
    wsjt = wsjt_ini or wsjt_running
    n1mm = n1mm_found or n1mm_running

    if pref in _VALID:
        return SeatProbe(
            seat_type=pref, wsjt_ini=wsjt_ini, wsjt_running=wsjt_running,
            n1mm_found=n1mm_found, n1mm_running=n1mm_running, source="pref",
            detail=f"saved preference={pref}",
        )

    if n1mm and not wsjt:
        kind, src, detail = SEAT_N1MM, "detect", "N1MM present, no WSJT-X"
    elif wsjt and not n1mm:
        kind, src, detail = SEAT_WSJT, "detect", "WSJT-X present, no N1MM"
    elif n1mm and wsjt:
        # Co-located logger+WSJT → N1MM seat helpers are the primary need.
        kind, src, detail = SEAT_N1MM, "detect", "both present — default N1MM seat"
    else:
        kind, src, detail = SEAT_AMBIGUOUS, "ambiguous", "neither N1MM nor WSJT-X detected"

    return SeatProbe(
        seat_type=kind, wsjt_ini=wsjt_ini, wsjt_running=wsjt_running,
        n1mm_found=n1mm_found, n1mm_running=n1mm_running, source=src,
        detail=detail,
    )


def detect_seat_type() -> str:
    """Convenience: n1mm | wsjt | site | ambiguous."""
    return probe_seat().seat_type
