# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compare the running site server's revision with the code on disk.

Pure helpers. The window calls these; tests do not open a window.
"""

from __future__ import annotations

# Mark on the Restart site server button, and the status-area title.
RESTART_NEEDED_MARK = "Restart needed"
RESTART_NEEDED_TIP = (
    "The server is running older code than what is installed. "
    "Restart to use the latest."
)
RESTART_PLAIN_TIP = (
    "Site server is on this PC — stop and start it again to load "
    "the latest code after Update WIMS / git pull."
)
# The two revision labels under the window title.
LAUNCHER_REV_TIP = "Launcher: the code this window loaded when it opened."
SERVER_REV_TIP = "Server: the code the site server loaded at start."
# Status area sentence when the running server and the disk checkout differ.
STALE_STATUS_DETAIL = RESTART_NEEDED_TIP
# Updates list, after Install, when the server is now stale.
UPDATE_STALE_NOTICE = "Restart server to finish the update"

_UNKNOWN = {"", "?", "none", "unknown"}


def revision_token(stamp: str | None) -> str:
    """Short SHA from a git stamp, or ``""`` when the revision is unknown."""
    text = (stamp or "").strip()
    if not text or text.lower() in _UNKNOWN:
        return ""
    token = text.split()[0]
    if token.lower() in _UNKNOWN:
        return ""
    return token


def server_restart_needed(disk_rev: str | None, server_rev: str | None) -> bool:
    """True only when both revisions are known and they differ.

    A server that is down, or an older build that does not report
    ``server_rev``, is not a mismatch. Unknown disk (``?``) is not either.
    """
    disk = revision_token(disk_rev)
    server = revision_token(server_rev)
    if not disk or not server:
        return False
    return disk != server


def _plain_version(version: str | None) -> str:
    ver = (version or "").strip()
    if ver.lower().startswith("v"):
        ver = ver[1:]
    return ver


def launcher_rev_label(version: str | None, launcher_rev: str | None) -> str:
    """``Launcher: v1.2.3 (stamp)`` — the code this window loaded when it opened."""
    ver = _plain_version(version)
    rev = (launcher_rev or "").strip()
    if not rev or rev == "?" or rev.lower() in _UNKNOWN:
        rev = ""
    if ver and rev:
        return f"Launcher: v{ver} ({rev})"
    if ver:
        return f"Launcher: v{ver}"
    if rev:
        return f"Launcher: ({rev})"
    return "Launcher"


def server_rev_label(version: str | None, server_rev: str | None) -> str:
    """``Server: v1.2.3 (abc1234 2026-…)``, or empty when the server did not say."""
    rev = (server_rev or "").strip()
    if not rev or rev == "?" or rev.lower() in _UNKNOWN:
        return ""
    ver = _plain_version(version)
    if ver:
        return f"Server: v{ver} ({rev})"
    return f"Server: ({rev})"


def _stamp_day(stamp: str | None) -> str:
    """``YYYY-MM-DD`` from a git stamp, or ``""``."""
    parts = (stamp or "").split()
    if len(parts) < 2:
        return ""
    token = parts[1]
    if (
        len(token) >= 10
        and token[4:5] == "-"
        and token[7:8] == "-"
        and token[:4].isdigit()
    ):
        return token[:10]
    return ""


def restart_server_tip(
    *,
    server_version: str | None,
    server_rev: str | None,
    disk_rev: str | None,
) -> str:
    """What Restart site server is about to reload, and whether it matches disk.

    ``disk_rev`` is the checkout on disk (installed code). ``server_rev`` is
    the revision ``/healthz`` says the server loaded at start.
    """
    ver = _plain_version(server_version)
    server_tok = revision_token(server_rev)
    disk_tok = revision_token(disk_rev)
    day = _stamp_day(server_rev)
    if server_tok:
        ver_bit = f"v{ver} " if ver else ""
        when = f", {day}" if day else ""
        running = f"Server running {ver_bit}({server_tok}{when})."
    else:
        running = "The server did not report a revision."
    if disk_tok:
        installed = f"Installed code: {disk_tok}."
    else:
        installed = "Installed code was not reported."
    if server_tok and disk_tok and server_tok == disk_tok:
        state = "Up to date."
    elif server_restart_needed(disk_rev, server_rev):
        state = RESTART_NEEDED_TIP
    else:
        state = RESTART_PLAIN_TIP
    return f"{running} {installed} {state}"


def update_install_notice(
    *,
    went_back: bool,
    disk_rev: str | None,
    server_rev: str | None,
    local_server: bool,
) -> str:
    """Updates-list sentence after Install, or empty when nothing extra is due.

    Go back, a server that is not on this PC, and an older build with no
    revision stay quiet.
    """
    if went_back or not local_server:
        return ""
    if server_restart_needed(disk_rev, server_rev):
        return UPDATE_STALE_NOTICE
    return ""
