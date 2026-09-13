# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows KEY/CTS CreateFile + GetCommModemStatus handle path."""

from __future__ import annotations

import ctypes
import sys
import unittest
from pathlib import Path
from unittest import mock
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.key.cts import (  # noqa: E402
    CtsSource, _handle_value, _win_fail, win_com_path,
)


class FakeK32:
    def __init__(self, handle=0x7FF6_ABCD_0000, modem_ok=True, cts=True):
        self.handle = handle
        self.modem_ok = modem_ok
        self.cts = cts
        self.got_handle = None
        self.closed = []

    def CreateFileW(self, *args):
        self.create_args = args
        return self.handle

    def GetCommModemStatus(self, handle, pstatus):
        self.got_handle = int(getattr(handle, "value", handle) or 0)
        if self.modem_ok:
            val = 0x0010 if self.cts else 0
            ctypes.memmove(pstatus, ctypes.byref(wintypes.DWORD(val)), 4)
            return 1
        return 0

    def CloseHandle(self, handle):
        self.closed.append(int(getattr(handle, "value", handle) or 0))
        return 1


class HandleValueTests(unittest.TestCase):
    def test_64bit_handle_kept(self):
        self.assertEqual(_handle_value(0x7FF6ABCD0000), 0x7FF6ABCD0000)

    def test_invalid_rejected(self):
        self.assertIsNone(_handle_value(-1))
        self.assertIsNone(_handle_value(0))
        self.assertIsNone(_handle_value(0xFFFFFFFFFFFFFFFF))
        self.assertIsNone(_handle_value(None))


class WinFailTests(unittest.TestCase):
    def test_includes_device_and_code(self):
        with mock.patch("ctypes.get_last_error", return_value=6):
            msg = _win_fail("GetCommModemStatus", "COM7")
        self.assertIn("COM7", msg)
        self.assertIn("win32 6", msg)
        self.assertIn("invalid handle", msg)


class CtsWinTests(unittest.TestCase):
    def test_open_reads_cts_on_64bit_handle(self):
        fake = FakeK32(handle=0x7FF6ABCD0000, cts=True)
        with mock.patch("wims.key.cts._kernel32", return_value=fake):
            src = CtsSource.open("COM7")
            self.assertIsNone(src.error)
            self.assertEqual(src._handle, 0x7FF6ABCD0000)
            self.assertTrue(src.read())
            self.assertEqual(fake.got_handle, 0x7FF6ABCD0000)
            src.close()

    def test_modem_status_fail_names_port(self):
        fake = FakeK32(modem_ok=False)
        with mock.patch("wims.key.cts._kernel32", return_value=fake):
            with mock.patch("ctypes.get_last_error", return_value=1):
                src = CtsSource.open("COM3")
        self.assertIsNotNone(src.error)
        self.assertIn("GetCommModemStatus", src.error)
        self.assertIn("COM3", src.error)
        self.assertIsNone(src._handle)  # closed after probe fail

    def test_sim_unchanged(self):
        up = CtsSource.open("sim:up")
        self.assertIsNone(up.error)
        self.assertTrue(up.read())
        down = CtsSource.open("sim:down")
        self.assertFalse(down.read())

    def test_com_path(self):
        self.assertEqual(win_com_path("COM7"), r"\\.\COM7")

    def test_open_is_read_only_shared(self):
        fake = FakeK32()
        with mock.patch("wims.key.cts._kernel32", return_value=fake):
            src = CtsSource.open("COM7")
            src.close()
        access, share = fake.create_args[1], fake.create_args[2]
        self.assertEqual(access, 0x80000000)  # GENERIC_READ
        self.assertEqual(share, 0x00000001)   # FILE_SHARE_READ

    def test_access_denied_does_not_blame_n1mm(self):
        msg = _win_fail("CreateFile", "COM3", 5)
        self.assertIn("already open", msg)
        self.assertNotIn("N1MM", msg)
        self.assertNotIn("WSJT", msg)


class SenseRetryTests(unittest.TestCase):
    def test_sense_loop_reopens_after_first_fail(self):
        import threading
        import time
        from wims.key.runtime import KeyRuntime

        opens: list[str] = []

        class Boom:
            error = "CreateFile failed on COM3 (win32 5: access denied (port already open))"
            def read(self):
                return False
            def close(self):
                pass

        class Ok:
            error = None
            def read(self):
                return False
            def close(self):
                pass

        def fake_open(dev):
            opens.append(dev)
            return Boom() if len(opens) == 1 else Ok()

        with mock.patch("wims.key.runtime.CtsSource.open", side_effect=fake_open):
            with mock.patch("wims.key.runtime.CTS_RETRY_S", 0.05):
                rt = KeyRuntime(device="COM3")
                t = threading.Thread(target=rt._sense_loop, daemon=True)
                t.start()
                deadline = time.time() + 2.0
                while len(opens) < 2 and time.time() < deadline:
                    time.sleep(0.02)
                rt._stop.set()
                t.join(timeout=1.0)
        self.assertGreaterEqual(len(opens), 2)
        self.assertIsNone(rt.state.snapshot()["cts_error"])


if __name__ == "__main__":
    unittest.main()
