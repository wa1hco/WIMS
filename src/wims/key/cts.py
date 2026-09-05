# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""KEY/CTS sense helpers for the Key runtime.

Linux: stdlib fcntl TIOCMGET (same path as inhibit_bench).
Windows: best-effort GetCommModemStatus via ctypes; falls back to idle.
Special device ``sim:down`` / ``sim:up`` for lab without hardware.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass


TIOCMGET = 0x5415
TIOCM_CTS = 0x020


def win_com_path(device: str) -> str:
    """CreateFileW needs \\\\.\\COM10 for ports >= COM10; accept plain COMx."""
    dev = (device or "").strip()
    if re.fullmatch(r"(?i)COM\d+", dev):
        return "\\\\.\\" + dev.upper()
    return dev


@dataclass
class CtsSource:
    """Open a KEY sense path. ``read()`` → True when KEY/CTS asserted."""

    device: str
    _fd: int | None = None
    _handle: int | None = None
    _sim: bool | None = None
    error: str | None = None

    @classmethod
    def open(cls, device: str) -> CtsSource:
        dev = (device or "").strip()
        src = cls(device=dev)
        if not dev:
            src.error = "no KEY device configured"
            return src
        if dev.lower().startswith("sim:"):
            # sim:up = always keyed; sim:down / sim = idle
            src._sim = dev.lower() in ("sim:up", "sim:1", "sim:true")
            return src
        if sys.platform.startswith("win"):
            src._open_win()
        else:
            src._open_linux()
        return src

    def _open_linux(self) -> None:
        try:
            self._fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            self.error = str(e)
            self._fd = None

    def _open_win(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError as e:
            self.error = f"ctypes unavailable: {e}"
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        handle = kernel32.CreateFileW(
            win_com_path(self.device), GENERIC_READ | GENERIC_WRITE, 0, None,
            OPEN_EXISTING, 0, None,
        )
        INVALID = wintypes.HANDLE(-1).value
        if handle == INVALID or handle is None:
            self.error = f"CreateFile failed for {self.device}"
            return
        self._handle = int(handle)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._handle is not None:
            try:
                import ctypes
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    def read(self) -> bool:
        if self._sim is not None:
            return self._sim
        if self.error:
            return False
        if self._fd is not None:
            return self._read_linux()
        if self._handle is not None:
            return self._read_win()
        return False

    def _read_linux(self) -> bool:
        import fcntl
        import struct
        assert self._fd is not None
        try:
            res = fcntl.ioctl(self._fd, TIOCMGET, struct.pack("I", 0))
            return bool(struct.unpack("I", res)[0] & TIOCM_CTS)
        except OSError as e:
            self.error = str(e)
            return False

    def _read_win(self) -> bool:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        status = wintypes.DWORD()
        ok = kernel32.GetCommModemStatus(self._handle, ctypes.byref(status))
        if not ok:
            self.error = "GetCommModemStatus failed"
            return False
        MS_CTS_ON = 0x0010
        return bool(status.value & MS_CTS_ON)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._handle is not None and sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
