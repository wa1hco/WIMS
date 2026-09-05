# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Git revision stamp for operator-facing banners (SHA + commit date-time)."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def git_stamp(repo: Path | None = None) -> str:
    """Return ``abc1234 2026-09-05 14:42 -0400`` (or ``?`` if not a git tree)."""
    root = Path(repo) if repo is not None else _REPO
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "log", "-1", "--format=%h %ci"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return (out or "").strip() or "?"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "?"


def git_short(repo: Path | None = None) -> str:
    """Short SHA only (first token of :func:`git_stamp`)."""
    stamp = git_stamp(repo)
    return stamp.split()[0] if stamp and stamp != "?" else "?"
