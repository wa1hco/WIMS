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

from wims import __version__  # noqa: E402
from wims.launcher.app import (  # noqa: E402
    LauncherApp,
    _HOME_FIT_PAD,
    _SCREEN_FIT_MARGIN,
    _health_result,
    fetch_site_health,
    site_reachable,
)
from wims.launcher.home_panel import AgentHomePanel  # noqa: E402
from wims.launcher.server_rev import (  # noqa: E402
    LAUNCHER_REV_TIP,
    RESTART_NEEDED_MARK,
    RESTART_NEEDED_TIP,
    RESTART_PLAIN_TIP,
    SERVER_REV_TIP,
    UPDATE_STALE_NOTICE,
    launcher_rev_label,
    restart_server_tip,
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

    def test_launcher_label_names_the_window_copy(self):
        self.assertEqual(
            launcher_rev_label("1.0.16", _DISK),
            f"Launcher: v1.0.16 ({_DISK})",
        )
        self.assertEqual(LAUNCHER_REV_TIP, "Launcher: the code this window loaded when it opened.")
        self.assertEqual(SERVER_REV_TIP, "Server: the code the site server loaded at start.")
        self.assertNotIn("python", LAUNCHER_REV_TIP.lower())
        self.assertNotIn("python", SERVER_REV_TIP.lower())

    def test_restart_tip_says_when_the_server_matches_disk(self):
        tip = restart_server_tip(
            server_version="1.0.16",
            server_rev="abc1234 2026-10-18 12:00:00 +0000",
            disk_rev="abc1234 2026-10-18 12:00:00 +0000",
        )
        self.assertEqual(
            tip,
            "Server running v1.0.16 (abc1234, 2026-10-18). "
            "Installed code: abc1234. Up to date.",
        )

    def test_restart_tip_says_when_a_restart_is_needed(self):
        tip = restart_server_tip(
            server_version="1.0.15",
            server_rev=_SERVER,
            disk_rev=_DISK,
        )
        self.assertIn("Server running v1.0.15 (bbb2222, 2026-10-01).", tip)
        self.assertIn("Installed code: aaa1111.", tip)
        self.assertIn(RESTART_NEEDED_TIP, tip)
        self.assertNotIn("python", tip.lower())

    def test_restart_tip_stays_plain_when_the_server_did_not_report(self):
        tip = restart_server_tip(
            server_version="1.0.16",
            server_rev="",
            disk_rev=_DISK,
        )
        self.assertIn("did not report", tip)
        self.assertIn("Installed code: aaa1111.", tip)
        self.assertIn(RESTART_PLAIN_TIP, tip)

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

    def test_revision_sentence_stays_on_the_button(self):
        panel = AgentHomePanel.__new__(AgentHomePanel)
        panel.restart_needed_lbl = _Label()
        panel._restart_tip = _Tip()
        panel._restart_mark_tip = _Tip()
        panel._restart_detail = ""
        sentence = (
            "Server running v1.0.16 (abc1234, 2026-10-18). "
            "Installed code: abc1234. Up to date."
        )
        panel.set_restart_tip(sentence)
        panel.set_restart_needed(False)
        self.assertEqual(panel._restart_tip.text, sentence)
        panel.set_restart_needed(True)
        self.assertEqual(panel._restart_tip.text, sentence)
        self.assertEqual(panel.restart_needed_lbl.text, "Restart needed")


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class _TitleRoot:
    def __init__(self) -> None:
        self.title_text = ""

    def title(self, text: str) -> None:
        self.title_text = text


class LoadedRevTests(unittest.TestCase):
    def test_title_and_labels_name_each_copy(self):
        app = LauncherApp.__new__(LauncherApp)
        app._rev = _DISK
        app._launcher_rev_var = _Var()
        app._server_rev_var = _Var()
        app._server_rev_lbl = _Label()
        app.root = _TitleRoot()
        tips: list[str] = []

        class _Panel:
            def set_restart_tip(self, text: str) -> None:
                tips.append(text)

        app._home_panel = _Panel()
        LauncherApp._show_loaded_revs(
            app,
            "1.0.16",
            "abc1234 2026-10-18 12:00:00 +0000",
            "abc1234 2026-10-18 12:00:00 +0000",
        )
        self.assertIn("Launcher:", app._launcher_rev_var.get())
        self.assertIn(f"v{__version__}", app._launcher_rev_var.get())
        self.assertIn(_DISK, app._launcher_rev_var.get())
        self.assertIn("Server:", app._server_rev_var.get())
        self.assertIn("v1.0.16", app._server_rev_var.get())
        self.assertTrue(app._server_rev_lbl.packed)
        self.assertIn("Launcher:", app.root.title_text)
        self.assertIn("Server:", app.root.title_text)
        self.assertIn("Up to date.", tips[-1])
        self.assertIn("abc1234", tips[-1])

        LauncherApp._show_loaded_revs(app, "", "", _DISK)
        self.assertEqual(app._server_rev_var.get(), "")
        self.assertFalse(app._server_rev_lbl.packed)
        self.assertNotIn("Server:", app.root.title_text)


class ToolsPanelTests(unittest.TestCase):
    def test_open_packs_below_the_checkbox_and_grows(self):
        app = _layout_app(advanced=True)
        LauncherApp._toggle_advanced(app)
        self.assertIsNotNone(app._adv_frame.kwargs)
        self.assertNotIn("before", app._adv_frame.kwargs)
        self.assertEqual(app.fit_calls, 1)
        self.assertEqual(app._auto_fit_left, 0)
        self.assertFalse(app._adv_frame.forgotten)

    def test_close_hides_the_panel_and_fits_the_compact_size(self):
        app = _layout_app(advanced=False)
        LauncherApp._toggle_advanced(app)
        self.assertTrue(app._adv_frame.forgotten)
        self.assertEqual(app.canvas.pos, 0)
        self.assertEqual(app.fit_calls, 1)
        self.assertEqual(app.fit_left_seen, 4)

    def test_fit_grows_to_the_open_panel_and_stops_at_the_screen(self):
        app = _geometry_app(advanced=True)
        app._auto_fit_left = 4
        LauncherApp._fit_default_geometry(app, 3)
        self.assertEqual(app.root.spec, _spec(app._adv_frame))
        self.assertEqual(app._auto_fit_left, 3)
        app._adv_frame._h = 4000
        app._auto_fit_left = 1
        LauncherApp._fit_default_geometry(app)
        cap = max(280, 1200 - _SCREEN_FIT_MARGIN)
        self.assertEqual(app.root.spec, f"604x{cap}")

    def test_fit_sets_the_compact_height_when_tools_are_closed(self):
        app = _geometry_app(advanced=False)
        app._auto_fit_left = 4
        LauncherApp._fit_default_geometry(app)
        self.assertEqual(app.root.spec, _spec(app._tools))
        self.assertEqual(app._auto_fit_left, 3)

    def test_fit_keeps_a_checkbox_that_still_fits_on_the_screen(self):
        app = _geometry_app(advanced=False)
        app._auto_fit_left = 1
        app._tools._y = 1160
        app._tools._h = 30
        LauncherApp._fit_default_geometry(app)
        # 1194 is under the 1200 screen and past the margin, so it is kept.
        self.assertEqual(app.root.spec, "604x1194")

    def test_fit_follows_a_taller_home(self):
        app = _geometry_app(advanced=False)
        app._auto_fit_left = 2
        LauncherApp._fit_default_geometry(app)
        first = app.root.spec
        app._tools._y += 80
        LauncherApp._fit_default_geometry(app)
        self.assertEqual(app.root.spec, _spec(app._tools))
        self.assertNotEqual(first, app.root.spec)

    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
    def test_real_window_fits_the_checkbox_and_grows_for_tools(self):
        """Closed height ends at Other tools…. Open grows, then scrolls."""
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"tkinter is not available ({exc})")
        root = tk.Tk()
        try:
            app, tools, adv, banner = _real_fit_window(root, tk)
            LauncherApp._fit_default_geometry(app)
            root.update()
            closed = root.winfo_height()
            gap = _window_gap(root, tools)
            self.assertGreaterEqual(gap, 0, gap)
            self.assertLessEqual(gap, 16, gap)
            self.assertFalse(LauncherApp._content_overflows(app))

            app._show_advanced = _Flag(True)
            LauncherApp._toggle_advanced(app)
            root.update()
            self.assertGreater(adv.winfo_y(), tools.winfo_y())
            self.assertGreater(root.winfo_height(), closed)
            open_gap = _window_gap(root, adv)
            self.assertGreaterEqual(open_gap, 0, open_gap)
            self.assertLessEqual(open_gap, 16, open_gap)

            app._show_advanced = _Flag(False)
            LauncherApp._toggle_advanced(app)
            root.update()
            self.assertNotIn(adv, app._inner.pack_slaves())
            self.assertEqual(root.winfo_height(), closed)
            self.assertLessEqual(_window_gap(root, tools), 16)

            banner.configure(
                wraplength=420,
                text="Restart needed. The server is running older code. " * 8,
            )
            root.update_idletasks()
            LauncherApp._fit_default_geometry(app)
            root.update()
            self.assertGreater(root.winfo_height(), closed)
            grown_gap = _window_gap(root, tools)
            self.assertGreaterEqual(grown_gap, 0, grown_gap)
            self.assertLessEqual(grown_gap, 16, grown_gap)

            # Taller than the screen: the window stops, and the panel scrolls.
            tall = tk.Frame(adv, height=root.winfo_screenheight() + 400, width=400)
            tall.pack(fill="x")
            tall.pack_propagate(False)
            app._show_advanced = _Flag(True)
            adv.pack(fill="x", expand=False, pady=(0, 4))
            root.update_idletasks()
            LauncherApp._fit_default_geometry(app)
            root.update()
            cap = max(280, root.winfo_screenheight() - _SCREEN_FIT_MARGIN)
            self.assertLessEqual(root.winfo_height(), cap + 8)
            self.assertGreaterEqual(root.winfo_height(), cap - 8)
            LauncherApp._on_inner_configure(app)
            self.assertGreater(
                app._inner.winfo_reqheight(),
                root.winfo_height(),
            )
            self.assertTrue(LauncherApp._content_overflows(app))
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


class _Box:
    """A packed row with a known y and height inside the inner frame."""

    def __init__(self, y: int, h: int, master) -> None:
        self._y = y
        self._h = h
        self.master = master

    def winfo_exists(self) -> bool:
        return True

    def winfo_height(self) -> int:
        return self._h

    def winfo_reqheight(self) -> int:
        return self._h

    def winfo_y(self) -> int:
        return self._y


def _spec(widget: _Box) -> str:
    bottom = widget.winfo_height() + widget.winfo_y()
    height = bottom + _HOME_FIT_PAD
    cap = max(280, 1200 - _SCREEN_FIT_MARGIN)
    return f"604x{min(height, cap)}"


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
    app._tools = _Box(500, 30, inner)
    app._adv_frame = _Box(540, 300, inner)
    app._home_panel = type("P", (), {"btn_row": btn})()
    app.root = _GeoRoot()
    app._show_advanced = _Flag(advanced)
    app._auto_fit_left = 0
    app._on_inner_configure = lambda *_a, **_k: None
    return app


def _window_gap(root, widget) -> int:
    bottom = (widget.winfo_rooty() - root.winfo_rooty()) + widget.winfo_height()
    return int(root.winfo_height()) - int(bottom)


def _real_fit_window(root, tk):
    """A short stand-in for the home column, on the real fit path."""
    outer = tk.Frame(root, bg="#f4f4f4")
    outer.pack(fill="both", expand=True)
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, bg="#f4f4f4", highlightthickness=0, bd=0)
    vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    vsb.grid_remove()
    inner = tk.Frame(canvas, bg="#f4f4f4")
    canvas.create_window((0, 0), window=inner, anchor="nw")
    banner = tk.Label(inner, text="Checking…", font=("TkDefaultFont", 14, "bold"), anchor="w")
    banner.pack(fill="x", padx=12, pady=4)
    tk.Label(inner, text="Launcher: v1.0.16 (abc1234)", anchor="w").pack(fill="x", padx=12)
    listing = tk.Listbox(inner, height=4)
    listing.pack(fill="x", padx=12, pady=4)
    for name in ("v1.0.16", "v1.0.15", "v1.0.10", "v1.0.0"):
        listing.insert("end", name)
    btn = tk.Button(inner, text="Open site console")
    btn.pack(fill="x", padx=12, pady=4)
    tools = tk.Frame(inner, bg="#f4f4f4")
    tools.pack(fill="x", padx=12, pady=(2, 0))
    tk.Checkbutton(tools, text="Other tools…").pack(side="left")
    adv = tk.Frame(inner, bg="#f4f4f4")
    tk.Label(adv, text="Screenshots, desktop shortcut, and the details log.").pack(
        fill="x", padx=12, pady=4,
    )
    app = LauncherApp.__new__(LauncherApp)
    app.root = root
    app.tk = tk
    app._inner = inner
    app._canvas = canvas
    app._vscroll = vsb
    app._tools = tools
    app._adv_frame = adv
    app._home_panel = type("P", (), {"btn_row": btn})()
    app._show_advanced = _Flag(False)
    app._auto_fit_left = 4
    app._fitted_inner_h = None
    app._content_fit_queued = False
    root.geometry("560x440")
    root.update_idletasks()
    return app, tools, adv, banner


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
