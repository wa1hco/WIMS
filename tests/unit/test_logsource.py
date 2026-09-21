# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for LogSource protocol + N1MM adapter."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.logsource import (  # noqa: E402
    LogEvent,
    LogSource,
    N1mmLogSource,
)
from wims.state.logstore import LogStore  # noqa: E402


class LogSourceProtocolTests(unittest.TestCase):
    def test_n1mm_source_is_logsource(self):
        src = N1mmLogSource()
        self.assertIsInstance(src, LogSource)
        self.assertEqual(src.kind, "n1mm")
        self.assertEqual(src.title, "N1MM+")

    def test_parse_live_contactinfo(self):
        src = N1mmLogSource()
        xml = (
            "<contactinfo><app>N1MM</app><ID>abcd1234</ID><call>W1AW</call>"
            "<band>50</band><gridsquare>FN31</gridsquare><points>1</points>"
            "<ismultiplier1>1</ismultiplier1>"
            "<contestname>ARRL-VHF-JUN</contestname></contactinfo>"
        )
        ev = src.parse_live(xml)
        self.assertIsNotNone(ev)
        assert ev is not None
        self.assertEqual(ev.op, "add")
        self.assertEqual(ev.id, "abcd1234")
        assert ev.qso is not None
        self.assertEqual(ev.qso.call, "W1AW")
        self.assertEqual(ev.qso.band, "6m")
        self.assertTrue(ev.qso.is_mult)

    def test_parse_live_contactreplace(self):
        src = N1mmLogSource()
        xml = (
            "<contactreplace><app>N1MM</app><ID>abcd1234</ID><call>W1AW</call>"
            "<band>144</band><gridsquare>FN32</gridsquare><points>1</points>"
            "</contactreplace>"
        )
        ev = src.parse_live(xml)
        self.assertIsNotNone(ev)
        assert ev is not None
        self.assertEqual(ev.op, "replace")
        assert ev.qso is not None
        self.assertEqual(ev.qso.band, "2m")
        self.assertEqual(ev.qso.grid, "FN32")

    def test_parse_live_contactdelete(self):
        src = N1mmLogSource()
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<contactdelete><app>N1MM</app><call>W1AW</call>"
            "<band>50</band><ID>deadbeefcafe</ID></contactdelete>"
        )
        ev = src.parse_live(xml)
        self.assertIsNotNone(ev)
        assert ev is not None
        self.assertEqual(ev.op, "delete")
        self.assertEqual(ev.id, "deadbeefcafe")
        self.assertIsNone(ev.qso)

    def test_parse_live_ignores_radioinfo(self):
        src = N1mmLogSource()
        ev = src.parse_live(
            "<RadioInfo><app>N1MM</app><StationName>W10VM-50</StationName></RadioInfo>"
        )
        self.assertIsNone(ev)

    def test_live_event_updates_logstore(self):
        src = N1mmLogSource()
        store = LogStore(":memory:")
        add = src.parse_live(
            "<contactinfo><ID>q1</ID><call>K1ABC</call><band>50</band>"
            "<gridsquare>FN42</gridsquare><points>1</points></contactinfo>"
        )
        self.assertIsInstance(add, LogEvent)
        assert add is not None and add.qso is not None
        store.upsert(add.qso)
        self.assertTrue(store.is_dupe("K1ABC", "6m", "FN42"))
        delete = src.parse_live(
            "<contactdelete><ID>q1</ID><call>K1ABC</call><band>50</band>"
            "</contactdelete>"
        )
        assert delete is not None and delete.id
        store.delete(delete.id)
        self.assertFalse(store.is_dupe("K1ABC", "6m", "FN42"))

    def test_seed_missing_db_raises(self):
        src = N1mmLogSource(db_path="/no/such/n1mm.s3db")
        with self.assertRaises(FileNotFoundError):
            src.seed()

    def test_resync_missing_db_soft(self):
        src = N1mmLogSource(db_path="/no/such/n1mm.s3db")
        self.assertEqual(src.resync(), [])
        self.assertEqual(src.status().get("error"), "db_not_found")

    def test_seed_no_path_raises(self):
        src = N1mmLogSource()
        with self.assertRaises(ValueError):
            src.seed()

    def test_status_shape(self):
        src = N1mmLogSource(db_path="/tmp/x.s3db", contest_nr=3)
        st = src.status()
        self.assertEqual(st["kind"], "n1mm")
        self.assertEqual(st["contest_nr"], 3)
        self.assertIn("error", st)


if __name__ == "__main__":
    unittest.main()
