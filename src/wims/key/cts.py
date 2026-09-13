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
MS_CTS_ON = 0x0010

# CreateFile / GetCommModemStatus without HANDLE restype truncates 64-bit
# handles to 32-bit → ERROR_INVALID_HANDLE (6) on 64-bit Windows.
_k32 = None

_WINERR = {
    1: "not a serial port",
    2: "port not found",
    5: "access denied (port already open)",
    6: "invalid handle",
    32: "sharing violation (port already open)",
    1167: "device disconnected",
}


def win_com_path(device: str) -> str:
    """CreateFileW needs \\\\.\\COM10 for ports >= COM10; accept plain COMx."""
    dev = (device or "").strip()
    if re.fullmatch(r"(?i)COM\d+", dev):
        return "\\\\.\\" + dev.upper()
    return dev


def _kernel32():
    """kernel32 with pointer-sized HANDLE (must not use default c_int restype)."""
    global _k32
    if _k32 is not None:
        return _k32
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    k.GetCommModemStatus.restype = wintypes.BOOL
    k.GetCommModemStatus.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
    )
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32 = k
    return k


def _win_fail(op: str, device: str, code: int | None = None) -> str:
    import ctypes
    n = int(code if code is not None else (ctypes.get_last_error() or 0))
    hint = _WINERR.get(n)
    extra = f": {hint}" if hint else ""
    return f"{op} failed on {device} (win32 {n}{extra})"


def _handle_value(handle) -> int | None:
    """Normalize CreateFileW HANDLE to an int; None if invalid."""
    if handle is None:
        return None
    hv = int(getattr(handle, "value", handle) or 0)
    if hv == 0 or hv == -1 or hv == 0xFFFFFFFF or hv == 0xFFFFFFFFFFFFFFFF:
        return None
    return hv


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
        k = _kernel32()
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        OPEN_EXISTING = 3
        # Sense-only: no GENERIC_WRITE (that is what radio CAT often holds).
        ctypes.set_last_error(0)
        handle = k.CreateFileW(
            win_com_path(self.device), GENERIC_READ, FILE_SHARE_READ, None,
            OPEN_EXISTING, 0, None,
        )
        create_err = ctypes.get_last_error()
        hv = _handle_value(handle)
        if hv is None:
            self.error = _win_fail("CreateFile", self.device, create_err)
            return
        self._handle = hv
        # Probe now so a non-UART COM (or truncated handle) fails at open.
        ctypes.set_last_error(0)
        status = wintypes.DWORD(0)
        ok = k.GetCommModemStatus(
            wintypes.HANDLE(self._handle), ctypes.byref(status),
        )
        if not ok:
            self.error = _win_fail(
                "GetCommModemStatus", self.device, ctypes.get_last_error(),
            )
            self.close()

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._handle is not None:
            try:
                _kernel32().CloseHandle(self._handle)
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
        k = _kernel32()
        ctypes.set_last_error(0)
        status = wintypes.DWORD(0)
        ok = k.GetCommModemStatus(
            wintypes.HANDLE(self._handle), ctypes.byref(status),
        )
        if not ok:
            self.error = _win_fail(
                "GetCommModemStatus", self.device, ctypes.get_last_error(),
            )
            return False
        return bool(status.value & MS_CTS_ON)
