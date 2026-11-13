# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dedicated console-window profile and a single-launch guard.

Snap Firefox is confined: it cannot write a profile under a hidden home
folder such as ~/.local/share/wims. For that browser, the profile lives
in ~/snap/firefox/common/ws-hub-console-profile. A file lock and a
remembered pid keep the launcher and a solo start from opening two
windows against the same profile at once.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# How long a launch holds the lock while we see whether the browser stays up.
CONSOLE_LAUNCH_GRACE_S = 4.0

_SNAP_PROFILE = Path("snap") / "firefox" / "common" / "ws-hub-console-profile"


def is_snap_firefox(executable: str | None) -> bool:
    """True when *executable* is the Ubuntu snap Firefox wrapper or binary."""
    if not executable:
        return False
    raw = str(executable).replace("\\", "/")
    if raw.startswith("/snap/") or "/snap/bin/" in raw or "/snap/firefox/" in raw:
        return True
    path = Path(executable)
    try:
        if not path.is_file():
            return False
        if path.stat().st_size > 16384:
            return False
        head = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\0" in head:
        return False
    text = head.decode("utf-8", "replace")
    return "/snap/bin/firefox" in text or "/snap/firefox/" in text


def default_kiosk_profile_dir() -> Path:
    """Non-snap Firefox/Chrome profile (XDG or LocalAppData)."""
    if sys.platform.startswith("win"):
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            return Path(local) / "WIMS" / "kiosk-profile"
        return Path.home() / "AppData" / "Local" / "WIMS" / "kiosk-profile"
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "kiosk-profile"
    return Path.home() / ".local" / "share" / "wims" / "kiosk-profile"


def firefox_kiosk_profile_dir(
    executable: str | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Profile directory Firefox can actually write for a console window."""
    if is_snap_firefox(executable):
        root = Path(home) if home is not None else Path.home()
        return root / _SNAP_PROFILE
    if home is not None:
        return Path(home) / ".local" / "share" / "wims" / "kiosk-profile"
    return default_kiosk_profile_dir()


def console_launch_lock_path() -> Path:
    """Lock file that serializes console-window launches on this PC."""
    env = (os.environ.get("WIMS_CONSOLE_LOCK") or "").strip()
    if env:
        return Path(env)
    runtime = (os.environ.get("XDG_RUNTIME_DIR") or "").strip()
    if runtime:
        return Path(runtime) / "ws-hub-console.lock"
    if sys.platform.startswith("win"):
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "WIMS" / "console-launch.lock"
    try:
        uid = os.getuid()
    except AttributeError:
        uid = os.getpid()
    return Path("/tmp") / f"ws-hub-console-{uid}.lock"


def console_launch_pid_path() -> Path:
    return console_launch_lock_path().with_suffix(".pid")


def pid_is_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def live_console_pid() -> int | None:
    path = console_launch_pid_path()
    try:
        raw = path.read_text(encoding="ascii").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return None
    if pid_is_running(pid):
        return pid
    try:
        path.unlink()
    except OSError:
        pass
    return None


def remember_console_pid(pid: int) -> None:
    path = console_launch_pid_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(pid)) + "\n", encoding="ascii")
    except OSError:
        pass


def clear_console_pid() -> None:
    try:
        console_launch_pid_path().unlink()
    except OSError:
        pass


def _lock_exclusive(fd: int, *, nonblocking: bool) -> bool:
    if sys.platform.startswith("win"):
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    flags = fcntl.LOCK_EX
    if nonblocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
    except BlockingIOError:
        return False
    return True


def _unlock(fd: int) -> None:
    try:
        if sys.platform.startswith("win"):
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def hold_console_launch_lock(timeout_s: float = 8.0):
    """Exclusive lock so only one process starts a console window at a time."""
    path = console_launch_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    got = False
    try:
        while True:
            if _lock_exclusive(fd, nonblocking=True):
                got = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        yield got
    finally:
        if got:
            _unlock(fd)
        os.close(fd)


def console_process_stayed_up(proc, timeout_s: float | None = None) -> bool:
    """False when the just-started browser exits within the grace period."""
    grace = CONSOLE_LAUNCH_GRACE_S if timeout_s is None else float(timeout_s)
    if grace <= 0:
        return proc.poll() is None
    deadline = time.monotonic() + grace
    while True:
        code = proc.poll()
        if code is not None:
            return False
        now = time.monotonic()
        if now >= deadline:
            return True
        time.sleep(min(0.1, deadline - now))
