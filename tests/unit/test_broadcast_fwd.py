# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.broadcast_fwd import (
    BroadcastForwarder,
    is_contact_xml,
    is_radioinfo,
    looks_like_n1mm_broadcast_xml,
)
from wims.server.app import LiveFleet


RADIO = """<?xml version="1.0"?>
<RadioInfo>
  <app>N1MM</app>
  <StationName>W10VM-50</StationName>
  <RadioNr>1</RadioNr>
  <Freq>14417400</Freq>
  <TXFreq>14417400</TXFreq>
  <Mode>USB</Mode>
</RadioInfo>
"""

CONTACT = """<?xml version="1.0"?>
<contactinfo>
  <app>N1MM</app>
  <StationName>W10VM-50</StationName>
  <call>K1ABC</call>
  <band>2</band>
</contactinfo>
"""


class BroadcastFwdHelpers(unittest.TestCase):
    def test_detect_xml(self):
        self.assertTrue(looks_like_n1mm_broadcast_xml(RADIO))
        self.assertTrue(is_radioinfo(RADIO))
        self.assertFalse(is_contact_xml(RADIO))
        self.assertTrue(is_contact_xml(CONTACT))
        self.assertFalse(looks_like_n1mm_broadcast_xml("W10VM-50%192.168.1.120%12070"))


class BroadcastForwarderTests(unittest.TestCase):
    def test_nosite(self):
        f = BroadcastForwarder(site_url=None, agent_id="t", lan_ip="192.168.1.120")
        self.assertEqual(f.maybe_forward(RADIO, now=1.0), "nosite")

    def test_rate_limit_radioinfo(self):
        posts = []

        class Resp:
            status = 200
            def read(self):
                return b'{"ok":true}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            posts.append(json.loads(req.data.decode()))
            return Resp()

        f = BroadcastForwarder(
            site_url="http://127.0.0.1:8787",
            agent_id="vm-n1mm",
            lan_ip="192.168.1.120",
        )
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(f.maybe_forward(RADIO, now=10.0), "sent")
            self.assertEqual(f.maybe_forward(RADIO, now=10.5), "skip")
            self.assertEqual(f.maybe_forward(RADIO, now=13.0), "sent")
            self.assertEqual(f.maybe_forward(CONTACT, now=13.1), "sent")
        self.assertEqual(len(posts), 3)
        self.assertEqual(posts[0]["lan_ip"], "192.168.1.120")
        self.assertIn("RadioInfo", posts[0]["xml"])


class ServerBroadcastIngestTests(unittest.TestCase):
    def test_accept_creates_logger(self):
        live = LiveFleet()
        r = live.accept_n1mm_broadcast({
            "agent_id": "W10VM-50-n1mm",
            "lan_ip": "192.168.1.120",
            "xml": RADIO,
            "ts": 100.0,
        }, now=100.0)
        self.assertTrue(r["ok"])
        self.assertIn("W10VM-50", live._tracker.loggers)
        lg = live._tracker.loggers["W10VM-50"]
        self.assertIn("192.168.1.120", lg.hosts)


if __name__ == "__main__":
    unittest.main()
