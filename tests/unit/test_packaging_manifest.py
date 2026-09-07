#!/usr/bin/env python3
# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for scripts/packaging/write_manifest.py (no pytest)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOD_PATH = ROOT / "scripts" / "packaging" / "write_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("write_manifest", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ParseTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_ga(self):
        base, channel, display = self.m.parse_release_tag("v0.1.0")
        self.assertEqual((base, channel, display), ("0.1.0", "GA", "0.1.0"))

    def test_tester(self):
        base, channel, display = self.m.parse_release_tag("0.1.0-tester")
        self.assertEqual((base, channel, display), ("0.1.0", "tester", "0.1.0-tester"))

    def test_rc(self):
        base, channel, display = self.m.parse_release_tag("v0.1.0-rc2")
        self.assertEqual((base, channel, display), ("0.1.0", "RC", "0.1.0-rc2"))

    def test_rejects_dev_suffix(self):
        with self.assertRaises(ValueError):
            self.m.parse_release_tag("0.1.0-dev1")

    def test_rejects_rc0(self):
        with self.assertRaises(ValueError):
            self.m.parse_release_tag("0.1.0-rc0")


class ManifestBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_build_against_repo(self):
        # Live tree version — GA channel for bare X.Y.Z.
        man = self.m.build_manifest(repo_root=ROOT, tag_or_version="1.0.0")
        self.assertEqual(man["version_base"], "1.0.0")
        self.assertEqual(man["version"], "1.0.0")
        self.assertEqual(man["channel"], "GA")
        self.assertEqual(man["name"], "wims")
        self.assertFalse(man["python_bundled"])
        self.assertIn("created_utc", man)
        self.assertIn("git_sha", man)

    def test_mismatch_base_raises(self):
        with self.assertRaises(ValueError):
            self.m.build_manifest(repo_root=ROOT, tag_or_version="9.9.9")


if __name__ == "__main__":
    unittest.main()
