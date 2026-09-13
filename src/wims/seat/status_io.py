# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""N1MM-seat status snapshot for the launcher (one window; no agent Tk)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def status_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or "."
    d = Path(base) / "WIMS"
    return d / "n1mm-seat-status.json"


def write_status(payload: dict[str, Any]) -> None:
    path = status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def clear_status() -> None:
    try:
        status_path().unlink(missing_ok=True)
    except OSError:
        pass


def read_status(*, max_age_s: float = 8.0) -> dict[str, Any] | None:
    path = status_path()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        age = time.time() - float(data.get("ts") or 0)
    except (TypeError, ValueError):
        return None
    if age > max_age_s:
        return None
    return data
