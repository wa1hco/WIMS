# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multicast join / IGMP rejoin helpers (no real network)."""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.udp import sink


class FakeSock:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or []

    def setsockopt(self, level, opt, value):
        self.calls.append((level, opt, value))
        key = (opt, value)
        if opt in self.fail_on or key in self.fail_on:
            raise OSError("simulated join fail")


class JoinHelperTests(unittest.TestCase):
    def test_join_multicast_tries_every_iface(self):
        sock = FakeSock()
        with mock.patch("wims.udp.sink._join_iface_ips",
                        return_value=["192.168.10.12", "10.0.0.1", "0.0.0.0"]):
            joined = sink.join_multicast(sock, "224.0.0.73", "0.0.0.0")
        self.assertEqual(joined, ["192.168.10.12", "10.0.0.1", "0.0.0.0"])
        self.assertEqual(len(sock.calls), 3)
        self.assertTrue(all(c[1] == socket.IP_ADD_MEMBERSHIP for c in sock.calls))

    def test_join_multicast_skips_failed_iface(self):
        bad = socket.inet_aton("10.0.0.1")
        sock = FakeSock()
        orig = FakeSock.setsockopt

        def maybe_fail(self, level, opt, value):
            if value[4:8] == bad:
                raise OSError("nope")
            return orig(self, level, opt, value)

        sock.setsockopt = maybe_fail.__get__(sock, FakeSock)
        with mock.patch("wims.udp.sink._join_iface_ips",
                        return_value=["192.168.10.12", "10.0.0.1"]):
            joined = sink.join_multicast(sock, "224.0.0.73")
        self.assertEqual(joined, ["192.168.10.12"])

    def test_rejoin_drops_then_adds(self):
        sock = FakeSock()
        drop = getattr(socket, "IP_DROP_MEMBERSHIP", None)
        with mock.patch("wims.udp.sink._join_iface_ips", return_value=["192.168.10.12"]):
            joined = sink.rejoin_multicast(sock, "224.0.0.73")
        self.assertEqual(joined, ["192.168.10.12"])
        opts = [c[1] for c in sock.calls]
        self.assertEqual(opts[-1], socket.IP_ADD_MEMBERSHIP)
        if drop is not None:
            self.assertEqual(opts[0], drop)
            self.assertEqual(len(opts), 2)


if __name__ == "__main__":
    unittest.main()
