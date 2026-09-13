# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.log.pfx import lookup_pfx  # noqa: E402


class PfxLookupTests(unittest.TestCase):
    def test_us_w1(self):
        pfx, cqz, ituz = lookup_pfx("K1ABC")
        self.assertEqual(pfx, "K")
        self.assertEqual(cqz, 5)
        self.assertEqual(ituz, 8)

    def test_us_w6(self):
        pfx, cqz, ituz = lookup_pfx("W6ABC")
        self.assertEqual(pfx, "K")
        self.assertEqual(cqz, 3)

    def test_portable(self):
        pfx, _, _ = lookup_pfx("K1ABC/P")
        self.assertEqual(pfx, "K")

    def test_ve3(self):
        pfx, cqz, _ = lookup_pfx("VE3XYZ")
        self.assertEqual(pfx, "VE")
        self.assertEqual(cqz, 4)

    def test_kh6(self):
        pfx, cqz, _ = lookup_pfx("KH6FOO")
        self.assertEqual(pfx, "KH6")
        self.assertEqual(cqz, 31)


if __name__ == "__main__":
    unittest.main()
