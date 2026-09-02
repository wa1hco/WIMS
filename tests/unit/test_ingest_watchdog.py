# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ingest loop harden + heartbeat watchdog (no real network)."""

from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.server.app import LiveFleet, ingest_loop, start_ingest, start_ingest_watchdog


class _BoomFleet(LiveFleet):
    def observe_wsjtx(self, msg, now, src_ip, src_port=None):
        raise RuntimeError("simulated observe failure")


class IngestHardenTests(unittest.TestCase):
    def test_observe_exception_does_not_kill_loop(self):
        live = _BoomFleet()

        class FakeSock:
            def recvfrom(self, n):
                return b"\x00" * 32, ("127.0.0.1", 9999)

        sock = FakeSock()
        calls = {"n": 0}

        def fake_select(r, w, x, timeout=0):
            calls["n"] += 1
            if calls["n"] > 3:
                live._ingest_generation += 1  # force loop exit
                return [], [], []
            return [sock], [], []

        live._ingest_generation = 1
        with mock.patch("wims.server.app.select.select", side_effect=fake_select):
            with mock.patch("wims.server.app.M.parse", return_value=object()):
                ingest_loop(live, [sock], None, None, generation=1)

        self.assertGreaterEqual(live.ingest_errors, 1)
        self.assertGreater(live.ingest_heartbeat_mono, 0.0)

    def test_watchdog_restarts_dead_thread(self):
        live = LiveFleet()
        live.ingest_heartbeat_mono = time.monotonic() - 60.0  # already stalled
        # Pretend there was a dead ingest thread.
        dead = threading.Thread(target=lambda: None, daemon=True)
        dead.start()
        dead.join(timeout=1.0)
        live._ingest_thread = dead
        live._ingest_generation = 0

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))

        started = {"n": 0}
        real_start = start_ingest

        def counting_start(live_, wsjt, n1mm, gt):
            started["n"] += 1
            # Stop watchdog after first restart.
            live_._ingest_watchdog_stop.set()
            return real_start(live_, wsjt, n1mm, gt)

        with mock.patch("wims.server.app.start_ingest", side_effect=counting_start):
            start_ingest_watchdog(
                live, [sock], None, None, stall_s=0.1, period_s=0.05,
            )
            deadline = time.time() + 2.0
            while started["n"] < 1 and time.time() < deadline:
                time.sleep(0.05)

        self.assertGreaterEqual(started["n"], 1)
        self.assertGreaterEqual(live.ingest_restarts, 1)
        sock.close()


if __name__ == "__main__":
    unittest.main()
