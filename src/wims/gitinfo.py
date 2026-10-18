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


def _read_git_stamp(root: Path) -> str:
    """Return ``abc1234 2026-09-05 14:42 -0400`` (or ``?`` if not a git tree)."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "log", "-1", "--format=%h %ci"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (out or "").strip() or "?"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "?"


@lru_cache(maxsize=1)
def git_stamp(repo: Path | None = None) -> str:
    """Revision cached for this process (the code it loaded).

    The site server records this once at start and keeps reporting it.
    Use :func:`git_stamp_fresh` to re-read the checkout on disk.
    """
    root = Path(repo) if repo is not None else _REPO
    return _read_git_stamp(root)


def git_stamp_fresh(repo: Path | None = None) -> str:
    """Re-read HEAD from disk. Does not reuse the process-start cache.

    One ``git log -1``. The launcher calls this on its periodic refresh
    and after an update, so a branch change shows up without restarting
    the window.
    """
    root = Path(repo) if repo is not None else _REPO
    return _read_git_stamp(root)


def git_short(repo: Path | None = None) -> str:
    """Short SHA only (first token of :func:`git_stamp`)."""
    stamp = git_stamp(repo)
    return stamp.split()[0] if stamp and stamp != "?" else "?"
