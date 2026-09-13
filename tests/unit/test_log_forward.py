# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Log-agent apply + site Logged-QSO relay (no N1MM)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.app import LogState, apply_logged_qso
from wims.server.app import LiveFleet
from wims.udp import encode as E, messages as M


class ApplyLoggedTests(unittest.TestCase):
    def test_wait_until_band(self):
        st = LogState()
        apply_logged_qso(
            st, instance="WSJT-X - 2M-Trailer", call="K1ABC", band="2m",
            adif="<CALL:5>K1ABC <BAND:2>2M <eor>", src="test",
            dry_run=True, host="127.0.0.1", udp_port=2333, tcp_port=52001,
        )
        self.assertEqual(st.n_wait, 1)
        self.assertEqual(st.n_fwd, 0)

    def test_drop_other_band(self):
        st = LogState()
        st.live_band = "2m"
        apply_logged_qso(
            st, instance="WSJT-X - 6M-WAMC", call="K1ABC", band="6m",
            adif="<CALL:5>K1ABC <BAND:2>6M <eor>", src="test",
            dry_run=True, host="127.0.0.1", udp_port=2333, tcp_port=52001,
        )
        self.assertEqual(st.n_drop, 1)
        self.assertEqual(st.n_fwd, 0)

    def test_fwd_and_dedupe(self):
        st = LogState()
        st.live_band = "2m"
        adif = "<CALL:5>K1ABC <BAND:2>2M <GRIDSQUARE:4>FN42 <MODE:3>FT8 <eor>"
        apply_logged_qso(
            st, instance="WSJT-X - 2M-Trailer", call="K1ABC", band="2m",
            adif=adif, src="udp", dry_run=True,
            host="127.0.0.1", udp_port=2333, tcp_port=52001,
        )
        apply_logged_qso(
            st, instance="WSJT-X - 2M-Trailer", call="K1ABC", band="2m",
            adif=adif, src="site-relay", dry_run=True,
            host="127.0.0.1", udp_port=2333, tcp_port=52001,
        )
        self.assertEqual(st.n_fwd, 1)

    def test_site_logged_qsos_since(self):
        live = LiveFleet()
        raw = E.build_logged_adif(
            "WSJT-X - 2M-Trailer",
            "<CALL:5>VE3DS <BAND:2>2M <MODE:3>FT8 <GRIDSQUARE:4>FN03 <eor>",
        )
        live.observe_wsjtx(M.parse(raw), now=100.0, src_ip="192.168.10.11", src_port=1)
        qsos = live.logged_qsos_since(99.0)
        self.assertEqual(len(qsos), 1)
        self.assertEqual(qsos[0]["call"], "VE3DS")
        self.assertEqual(live.logged_qsos_since(100.0), [])


if __name__ == "__main__":
    unittest.main()
