# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Second start asks the running launcher to show its window.

The socket handoff and the Tk call sequence run without a display.
A real window is checked when Xvfb and the window library are both present.
"""

from __future__ import annotations

import builtins
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeRoot:
    """Records the raise sequence. No display."""

    def __init__(self) -> None:
        self.calls: list = []
        self._after: list = []

    def deiconify(self) -> None:
        self.calls.append("deiconify")

    def lift(self) -> None:
        self.calls.append("lift")

    def focus_force(self) -> None:
        self.calls.append("focus_force")

    def attributes(self, name, value=None):
        self.calls.append(("attributes", name, value))
        return 0

    def after(self, ms, fn):
        self.calls.append(("after", ms))
        self._after.append(fn)
        return "after-id"

    def update_idletasks(self) -> None:
        self.calls.append("update_idletasks")


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        from wims.launcher import singleton as sing
        from wims.launcher.handoff import stop_raise_server

        self._td = tempfile.TemporaryDirectory()
        lock = Path(self._td.name) / "launcher.lock"
        self._env = mock.patch.dict(os.environ, {"WIMS_LAUNCHER_LOCK": str(lock)})
        self._env.start()
        if sing._lock_fp is not None:
            sing.release_launcher_lock()
        stop_raise_server()

    def tearDown(self) -> None:
        from wims.launcher import singleton as sing
        from wims.launcher.handoff import stop_raise_server

        stop_raise_server()
        if sing._lock_fp is not None:
            sing.release_launcher_lock()
        self._env.stop()
        self._td.cleanup()

    def test_present_unminimizes_raises_focuses_and_toggles_topmost(self) -> None:
        from wims.launcher.handoff import present_launcher_window

        root = FakeRoot()
        present_launcher_window(root, topmost_ms=200)
        self.assertEqual(
            root.calls[:5],
            [
                "deiconify",
                "lift",
                "focus_force",
                ("attributes", "-topmost", True),
                "update_idletasks",
            ],
        )
        self.assertIn(("after", 200), root.calls)
        root._after[0]()
        self.assertEqual(
            root.calls[-3:],
            [("attributes", "-topmost", False), "lift", "focus_force"],
        )

    def test_second_process_is_acked_when_the_owner_shows_the_window(self) -> None:
        from wims.launcher.handoff import (
            request_running_launcher,
            service_raise_requests,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        root = FakeRoot()
        result: dict[str, bool] = {}

        def client() -> None:
            result["ok"] = request_running_launcher(timeout=2)

        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(_wait_pending(1))
        self.assertEqual(service_raise_requests(root), 1)
        _wait_result(result)
        self.assertTrue(result["ok"])
        self.assertEqual(root.calls.count("deiconify"), 1)
        self.assertIn("lift", root.calls)
        self.assertIn("focus_force", root.calls)
        self.assertIn(("attributes", "-topmost", True), root.calls)

    def test_two_requests_share_one_raise(self) -> None:
        from wims.launcher.handoff import (
            request_running_launcher,
            service_raise_requests,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        root = FakeRoot()
        results: list[bool] = []

        def client() -> None:
            results.append(request_running_launcher(timeout=2))

        threading.Thread(target=client, daemon=True).start()
        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(_wait_pending(2))
        self.assertEqual(service_raise_requests(root), 2)
        deadline = time.monotonic() + 2
        while len(results) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(results, [True, True])
        self.assertEqual(root.calls.count("deiconify"), 1)

    def test_no_listener_returns_without_waiting_the_full_handshake(self) -> None:
        from wims.launcher.handoff import request_running_launcher

        started = time.monotonic()
        self.assertFalse(request_running_launcher(timeout=2))
        self.assertLess(time.monotonic() - started, 1.5)

    def test_stale_port_does_not_count_as_shown(self) -> None:
        from wims.launcher.handoff import (
            raise_endpoint_path,
            request_running_launcher,
        )

        path = raise_endpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # A port that was open and is now closed: same as a dead launcher.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
        probe.close()
        path.write_text(f"{closed} abcdef\n", encoding="ascii")
        self.assertFalse(request_running_launcher(timeout=0.4))

    def test_hung_listener_is_not_a_quiet_success(self) -> None:
        from wims.launcher.handoff import (
            request_running_launcher,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        started = time.monotonic()
        self.assertFalse(request_running_launcher(timeout=0.4))
        self.assertLess(time.monotonic() - started, 1.5)

    def test_wrong_command_does_not_raise(self) -> None:
        from wims.launcher.handoff import (
            raise_server_address,
            service_raise_requests,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        addr = raise_server_address()
        self.assertIsNotNone(addr)
        assert addr is not None
        self.assertEqual(addr[0], "127.0.0.1")
        with socket.create_connection(addr, timeout=1) as conn:
            conn.settimeout(0.4)
            conn.sendall(b"nope\n")
            try:
                data = conn.recv(32)
            except socket.timeout:
                data = b""
        self.assertNotEqual(data.strip(), b"ok")
        root = FakeRoot()
        self.assertEqual(service_raise_requests(root), 0)
        self.assertNotIn("deiconify", root.calls)

    def test_listener_is_localhost_only_and_file_sits_beside_the_lock(self) -> None:
        from wims.launcher.handoff import (
            raise_endpoint_path,
            raise_server_address,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        addr = raise_server_address()
        self.assertIsNotNone(addr)
        assert addr is not None
        self.assertEqual(addr[0], "127.0.0.1")
        path = raise_endpoint_path()
        self.assertEqual(path.name, "launcher.raise")
        self.assertTrue(path.is_file())
        port_text, _token = path.read_text(encoding="ascii").split()
        self.assertEqual(int(port_text), addr[1])
        lock = Path(os.environ["WIMS_LAUNCHER_LOCK"])
        self.assertEqual(path.parent, lock.parent)
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_release_stops_the_listener(self) -> None:
        from wims.launcher.handoff import raise_endpoint_path, request_running_launcher, start_raise_server
        from wims.launcher.singleton import release_launcher_lock, try_acquire_launcher_lock

        self.assertTrue(try_acquire_launcher_lock())
        self.assertTrue(start_raise_server())
        self.assertTrue(raise_endpoint_path().is_file())
        release_launcher_lock()
        self.assertFalse(raise_endpoint_path().is_file())
        self.assertFalse(request_running_launcher(timeout=0.3))

    def test_stop_does_not_pretend_the_window_was_shown(self) -> None:
        from wims.launcher.handoff import (
            request_running_launcher,
            start_raise_server,
            stop_raise_server,
        )

        self.assertTrue(start_raise_server())
        result: dict[str, bool] = {}

        def client() -> None:
            result["ok"] = request_running_launcher(timeout=1.5)

        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(_wait_pending(1))
        stop_raise_server()
        _wait_result(result)
        self.assertFalse(result["ok"])

    def test_owner_listens_before_the_window_library(self) -> None:
        from wims.launcher.app import main

        order: list[str] = []
        real_import = builtins.__import__

        def start() -> bool:
            order.append("listen")
            return True

        def block_tk(name, *args, **kwargs):
            if name == "tkinter":
                order.append("tk")
                raise ImportError("no window library in this test")
            return real_import(name, *args, **kwargs)

        err = io.StringIO()
        with mock.patch(
            "wims.launcher.singleton.try_acquire_launcher_lock", return_value=True,
        ), mock.patch(
            "wims.launcher.handoff.start_raise_server", side_effect=start,
        ), mock.patch(
            "builtins.__import__", side_effect=block_tk,
        ), mock.patch("sys.stderr", err):
            rc = main([])
        self.assertEqual(rc, 2)
        self.assertEqual(order[:2], ["listen", "tk"])
        self.assertIn("window library", err.getvalue())

    def test_window_poll_services_a_request_and_reschedules(self) -> None:
        from wims.launcher.app import LauncherApp
        from wims.launcher.handoff import (
            RAISE_POLL_MS,
            request_running_launcher,
            start_raise_server,
        )

        self.assertTrue(start_raise_server())
        root = FakeRoot()
        app = mock.Mock()
        app.root = root
        result: dict[str, bool] = {}

        def client() -> None:
            result["ok"] = request_running_launcher(timeout=2)

        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(_wait_pending(1))
        LauncherApp._poll_raise_request(app)
        _wait_result(result)
        self.assertTrue(result["ok"])
        self.assertIn("deiconify", root.calls)
        self.assertIn(("after", RAISE_POLL_MS), root.calls)

    def test_second_process_main_exits_quietly(self) -> None:
        from wims.launcher.handoff import service_raise_requests, start_raise_server
        from wims.launcher.singleton import try_acquire_launcher_lock

        self.assertTrue(try_acquire_launcher_lock())
        self.assertTrue(start_raise_server())
        root = FakeRoot()
        stop = threading.Event()

        def pump() -> None:
            while not stop.is_set():
                service_raise_requests(root)
                time.sleep(0.02)

        threading.Thread(target=pump, daemon=True).start()
        try:
            proc = _run_launcher(timeout=15)
        finally:
            stop.set()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")
        self.assertIn("deiconify", root.calls)
        self.assertIn(("attributes", "-topmost", True), root.calls)
        self.assertNotIn("http://", proc.stdout + proc.stderr)

    def test_second_process_main_explains_when_nobody_answers(self) -> None:
        from wims.launcher.singleton import try_acquire_launcher_lock

        self.assertTrue(try_acquire_launcher_lock())
        started = time.monotonic()
        proc = _run_launcher(timeout=15, display=False)
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertIn("did not come forward", proc.stdout)
        self.assertIn("double-click", proc.stdout)
        self.assertNotIn("http://", proc.stdout + proc.stderr)
        self.assertLess(elapsed, 5.0)


class RaiseWindowDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        from wims.launcher import singleton as sing
        from wims.launcher.handoff import stop_raise_server

        self._td = tempfile.TemporaryDirectory()
        lock = Path(self._td.name) / "launcher.lock"
        self._env = mock.patch.dict(os.environ, {"WIMS_LAUNCHER_LOCK": str(lock)})
        self._env.start()
        if sing._lock_fp is not None:
            sing.release_launcher_lock()
        stop_raise_server()

    def tearDown(self) -> None:
        from wims.launcher import singleton as sing
        from wims.launcher.handoff import stop_raise_server

        stop_raise_server()
        if sing._lock_fp is not None:
            sing.release_launcher_lock()
        self._env.stop()
        self._td.cleanup()

    def test_second_start_raises_a_real_window(self) -> None:
        if shutil.which("Xvfb") is None:
            self.skipTest("Xvfb is not installed")
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("window library is not installed")

        from wims.launcher.handoff import (
            request_running_launcher,
            service_raise_requests,
            start_raise_server,
        )

        display = f":{220 + (os.getpid() % 60)}"
        xvfb = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1024x768x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        old_display = os.environ.get("DISPLAY")
        os.environ["DISPLAY"] = display
        root = None
        try:
            if not _wait_xvfb(display, xvfb):
                self.skipTest("display did not open")
            try:
                root = tk.Tk()
            except Exception:
                self.skipTest("display did not open")
            root.withdraw()
            root.update()
            hidden = root.state()
            if hidden != "withdrawn":
                root.iconify()
                root.update()
                hidden = root.state()
            self.assertIn(hidden, ("withdrawn", "iconic"))
            # Xvfb has no window manager, so -topmost is accepted and then
            # reads back as off. Record the calls on the real Tk object.
            attr_calls: list[tuple] = []
            real_attributes = root.attributes

            def _record_attributes(name, value=None):
                attr_calls.append((name, value))
                if value is None:
                    return real_attributes(name)
                return real_attributes(name, value)

            root.attributes = _record_attributes
            self.assertTrue(start_raise_server())
            result: dict[str, bool] = {}

            def client() -> None:
                result["ok"] = request_running_launcher(timeout=3)

            threading.Thread(target=client, daemon=True).start()

            def poll() -> None:
                service_raise_requests(root)
                if "ok" in result:
                    root.quit()
                    return
                root.after(30, poll)

            root.after(30, poll)
            root.after(4000, root.quit)
            root.mainloop()
            self.assertTrue(result.get("ok"))
            self.assertEqual(root.state(), "normal")
            self.assertIn(("-topmost", True), attr_calls)
            time.sleep(0.25)
            root.update()
            self.assertIn(("-topmost", False), attr_calls)
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
            if old_display is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = old_display
            xvfb.terminate()
            try:
                xvfb.wait(timeout=2)
            except subprocess.TimeoutExpired:
                xvfb.kill()


def _wait_pending(n: int, timeout: float = 2.0) -> bool:
    from wims.launcher.handoff import pending_raise_count

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pending_raise_count() >= n:
            return True
        time.sleep(0.01)
    return False


def _wait_result(result: dict, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while "ok" not in result and time.monotonic() < deadline:
        time.sleep(0.02)


def _run_launcher(*, timeout: float, display: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["WIMS_SKIP_UPDATE_CHECK"] = "1"
    env["WIMS_LAUNCHER_LOCK"] = os.environ["WIMS_LAUNCHER_LOCK"]
    if not display:
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
    return subprocess.run(
        [sys.executable, "-m", "wims.launcher"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _wait_xvfb(display: str, proc: subprocess.Popen) -> bool:
    number = display.lstrip(":")
    sock = Path("/tmp/.X11-unix") / f"X{number}"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if sock.exists():
            return True
        time.sleep(0.05)
    return sock.exists()


if __name__ == "__main__":
    unittest.main()
