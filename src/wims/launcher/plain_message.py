# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plain messages that do not need the Python window library.

The Linux double-click scripts say the same thing. This module is the
fallback when Python itself is running and Tk did not load.
"""

from __future__ import annotations

import os
import shutil
import subprocess


WINDOW_LIBRARY_MESSAGE = (
    "WIMS needs the Python window library.\n"
    "\n"
    "Install python3-tk, then double-click WIMS again.\n"
    "On Fedora, the package is python3-tkinter."
)


def _have_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def show_plain_message(text: str, *, title: str = "WIMS") -> bool:
    """Show a dialog without Tk. True when a dialog tool was started."""
    if not _have_display():
        return False
    commands: list[list[str]] = []
    if shutil.which("zenity"):
        commands.append(
            ["zenity", "--info", "--title", title, "--width", "480", "--text", text]
        )
    if shutil.which("kdialog"):
        commands.append(["kdialog", "--title", title, "--msgbox", text])
    if shutil.which("yad"):
        commands.append(
            ["yad", "--title", title, "--text", text, "--button", "OK:0", "--width", "480"]
        )
    if shutil.which("xmessage"):
        commands.append(["xmessage", "-center", "-title", title, text])
    for cmd in commands:
        try:
            subprocess.run(cmd, check=False)
            return True
        except OSError:
            continue
    return False


def is_missing_window_library(exc: BaseException) -> bool:
    name = getattr(exc, "name", "") or ""
    if name == "tkinter" or name.startswith("tkinter."):
        return True
    return "tkinter" in str(exc)
