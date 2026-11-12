# WS Hub (formerly WIMS) — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install place, copy/swap, the legacy icon matcher, and tarball updates."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher import install_tree  # noqa: E402
from wims.launcher import update_check  # noqa: E402


def _tree(path: Path, marker: str = "a") -> Path:
    (path / "src" / "wims").mkdir(parents=True)
    (path / "src" / "wims" / "__init__.py").write_text(f'__version__ = "{marker}"\n')
    (path / "scripts").mkdir()
    (path / "scripts" / "start-wims.sh").write_text("#!/bin/bash\n")
    return path


class InstallPlaceTests(unittest.TestCase):
    def test_xdg_data_home_wins(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/x/data"}):
            self.assertEqual(install_tree.install_dir(), Path("/x/data/ws-hub"))

    def test_default_is_local_share(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ, {"XDG_DATA_HOME": ""}
        ), mock.patch.object(Path, "home", return_value=Path(td)):
            self.assertEqual(
                install_tree.install_dir(), Path(td) / ".local" / "share" / "ws-hub",
            )


class CopyTests(unittest.TestCase):
    def test_copy_skips_caches_and_keeps_old_logs(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            src = _tree(tmp / "dl", "new")
            (src / "src" / "wims" / "__pycache__").mkdir()
            (src / "scratch").mkdir()
            (src / "scratch" / "from-download.log").write_text("x")
            dest = _tree(tmp / "data" / "ws-hub", "old")
            (dest / "scratch").mkdir()
            (dest / "scratch" / "launcher-details.log").write_text("keep")
            out = install_tree.install_copy(src, dest)
            self.assertEqual(out, dest)
            self.assertIn("new", (dest / "src" / "wims" / "__init__.py").read_text())
            self.assertFalse((dest / "src" / "wims" / "__pycache__").exists())
            self.assertEqual((dest / "scratch" / "launcher-details.log").read_text(), "keep")
            self.assertFalse((dest / "scratch" / "from-download.log").exists())
            self.assertEqual(
                sorted(p.name for p in dest.parent.iterdir()), ["ws-hub"],
            )

    def test_running_from_the_installed_copy_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            dest = _tree(Path(td) / "ws-hub")
            self.assertEqual(install_tree.install_copy(dest, dest), dest)
            self.assertTrue((dest / "scripts" / "start-wims.sh").is_file())

    def test_refuses_a_folder_that_is_not_the_program(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                install_tree.install_copy(Path(td), Path(td) / "ws-hub")

    def test_git_checkout_is_not_copied(self):
        with tempfile.TemporaryDirectory() as td:
            src = _tree(Path(td) / "clone")
            (src / ".git").mkdir()
            out = io.StringIO()
            with mock.patch("sys.stdout", out), mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": str(Path(td) / "data")}
            ):
                self.assertEqual(install_tree.main([str(src)]), 0)
            self.assertEqual(out.getvalue().strip(), str(src.resolve()))
            self.assertFalse((Path(td) / "data").exists())


class LegacyMatcherTests(unittest.TestCase):
    def test_known_forms_match(self):
        from wims.launcher.app import legacy_entry_starts_wims

        for text in (
            "[Desktop Entry]\nExec=/bin/bash /home/j/ham/wims/scripts/start-wims.sh\n",
            "[Desktop Entry]\nExec=env PYTHONPATH=/home/j/ham/wims/src "
            "/usr/bin/python -m wims.launcher\nPath=/home/j/ham/wims\n",
            "[Desktop Entry]\nExec=something\nPath=/home/j/ham/wims\n",
            "[Desktop Entry]\nExec=x\nPath=/home/j/Downloads/wims-1.0.18-linux-x86_64\n",
        ):
            self.assertTrue(legacy_entry_starts_wims(text), text)

    def test_unrelated_entries_do_not_match(self):
        from wims.launcher.app import legacy_entry_starts_wims

        for text in (
            "[Desktop Entry]\nName=WIMS\nExec=/opt/other/wims-viewer\nPath=/opt/other\n",
            "[Desktop Entry]\nExec=firefox\n",
            "",
        ):
            self.assertFalse(legacy_entry_starts_wims(text), text)


def _release_tarball(folder: Path, version: str) -> tuple[Path, Path]:
    top = f"wims-{version}-linux-x86_64"
    stage = _tree(folder / "stage" / top, version)
    name = f"{top}.tar.gz"
    archive = folder / name
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(stage, arcname=top)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums = folder / "SHA256SUMS"
    sums.write_text(f"{digest}  {name}\n")
    return archive, sums


class TarballUpdateTests(unittest.TestCase):
    def setUp(self):
        if sys.platform.startswith("win"):
            self.skipTest("Linux and macOS replace the folder")

    def _assets(self, archive: Path, sums: Path) -> dict[str, str]:
        return {archive.name: archive.as_uri(), "SHA256SUMS": sums.as_uri()}

    def test_install_replaces_the_copy_and_go_back_restores_it(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = _tree(tmp / "data" / "ws-hub", "1.0.19")
            (root / "scratch").mkdir()
            (root / "scratch" / "launcher-details.log").write_text("keep")
            archive, sums = _release_tarball(tmp / "dl", "1.0.20")
            back = tmp / "back.json"
            with mock.patch.object(
                update_check, "release_assets",
                return_value=(self._assets(archive, sums), ""),
            ):
                ok, msg = update_check.apply_release(root, "v1.0.20", rollback_file=back)
            self.assertTrue(ok, msg)
            self.assertIn("1.0.20", (root / "src" / "wims" / "__init__.py").read_text())
            self.assertEqual((root / "scratch" / "launcher-details.log").read_text(), "keep")
            prev = install_tree.previous_dir(root)
            self.assertIn("1.0.19", (prev / "src" / "wims" / "__init__.py").read_text())
            saved = json.loads(back.read_text())
            self.assertEqual(saved["kind"], "tree")
            ok, msg = update_check.rollback_release(root, rollback_file=back)
            self.assertTrue(ok, msg)
            self.assertIn("1.0.19", (root / "src" / "wims" / "__init__.py").read_text())
            leftovers = [p.name for p in root.parent.iterdir() if p.name.startswith(".ws-hub")]
            self.assertEqual(leftovers, [])

    def test_bad_checksum_leaves_the_copy(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = _tree(tmp / "data" / "ws-hub", "1.0.19")
            archive, sums = _release_tarball(tmp / "dl", "1.0.20")
            sums.write_text(f"{'0' * 64}  {archive.name}\n")
            with mock.patch.object(
                update_check, "release_assets",
                return_value=(self._assets(archive, sums), ""),
            ):
                ok, msg = update_check.apply_release(
                    root, "v1.0.20", rollback_file=tmp / "back.json",
                )
            self.assertFalse(ok)
            self.assertIn("checksum", msg)
            self.assertIn("1.0.19", (root / "src" / "wims" / "__init__.py").read_text())
            self.assertFalse(install_tree.previous_dir(root).exists())

    def test_release_without_a_linux_download(self):
        with tempfile.TemporaryDirectory() as td:
            root = _tree(Path(td) / "ws-hub")
            with mock.patch.object(update_check, "release_assets", return_value=({}, "")):
                ok, msg = update_check.apply_release(
                    root, "v1.0.20", rollback_file=Path(td) / "b.json",
                )
            self.assertFalse(ok)
            self.assertIn("no Linux download", msg)


if __name__ == "__main__":
    unittest.main()
