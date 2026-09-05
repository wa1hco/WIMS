# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enumerate KEY/CTS serial devices (stdlib only)."""

from __future__ import annotations

import glob
import sys
from pathlib import Path


LAB_DEVICES = ("sim:down", "sim:up")


def list_key_devices() -> list[str]:
    """Return candidate KEY sense paths: real ports first, then lab sims.

    Order is stable. Does not open ports.
    """
    found: list[str] = []
    if sys.platform.startswith("win"):
        found.extend(_list_win_com())
    else:
        found.extend(_list_linux_tty())
    for lab in LAB_DEVICES:
        if lab not in found:
            found.append(lab)
    return found


def _list_linux_tty() -> list[str]:
    paths: list[str] = []
    # Prefer by-id symlinks (stable names) when present.
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    for p in by_id:
        try:
            real = str(Path(p).resolve())
        except OSError:
            real = p
        if real not in paths:
            paths.append(real)
        if p not in paths:
            paths.append(p)
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*"):
        for p in sorted(glob.glob(pattern)):
            if p not in paths:
                paths.append(p)
    return paths


def _list_win_com() -> list[str]:
    """COM ports from the SERIALCOMM registry map (no pyserial)."""
    try:
        import winreg
    except ImportError:
        return []
    ports: list[str] = []
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DEVICEMAP\SERIALCOMM",
        )
    except OSError:
        return []
    try:
        i = 0
        while True:
            try:
                _name, value, _typ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            if isinstance(value, str) and value.upper().startswith("COM"):
                ports.append(value.upper())
    finally:
        winreg.CloseKey(key)
    # Natural sort: COM2 before COM10
    def _key(p: str) -> tuple:
        digits = "".join(c for c in p if c.isdigit())
        return (int(digits) if digits else 0, p)

    return sorted(set(ports), key=_key)
