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
    "the latest code after an update or git pull."
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


def revisions_match(
    disk_rev: str | None,
    server_rev: str | None,
    *,
    disk_version: str | None = None,
    server_version: str | None = None,
) -> bool:
    """True when the running server is the same copy as the tree on disk.

    Compare revision tokens when both are known. When both are unknown
    (``?``, empty, or missing), compare package versions instead. A SHA
    is never compared to a version string. One known token and one
    unknown is not a match.
    """
    disk = revision_token(disk_rev)
    server = revision_token(server_rev)
    if disk and server:
        return disk == server
    if disk or server:
        return False
    dv = _plain_version(disk_version)
    sv = _plain_version(server_version)
    return bool(dv and sv and dv == sv)


def server_restart_needed(
    disk_rev: str | None,
    server_rev: str | None,
    *,
    disk_version: str | None = None,
    server_version: str | None = None,
) -> bool:
    """True only when both identities are known and they differ.

    A server that is down, or an older build that does not report
    ``server_rev``, is not a mismatch. Unknown disk (``?``) is not
    either, unless both sides lack a revision and the package versions
    are known and differ.
    """
    disk = revision_token(disk_rev)
    server = revision_token(server_rev)
    if disk and server:
        return disk != server
    if not disk and not server:
        dv = _plain_version(disk_version)
        sv = _plain_version(server_version)
        return bool(dv and sv and dv != sv)
    return False


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
    disk_version: str | None = None,
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
    if revisions_match(
        disk_rev, server_rev,
        disk_version=disk_version, server_version=server_version,
    ):
        state = "Up to date."
    elif server_restart_needed(
        disk_rev, server_rev,
        disk_version=disk_version, server_version=server_version,
    ):
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
    disk_version: str | None = None,
    server_version: str | None = None,
) -> str:
    """Updates-list sentence after Install, or empty when nothing extra is due.

    Go back, a server that is not on this PC, and an older build with no
    revision stay quiet. A version-only mismatch still asks for a restart.
    """
    if went_back or not local_server:
        return ""
    if server_restart_needed(
        disk_rev, server_rev,
        disk_version=disk_version, server_version=server_version,
    ):
        return UPDATE_STALE_NOTICE
    return ""
