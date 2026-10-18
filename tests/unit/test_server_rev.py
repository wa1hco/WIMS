# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Site-server revision vs the checkout on disk, and the tools-panel layout."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.app import (  # noqa: E402
    LauncherApp,
    _health_result,
    fetch_site_health,
    site_reachable,
)
from wims.launcher.home_panel import AgentHomePanel  # noqa: E402
from wims.launcher.server_rev import (  # noqa: E402
    RESTART_NEEDED_MARK,
    RESTART_NEEDED_TIP,
    RESTART_PLAIN_TIP,
    UPDATE_STALE_NOTICE,
    server_restart_needed,
    server_rev_label,
    update_install_notice,
)


_DISK = "aaa1111 2026-10-18 12:00:00 +0000"
_SERVER = "bbb2222 2026-10-01 08:00:00 -0400"
_SAME = "aaa1111 2026-10-18 12:00:00 +0000"


class CompareTests(unittest.TestCase):
    def test_same_revision_is_not_stale(self):
        self.assertFalse(server_restart_needed(_DISK, _SAME))
        self.assertFalse(server_restart_needed("aaa1111", _SAME))

    def test_different_revision_is_stale(self):
        self.assertTrue(server_restart_needed(_DISK, _SERVER))
        self.assertTrue(server_restart_needed("aaa1111", "bbb2222"))

    def test_missing_server_rev_is_not_a_warning(self):
        for server in (None, "", "?", "none", "unknown"):
            self.assertFalse(
                server_restart_needed(_DISK, server),
                server,
            )

    def test_unknown_disk_is_not_a_warning(self):
        for disk in (None, "", "?", "unknown"):
            self.assertFalse(server_restart_needed(disk, _SERVER), disk)

    def test_server_down_is_not_a_warning(self):
        self.assertFalse(server_restart_needed(_DISK, None))

    def test_label_sits_next_to_the_launcher_revision(self):
        self.assertEqual(
            server_rev_label("1.0.16", _SERVER),
            f"Server: v1.0.16 ({_SERVER})",
        )

    def test_label_hidden_when_the_server_did_not_report(self):
        self.assertEqual(server_rev_label("1.0.16", None), "")
        self.assertEqual(server_rev_label("1.0.16", ""), "")
        self.assertEqual(server_rev_label("1.0.16", "?"), "")

    def test_label_without_a_version_still_shows_the_revision(self):
        self.assertEqual(server_rev_label("", "abc1234"), "Server: (abc1234)")

    def test_install_notice_only_when_the_local_server_is_stale(self):
        self.assertEqual(
            update_install_notice(
                went_back=False, disk_rev=_DISK, server_rev=_SERVER,
                local_server=True,
            ),
            UPDATE_STALE_NOTICE,
        )
        self.assertEqual(UPDATE_STALE_NOTICE, "Restart server to finish the update")
        self.assertEqual(
            update_install_notice(
                went_back=False, disk_rev=_DISK, server_rev=_SAME,
                local_server=True,
            ),
            "",
        )
        self.assertEqual(
            update_install_notice(
                went_back=True, disk_rev=_DISK, server_rev=_SERVER,
                local_server=True,
            ),
            "",
        )
        self.assertEqual(
            update_install_notice(
                went_back=False, disk_rev=_DISK, server_rev=_SERVER,
                local_server=False,
            ),
            "",
        )
        self.assertEqual(
            update_install_notice(
                went_back=False, disk_rev=_DISK, server_rev=None,
                local_server=True,
            ),
            "",
        )

    def test_mark_and_tip_are_plain_language(self):
        self.assertEqual(RESTART_NEEDED_MARK, "Restart needed")
        self.assertIn("older code", RESTART_NEEDED_TIP)
        self.assertIn("Restart to use the latest", RESTART_NEEDED_TIP)
        self.assertNotIn("python", RESTART_NEEDED_TIP.lower())
        self.assertIn("latest code", RESTART_PLAIN_TIP)


class FreshStampTests(unittest.TestCase):
    def tearDown(self):
        from wims.gitinfo import git_stamp
        git_stamp.cache_clear()

    def test_fresh_stamp_rereads_disk(self):
        from wims.gitinfo import git_stamp, git_stamp_fresh
        calls = {"n": 0}

        def fake(*_args, **_kwargs):
            calls["n"] += 1
            return f"abc{calls['n']} 2026-10-18 00:00:00 +0000\n"

        git_stamp.cache_clear()
        repo = Path("/tmp/wims-rev-test")
        with mock.patch("wims.gitinfo.subprocess.check_output", side_effect=fake):
            first = git_stamp(repo)
            second = git_stamp(repo)
            fresh = git_stamp_fresh(repo)
        self.assertEqual(first, second)
        self.assertEqual(first, "abc1 2026-10-18 00:00:00 +0000")
        self.assertEqual(fresh, "abc2 2026-10-18 00:00:00 +0000")
        self.assertEqual(calls["n"], 2)


class HealthzTests(unittest.TestCase):
    def test_healthz_reports_the_revision_the_server_loaded(self):
        import wims.server.app as server_app
        from wims.gitinfo import git_stamp

        self.assertEqual(server_app.SERVER_REV, git_stamp())
        self.assertTrue(server_app.SERVER_REV)
        original_rev = server_app.SERVER_REV
        original_ver = server_app.SERVER_VERSION
        server_app.SERVER_REV = "abc1234 2026-10-18 12:00:00 +0000"
        server_app.SERVER_VERSION = "9.9.9"
        httpd, thread = _start(server_app.make_handler(object(), 1.0))
        try:
            port = httpd.server_address[1]
            with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
                raw = resp.read()
                data = json.loads(raw.decode("utf-8"))
        finally:
            server_app.SERVER_REV = original_rev
            server_app.SERVER_VERSION = original_ver
            _stop(httpd, thread)

        self.assertTrue(data["ok"])
        self.assertEqual(data["role"], "wims-site-server")
        self.assertEqual(data["kind"], "wims-server")
        self.assertIn("hostname", data)
        self.assertIn("console_base", data)
        self.assertIn("http_port", data)
        self.assertEqual(
            set(data["urls"]),
            {
                "operate", "status", "overview", "wsjt", "n1mm",
                "log", "setup", "healthz",
            },
        )
        self.assertEqual(data["server_rev"], "abc1234 2026-10-18 12:00:00 +0000")
        self.assertEqual(data["version"], "9.9.9")
        # The field is the recorded value, and the body is still one JSON object.
        self.assertGreater(len(raw), 100)

    def test_launcher_reads_a_health_body_past_the_old_500_byte_cap(self):
        pad = "x" * 800

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path.split("?", 1)[0] != "/healthz":
                    self.send_response(404)
                    self.end_headers()
                    return
                host = self.headers.get("Host")
                body = json.dumps({
                    "ok": True,
                    "role": "wims-site-server",
                    "console_base": f"http://{host}",
                    "server_rev": _SERVER,
                    "version": "1.2.3",
                    "pad": pad,
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd, thread = _start(Handler)
        try:
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"
            # Prove the payload is past the old cap before the launcher reads it.
            with urlopen(base + "/healthz", timeout=2) as resp:
                raw = resp.read()
            self.assertGreater(len(raw), 500)
            data = fetch_site_health(base, timeout=2)
            ok, used = site_reachable(base, timeout=2)
        finally:
            _stop(httpd, thread)

        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["server_rev"], _SERVER)
        self.assertTrue(ok)
        self.assertEqual(used, base)
        self.assertTrue(_health_result(data, base)[0])


class RestartMarkTests(unittest.TestCase):
    def test_mark_shows_and_clears(self):
        panel = AgentHomePanel.__new__(AgentHomePanel)
        panel.restart_needed_lbl = _Label()
        panel._restart_tip = _Tip()
        panel._restart_mark_tip = _Tip()
        panel.set_restart_needed(True)
        self.assertEqual(panel.restart_needed_lbl.text, "Restart needed")
        self.assertTrue(panel.restart_needed_lbl.packed)
        self.assertEqual(panel._restart_tip.text, RESTART_NEEDED_TIP)
        self.assertEqual(panel._restart_mark_tip.text, RESTART_NEEDED_TIP)
        panel.set_restart_needed(False)
        self.assertEqual(panel.restart_needed_lbl.text, "")
        self.assertFalse(panel.restart_needed_lbl.packed)
        self.assertEqual(panel._restart_tip.text, RESTART_PLAIN_TIP)
        self.assertEqual(panel._restart_mark_tip.text, "")


class ToolsPanelTests(unittest.TestCase):
    def test_open_packs_below_the_checkbox_and_does_not_resize(self):
        app = _layout_app(advanced=True)
        LauncherApp._toggle_advanced(app)
        self.assertIsNotNone(app._adv_frame.kwargs)
        self.assertNotIn("before", app._adv_frame.kwargs)
        self.assertEqual(app.fit_calls, 0)
        self.assertEqual(app._auto_fit_left, 0)
        self.assertFalse(app._adv_frame.forgotten)

    def test_close_hides_the_panel_and_fits_the_compact_size(self):
        app = _layout_app(advanced=False)
        LauncherApp._toggle_advanced(app)
        self.assertTrue(app._adv_frame.forgotten)
        self.assertEqual(app.canvas.pos, 0)
        self.assertEqual(app.fit_calls, 1)
        self.assertEqual(app.fit_left_seen, 4)

    def test_fit_does_not_resize_while_tools_are_open(self):
        app = _geometry_app(advanced=True)
        app._auto_fit_left = 4
        LauncherApp._fit_default_geometry(app, 3)
        self.assertIsNone(app.root.spec)
        self.assertEqual(app._auto_fit_left, 4)

    def test_fit_sets_the_compact_height_when_tools_are_closed(self):
        app = _geometry_app(advanced=False)
        app._auto_fit_left = 4
        LauncherApp._fit_default_geometry(app)
        self.assertEqual(app.root.spec, "604x408")
        self.assertEqual(app._auto_fit_left, 3)

    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
    def test_real_window_keeps_the_checkbox_and_shrinks(self):
        """Checkbox stays put; tools open below it; closing snaps the height back."""
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"tkinter is not available ({exc})")
        root = tk.Tk()
        try:
            inner = tk.Frame(root)
            inner.pack(fill="both", expand=True)
            spacer = tk.Frame(inner, height=200, width=400)
            spacer.pack(fill="x")
            spacer.pack_propagate(False)
            btn = tk.Button(inner, text="Open site console")
            btn.pack(fill="x")
            tools = tk.Frame(inner)
            tools.pack(fill="x")
            tk.Checkbutton(tools, text="Other tools…").pack(side="left")
            adv = tk.Frame(inner)
            tk.Label(adv, text="Screenshots and the details log\n" * 12).pack()
            root.geometry("700x900")
            root.update_idletasks()
            checkbox_y = tools.winfo_y()
            app = LauncherApp.__new__(LauncherApp)
            app.root = root
            app._inner = inner
            app._home_panel = type("P", (), {"btn_row": btn})()
            app._adv_frame = adv
            app._tools = tools
            app._canvas = tk.Canvas(root)
            app._auto_fit_left = 0
            app._on_inner_configure = lambda *_a, **_k: None
            app._show_advanced = _Flag(True)
            LauncherApp._toggle_advanced(app)
            root.update_idletasks()
            slaves = inner.pack_slaves()
            self.assertLess(slaves.index(tools), slaves.index(adv))
            self.assertGreater(adv.winfo_y(), tools.winfo_y())
            self.assertEqual(tools.winfo_y(), checkbox_y)
            self.assertGreaterEqual(root.winfo_height(), 800)
            app._show_advanced = _Flag(False)
            LauncherApp._toggle_advanced(app)
            root.update_idletasks()
            self.assertNotIn(adv, inner.pack_slaves())
            self.assertLess(root.winfo_height(), 700)
        finally:
            root.destroy()


class _Label:
    def __init__(self) -> None:
        self.text = ""
        self.packed = False

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def winfo_manager(self) -> str:
        return "pack" if self.packed else ""

    def pack(self, **_kwargs) -> None:
        self.packed = True

    def pack_forget(self) -> None:
        self.packed = False


class _Tip:
    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class _Frame:
    def __init__(self) -> None:
        self.kwargs = None
        self.forgotten = False

    def pack(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.forgotten = False

    def pack_forget(self) -> None:
        self.forgotten = True


class _Flag:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


class _Canvas:
    def __init__(self) -> None:
        self.pos = None

    def yview_moveto(self, pos) -> None:
        self.pos = pos


class _IdleRoot:
    def __init__(self) -> None:
        self.idle = []

    def after_idle(self, fn) -> None:
        self.idle.append(fn)


def _layout_app(*, advanced: bool):
    app = LauncherApp.__new__(LauncherApp)
    app._show_advanced = _Flag(advanced)
    app._adv_frame = _Frame()
    app._tools = object()
    app.canvas = _Canvas()
    app._canvas = app.canvas
    app.root = _IdleRoot()
    app._auto_fit_left = 0
    app.fit_calls = 0
    app.fit_left_seen = None

    def _fit(_tries: int = 0) -> None:
        app.fit_calls += 1
        app.fit_left_seen = app._auto_fit_left

    app._fit_default_geometry = _fit
    return app


class _Btn:
    master = None

    def winfo_exists(self) -> bool:
        return True

    def winfo_height(self) -> int:
        return 40

    def winfo_reqheight(self) -> int:
        return 40

    def winfo_y(self) -> int:
        return 300


class _Inner:
    def winfo_reqheight(self) -> int:
        return 400

    def winfo_reqwidth(self) -> int:
        return 580


class _GeoRoot:
    def __init__(self) -> None:
        self.spec = None
        self.mins = None

    def update_idletasks(self) -> None:
        return None

    def winfo_screenheight(self) -> int:
        return 1200

    def winfo_screenwidth(self) -> int:
        return 1600

    def geometry(self, spec=None):
        if spec is None:
            return "800x900"
        self.spec = spec
        return None

    def minsize(self, w, h) -> None:
        self.mins = (w, h)

    def after_idle(self, fn) -> None:
        return None

    def after(self, _ms, _fn) -> None:
        raise AssertionError("fit scheduled another pass")


def _geometry_app(*, advanced: bool):
    app = LauncherApp.__new__(LauncherApp)
    inner = _Inner()
    btn = _Btn()
    btn.master = inner
    app._inner = inner
    app._home_panel = type("P", (), {"btn_row": btn})()
    app.root = _GeoRoot()
    app._show_advanced = _Flag(advanced)
    app._auto_fit_left = 0
    app._on_inner_configure = lambda *_a, **_k: None
    return app


def _start(handler_cls):
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
