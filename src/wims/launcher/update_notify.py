# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gentle 'update available' prods — never steal keyboard/mouse focus.

Used when a bugfix lands on main mid-contest and operators are not
staring at the launcher. Detection stays pull-on-click; this only nudges.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from wims.launcher.update_check import UpdateInfo, check_git_update, env_skip_update_check


def _nag_path() -> Path:
    env = (os.environ.get("WIMS_UPDATE_NAG") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "update_nag.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "update_nag.json"
    return Path.home() / ".config" / "wims" / "update_nag.json"


def already_nagged(remote_sha: str) -> bool:
    sha = (remote_sha or "").strip()
    if not sha:
        return True
    try:
        raw = json.loads(_nag_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (raw.get("nagged_remote_sha") or "") == sha


def mark_nagged(remote_sha: str) -> None:
    path = _nag_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": 1, "nagged_remote_sha": remote_sha}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def notify_no_focus(title: str, body: str) -> bool:
    """Desktop notification that must not activate/focus another app's window.

    Returns True if a notify attempt was made (not proof the user saw it).
    """
    title = (title or "WIMS").strip()
    body = (body or "").strip()
    if sys.platform.startswith("win"):
        return _notify_windows(title, body)
    return _notify_linux(title, body)


def _notify_linux(title: str, body: str) -> bool:
    try:
        subprocess.run(
            ["notify-send", "--urgency=normal", "--expire-time=20000", title, body],
            check=False,
            timeout=5,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _notify_windows(title: str, body: str) -> bool:
    # Toast via WinRT — does not steal focus from N1MM/WSJT when done this way.
    import html as _html

    def _q(s: str) -> str:
        # XML text + PowerShell here-string safety.
        return _html.escape(s, quote=True).replace("'", "''")

    ps = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{_q(title)}</text>
      <text>{_q(body)}</text>
    </binding>
  </visual>
</toast>
"@
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('WIMS')
$notifier.Show($toast)
"""
    try:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-Command", ps,
            ],
            check=False,
            timeout=15,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def check_and_nudge(
    repo: Path | None = None,
    *,
    fetch: bool = True,
) -> UpdateInfo | None:
    """If behind main and not yet nagged for that SHA, fire a gentle notify.

    Returns the UpdateInfo when available (whether or not nag was sent).
    """
    if env_skip_update_check():
        return None
    info = check_git_update(repo, fetch=fetch)
    if not info.available:
        return info
    if already_nagged(info.remote_sha):
        return info
    subj = info.remote_subject or "bugfix / improvement on main"
    body = (
        f"{info.local_short} -> {info.remote_short}: {subj}. "
        "When convenient, run Desktop 'Update WIMS' (does not auto-install)."
    )
    if notify_no_focus("WIMS update available", body):
        mark_nagged(info.remote_sha)
    return info
