# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Diagnose N1MM TCP Log Call parsing against a live N1MM on :52001.

Not a guess: each variant gets a unique call. After send, read DXLOG.Call.
Skip if N1MM is not listening (CI).

Run:
  python tests/unit/test_n1mm_tcp_call.py
"""

from __future__ import annotations

import socket
import sqlite3
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.app import wrap_adif  # noqa: E402

N1MM_TCP = ("127.0.0.1", 52001)
DB = Path.home() / "Databases" / "ham.s3db"


def n1mm_tcp_up() -> bool:
    try:
        s = socket.create_connection(N1MM_TCP, timeout=0.4)
        s.close()
        return True
    except OSError:
        return False


def send_tcp(payload: bytes) -> None:
    s = socket.create_connection(N1MM_TCP, timeout=2.0)
    try:
        s.sendall(payload)
        try:
            s.shutdown(socket.SHUT_WR)
            s.settimeout(0.3)
            try:
                s.recv(4096)
            except OSError:
                pass
        except OSError:
            pass
    finally:
        s.close()


def dxlog_call(call: str) -> str | None:
    if not DB.is_file():
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT Call FROM DXLOG WHERE Call = ? ORDER BY TS DESC LIMIT 1",
            (call,),
        ).fetchone()
        if row:
            return row[0]
        row = con.execute(
            "SELECT Call FROM DXLOG WHERE TS >= datetime('now', '-2 minutes') "
            "AND (Comment = ? OR MiscText LIKE ?)",
            (call, f"%{call}%"),
        ).fetchone()
        return row[0] if row else ""
    finally:
        con.close()


def envelope(adif: str, *, space_after_gt: bool, n_includes_space: bool) -> bytes:
    raw = adif.encode("ascii")
    if space_after_gt and n_includes_space:
        raw = b" " + raw
        header = f"<command:3>Log <parameters:{len(raw)}>"
        return header.encode("ascii") + raw + b"\n"
    header = f"<command:3>Log <parameters:{len(raw)}>"
    if space_after_gt:
        header += " "
    return header.encode("ascii") + raw + b"\n"


class LiveN1mmCallTests(unittest.TestCase):
    """Live probe. Skipped in CI when :52001 is closed."""

    def _run(self, call: str, payload: bytes) -> str | None:
        if not self.live:
            self.skipTest("set WIMS_LIVE_N1MM=1 with N1MM :52001 and ham.s3db")
        send_tcp(payload)
        deadline = time.time() + 3.0
        last = None
        while time.time() < deadline:
            last = dxlog_call(call)
            if last:
                return last
            time.sleep(0.25)
        return last

    @classmethod
    def setUpClass(cls) -> None:
        import os
        cls.live = (
            os.environ.get("WIMS_LIVE_N1MM") == "1"
            and n1mm_tcp_up()
            and DB.is_file()
        )

    def test_current_wrap_adif(self):
        call = "W5WIMS"
        adif = (
            f"<call:{len(call)}>{call} <gridsquare:4>EN80 <mode:3>FT8 "
            f"<rst_sent:3>-06 <rst_rcvd:3>+14 <qso_date:8>20260913 "
            f"<time_on:6>{time.strftime('%H%M%S')} <band:2>2M "
            f"<freq:10>144.175400 <eor>"
        )
        got = self._run(call, wrap_adif(adif))
        print(f"\nDIAG wrap_adif -> DXLOG.Call={got!r} (want {call!r})")
        self.assertEqual(got, call)

    def test_space_after_parameters_not_in_N(self):
        call = "W8WIMS"
        adif = (
            f"<call:{len(call)}>{call} <gridsquare:4>EN80 <mode:3>FT8 "
            f"<qso_date:8>20260913 <time_on:6>{time.strftime('%H%M%S')} "
            f"<band:2>2M <freq:7>144.174 <eor>"
        )
        got = self._run(call, envelope(adif, space_after_gt=True, n_includes_space=False))
        print(f"\nDIAG space-after-> DXLOG.Call={got!r} (want {call!r})")
        self.assertEqual(got, call)

    def test_space_after_parameters_in_N(self):
        call = "W9WIMS"
        adif = (
            f"<call:{len(call)}>{call} <gridsquare:4>EN80 <mode:3>FT8 "
            f"<qso_date:8>20260913 <time_on:6>{time.strftime('%H%M%S')} "
            f"<band:2>2M <freq:7>144.174 <eor>"
        )
        got = self._run(call, envelope(adif, space_after_gt=True, n_includes_space=True))
        print(f"\nDIAG space-in-N -> DXLOG.Call={got!r} (want {call!r})")
        self.assertEqual(got, call)

    def test_wsjt_eoh_blob(self):
        call = "W6WIMS"
        adif = (
            "<adif_ver:5>3.1.0 <programid:6>WSJT-X <EOH> "
            f"<call:{len(call)}>{call} <gridsquare:4>EN80 <mode:3>FT8 "
            f"<qso_date:8>20260913 <time_on:6>{time.strftime('%H%M%S')} "
            f"<band:2>2m <freq:8>144.17400 <eor>"
        )
        raw = adif.encode("ascii")
        payload = f"<command:3>Log <parameters:{len(raw)}>".encode("ascii") + raw + b"\n"
        got = self._run(call, payload)
        print(f"\nDIAG EOH-blob -> DXLOG.Call={got!r} (want {call!r})")
        self.assertEqual(got, call)


if __name__ == "__main__":
    unittest.main(verbosity=2)
