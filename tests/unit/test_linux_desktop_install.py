# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Linux double-click installer: desktop file, dialogs, tarball mode."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DESKTOP = ROOT / "scripts" / "Add WIMS to Desktop.desktop"
INSTALLER = ROOT / "scripts" / "add-wims-to-desktop.sh"


def _user_facing(text: str) -> str:
    import re

    parts = re.split(r"(?m)^#{2,3} Developer\s*$", text, maxsplit=1)
    return parts[0]


class DesktopFileTests(unittest.TestCase):
    def test_installer_file_is_named_and_executable(self):
        text = DESKTOP.read_text(encoding="utf-8")
        self.assertTrue(DESKTOP.name.startswith("Add WIMS"))
        self.assertIn("Name=Add WIMS to Desktop\n", text)
        self.assertIn("add-wims-to-desktop.sh", text)
        self.assertIn("/bin/bash", text)
        self.assertIn("file://", text)
        self.assertNotIn("python", text.lower())
        self.assertTrue(os.access(DESKTOP, os.X_OK))
        self.assertTrue(os.access(INSTALLER, os.X_OK))
        listed = subprocess.run(
            ["git", "ls-files", "-s", "--", "scripts/Add WIMS to Desktop.desktop"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.stdout.strip():
            self.assertTrue(
                listed.stdout.startswith("100755"),
                listed.stdout,
            )

    def test_glib_launches_the_sibling_script_without_exec_bit(self):
        try:
            from gi.repository import Gio
        except ImportError:
            return
        with tempfile.TemporaryDirectory(prefix="wims launch ") as td:
            folder = Path(td)
            marker = folder / "marker"
            stub = folder / "add-wims-to-desktop.sh"
            stub.write_text(
                "#!/bin/bash\n"
                f'printf "ok\\n" > "{marker}"\n',
                encoding="utf-8",
            )
            stub.chmod(0o644)
            desk = folder / DESKTOP.name
            desk.write_text(DESKTOP.read_text(encoding="utf-8"), encoding="utf-8")
            desk.chmod(0o755)
            info = Gio.DesktopAppInfo.new_from_filename(str(desk))
            self.assertIsNotNone(info)
            self.assertTrue(info.launch([], None))
            self.assertTrue(_wait_for(marker), "desktop Exec did not run the sibling script")
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "ok")

    def test_generated_exec_runs_a_script_whose_name_has_spaces(self):
        from wims.launcher.app import freedesktop_exec

        with tempfile.TemporaryDirectory(prefix="wims check ") as td:
            folder = Path(td)
            marker = folder / "marker"
            script = folder / "Check logs.sh"
            script.write_text(
                "#!/bin/bash\n"
                f'printf "ok\\n" > "{marker}"\n',
                encoding="utf-8",
            )
            script.chmod(0o644)
            exec_line = freedesktop_exec(["/bin/bash", str(script)])
            self.assertIn("/bin/bash", exec_line)
            self.assertIn("Check logs.sh", exec_line)
            desk = folder / "Check logs.desktop"
            desk.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Check logs\n"
                f"Exec={exec_line}\n"
                "Terminal=false\n",
                encoding="utf-8",
            )
            desk.chmod(0o755)
            try:
                from gi.repository import Gio
            except ImportError:
                self.assertIn('"', exec_line)
                return
            info = Gio.DesktopAppInfo.new_from_filename(str(desk))
            self.assertIsNotNone(info)
            self.assertTrue(info.launch([], None))
            self.assertTrue(_wait_for(marker))
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "ok")


class InstallerScriptTests(unittest.TestCase):
    def test_missing_python_uses_a_dialog_and_names_the_package(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seen = tmp / "zenity.txt"
            bindir = _bindir(tmp, ["chmod", "dirname"])
            zenity = bindir / "zenity"
            zenity.write_text(
                "#!/bin/sh\n"
                f'printf "%s\\n" "$@" > "{seen}"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            zenity.chmod(0o755)
            env = _quiet_env(tmp)
            env["PATH"] = str(bindir)
            env["DISPLAY"] = ":99"
            proc = subprocess.run(
                ["/bin/bash", str(INSTALLER)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(proc.returncode, 0)
            shown = seen.read_text(encoding="utf-8")
        self.assertIn("Python was not found", shown)
        self.assertIn("python3", shown)
        self.assertIn("python3-tk", shown)
        self.assertIn("Add WIMS to Desktop", shown)
        self.assertNotIn("python -m", shown)
        self.assertNotIn("PYTHONPATH", shown)

    def test_missing_window_library_names_the_package(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            (home / "Desktop").mkdir(parents=True)
            bindir = _bindir(tmp, ["chmod", "dirname"])
            _write_fake_python(bindir, tk=False)
            env = _quiet_env(home)
            env["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
            env["WIMS_REAL_PYTHON"] = sys.executable
            proc = subprocess.run(
                ["/bin/bash", str(INSTALLER)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("python3-tk", proc.stdout)
            self.assertIn("python3-tkinter", proc.stdout)
            self.assertIn("Add WIMS to Desktop", proc.stdout)
            self.assertFalse((home / "Desktop" / "WIMS.desktop").exists())

    def test_install_repairs_exec_bits_and_writes_trusted_icons(self):
        targets = [INSTALLER, ROOT / "scripts" / "start-wims.sh", DESKTOP]
        saved = {path: path.stat().st_mode for path in targets}
        try:
            for path in targets:
                path.chmod(saved[path] & ~0o111)
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                (home / "Desktop").mkdir(parents=True)
                gio_log = tmp / "gio.txt"
                bindir = _bindir(tmp, ["gio", "update-desktop-database"])
                # Replace the real tools with recorders so the test does not
                # touch this machine's desktop database.
                for name, body in (
                    ("gio", f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{gio_log}"\n'),
                    ("update-desktop-database", "#!/bin/sh\nexit 0\n"),
                ):
                    tool = bindir / name
                    if tool.is_symlink() or tool.exists():
                        tool.unlink()
                    tool.write_text(body, encoding="utf-8")
                    tool.chmod(0o755)
                # The same interpreter that is running this test, so a runner
                # whose `python3` is a different build still matches.
                for name in ("python3", "python"):
                    link = bindir / name
                    if link.exists() or link.is_symlink():
                        link.unlink()
                    os.symlink(sys.executable, link)
                env = _quiet_env(home)
                env["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
                proc = subprocess.run(
                    ["/bin/bash", str(INSTALLER)],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("Double-click WIMS", proc.stdout)
                self.assertNotIn("python3-tk", proc.stdout)
                for path in targets:
                    self.assertTrue(os.access(path, os.X_OK), path)
                desk = home / "Desktop" / "WIMS.desktop"
                menu = home / ".local" / "share" / "applications" / "WIMS.desktop"
                logs = home / "Desktop" / "Check logs.desktop"
                self.assertTrue(desk.is_file())
                self.assertTrue(menu.is_file())
                self.assertTrue(logs.is_file())
                self.assertTrue(os.access(desk, os.X_OK))
                text = desk.read_text(encoding="utf-8")
                self.assertIn("Name=WIMS\n", text)
                self.assertIn("/bin/bash", text)
                self.assertIn("start-wims.sh", text)
                gio = gio_log.read_text(encoding="utf-8")
                self.assertIn("metadata::trusted", gio)
                self.assertIn("true", gio)
                self.assertIn("WIMS.desktop", gio)
        finally:
            for path, mode in saved.items():
                path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class PackageExecBitTests(unittest.TestCase):
    def test_zip_from_unix_keeps_the_bit_and_python_zip_drops_it(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            archive = tmp / "src.zip"
            subprocess.run(
                ["zip", "-q", str(archive), "scripts/Add WIMS to Desktop.desktop"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            unzip_dir = tmp / "unzipped"
            unzip_dir.mkdir()
            subprocess.run(
                ["unzip", "-q", str(archive), "-d", str(unzip_dir)],
                check=True,
                capture_output=True,
            )
            restored = unzip_dir / "scripts" / "Add WIMS to Desktop.desktop"
            self.assertTrue(os.access(restored, os.X_OK))

            py_dir = tmp / "pyzip"
            py_dir.mkdir()
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(py_dir)
            dropped = py_dir / "scripts" / "Add WIMS to Desktop.desktop"
            self.assertTrue(dropped.is_file())
            self.assertFalse(os.access(dropped, os.X_OK))

    def test_release_tarball_keeps_the_installer_executable(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dist"
            env = os.environ.copy()
            env["OUT_DIR"] = str(out)
            env["SKIP_WINDOWS"] = "1"
            proc = subprocess.run(
                ["bash", str(ROOT / "tools" / "dev" / "package-release.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            tarballs = list(out.glob("wims-*-linux-x86_64.tar.gz"))
            self.assertEqual(len(tarballs), 1, proc.stdout)
            with tarfile.open(tarballs[0]) as tf:
                members = {m.name: m for m in tf.getmembers()}
                desktop = _member(members, "scripts/Add WIMS to Desktop.desktop")
                starter = _member(members, "scripts/start-wims.sh")
                helper = _member(members, "scripts/_say.sh")
                self.assertTrue(desktop.mode & 0o111)
                self.assertTrue(starter.mode & 0o111)
                self.assertTrue(helper.mode & 0o111)
                note = tf.extractfile(_member(members, "README-INSTALL.txt"))
                self.assertIsNotNone(note)
                readme = note.read().decode()
            self.assertIn("Add WIMS to Desktop", readme)
            self.assertIn("Allow Launching", readme)
            self.assertNotIn("./scripts/add-wims-to-desktop.sh", readme)


class OperatorDocTests(unittest.TestCase):
    def test_linux_steps_are_double_click(self):
        readme = _user_facing((ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Add WIMS to Desktop", readme)
        self.assertIn("Allow Launching", readme)
        self.assertNotIn("./scripts/add-wims-to-desktop.sh", readme)
        self.assertNotIn("./install.sh", readme)
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        linux = install.split("## Developer", 1)[0]
        self.assertIn("Add WIMS to Desktop", linux)
        self.assertNotIn("sudo apt", linux)
        self.assertNotIn("./install.sh", linux)
        quick = (ROOT / "docs" / "tester_quickstart.md").read_text(encoding="utf-8")
        self.assertNotIn("./scripts/add-wims-to-desktop.sh", quick)
        self.assertNotIn("./scripts/start-wims-solo.sh", quick)
        self.assertIn("Add WIMS to Desktop", quick)


def _wait_for(path: Path, seconds: float = 3.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.is_file():
            return True
        time.sleep(0.05)
    return path.is_file()


def _quiet_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    return env


def _bindir(tmp: Path, names: list[str]) -> Path:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    for name in names:
        src = shutil.which(name)
        if not src:
            continue
        dest = bindir / name
        if not dest.exists():
            os.symlink(src, dest)
    return bindir


def _write_fake_python(bindir: Path, *, tk: bool) -> None:
    flag = "0" if tk else "1"
    script = bindir / "python3"
    script.write_text(
        "#!/bin/sh\n"
        "real=${WIMS_REAL_PYTHON:?}\n"
        "prev=\n"
        "code=\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$prev\" = \"-c\" ]; then code=$a; fi\n"
        "  prev=$a\n"
        "done\n"
        "case \"$code\" in\n"
        "  *tkinter*)\n"
        f"    if [ {flag} = 1 ]; then exit 1; fi\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "exec \"$real\" \"$@\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    # Also hide a plain "python" name so the resolver cannot skip the fake.
    python = bindir / "python"
    if not python.exists():
        os.symlink(script, python)


def _member(members: dict, suffix: str):
    hits = [m for name, m in members.items() if name.endswith("/" + suffix)]
    if not hits:
        raise AssertionError(f"missing {suffix}")
    return hits[0]


if __name__ == "__main__":
    unittest.main()
