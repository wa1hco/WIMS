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


def server_rev_label(version: str | None, server_rev: str | None) -> str:
    """``Server: v1.2.3 (abc1234 2026-…)``, or empty when the server did not say."""
    rev = (server_rev or "").strip()
    if not rev or rev == "?" or rev.lower() in _UNKNOWN:
        return ""
    ver = (version or "").strip()
    if ver:
        return f"Server: v{ver} ({rev})"
    return f"Server: ({rev})"


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
