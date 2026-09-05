# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Single desktop launcher per user session.

A second ``python -m wims.launcher`` must not open another window or call
``replace_seat_agents`` (that would restart seat agents under a new parent).
Uses an exclusive lock file under the user config dir.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

_lock_fp = None  # keep alive for process lifetime


def _lock_path() -> Path:
    env = (os.environ.get("WIMS_LAUNCHER_LOCK") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "launcher.lock"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "launcher.lock"
    return Path.home() / ".config" / "wims" / "launcher.lock"


def try_acquire_launcher_lock() -> bool:
    """Return True if this process now owns the launcher lock.

    False means another launcher is already running. Safe to call once at
    process start; holds the lock until exit.
    """
    global _lock_fp
    if _lock_fp is not None:
        return True
    path = _lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fp = open(path, "a+", encoding="utf-8")  # noqa: SIM115
    except OSError:
        return True  # cannot lock → do not block the operator

    try:
        if sys.platform == "win32":
            ok = _lock_win(fp)
        else:
            ok = _lock_posix(fp)
    except Exception:
        try:
            fp.close()
        except OSError:
            pass
        return True

    if not ok:
        try:
            fp.close()
        except OSError:
            pass
        return False

    try:
        fp.seek(0)
        fp.truncate()
        fp.write(f"{os.getpid()}\n")
        fp.flush()
    except OSError:
        pass
    _lock_fp = fp
    atexit.register(_release_launcher_lock)
    return True


def _lock_posix(fp) -> bool:
    import fcntl
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except OSError:
        return False


def _lock_win(fp) -> bool:
    import msvcrt
    try:
        fp.seek(0)
        # Lock one byte; fails if another process holds it.
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _release_launcher_lock() -> None:
    global _lock_fp
    fp = _lock_fp
    _lock_fp = None
    if fp is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            fp.seek(0)
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            fp.close()
        except OSError:
            pass
