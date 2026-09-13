# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""N1mmTcpClient must not park an idle socket on :52001."""

from __future__ import annotations

import socket
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.app import N1mmTcpClient


class TcpClientTests(unittest.TestCase):
    def test_try_connect_does_not_hold_socket(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        accepted = []

        def accept_one():
            srv.settimeout(2.0)
            try:
                c, _ = srv.accept()
                accepted.append(c)
            except OSError:
                pass

        t = threading.Thread(target=accept_one, daemon=True)
        t.start()
        client = N1mmTcpClient("127.0.0.1", port)
        self.assertTrue(client.try_connect())
        t.join(timeout=2.0)
        self.assertTrue(accepted)
        peer = accepted[0]
        peer.settimeout(0.8)
        # Probe must FIN so N1MM's next Log accept is free. Idle hold would
        # leave this recv blocking until the agent later sends.
        try:
            data = peer.recv(16)
        except socket.timeout:
            self.fail("try_connect left an idle TCP session (wedges N1MM :52001)")
        self.assertEqual(data, b"")
        self.assertIsNone(client._sock)
        peer.close()
        srv.close()

    def test_try_connect_false_when_nothing_listens(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.close()
        client = N1mmTcpClient("127.0.0.1", port)
        self.assertFalse(client.try_connect())
        self.assertFalse(client.alive)


if __name__ == "__main__":
    unittest.main()
