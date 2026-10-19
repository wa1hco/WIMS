# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Console window geometry, clamping, command line, and local-only reuse."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.console.place import (  # noqa: E402
    Screen,
    attach_console_ctrl,
    build_chromium_command,
    clamp_geometry,
    client_is_local,
    console_is_on_this_pc,
    console_open_message,
    ConsoleHub,
    decide_reuse,
    default_geometry,
    geometry_applies,
    handle_geometry_post,
    handle_ping_post,
    handle_reload_post,
    handle_reset_post,
    load_geometry,
    local_console_is_open,
    parse_xrandr,
    placed_console_url,
    request_console_reload,
    save_geometry,
)


PRIMARY = Screen(0, 0, 1920, 1080)
SECOND = Screen(1920, 0, 1280, 1024)
LEFT = Screen(-1920, 0, 1920, 1080)

XRANDR = """\
Screen 0: minimum 320 x 200, current 3200 x 1080, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right) 309mm x 174mm
DP-1 connected 1280x1024+1920+0 (normal left inverted right) 376mm x 301mm
HDMI-1 disconnected (normal left inverted right)
"""

LISTMONITORS = """\
Monitors: 2
 0: +*eDP-1 1920/309x1080/174+0+0  eDP-1
 1: +DP-2 1920/508x1080/286+-1920+0  DP-2
"""


class GeometryStoreTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wims" / "console_window.json"
            saved = save_geometry(
                {"x": 15, "y": -40, "width": 1000, "height": 700, "extra": "no"},
                path,
            )
            self.assertEqual(saved, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema"], 1)
            self.assertNotIn("extra", raw)
            self.assertEqual(
                load_geometry(path),
                {"x": 15, "y": -40, "width": 1000, "height": 700},
            )

    def test_missing_and_corrupt_load_as_unset(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "nope.json"
            self.assertIsNone(load_geometry(missing))
            bad = Path(td) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_geometry(bad))
            wrong = Path(td) / "wrong.json"
            wrong.write_text(json.dumps({"x": "nope"}), encoding="utf-8")
            self.assertIsNone(load_geometry(wrong))

    def test_remote_report_does_not_overwrite_local_spot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "console_window.json"
            hub = ConsoleHub(boot="b")
            local = handle_geometry_post(
                {"placed": True, "x": 11, "y": 22, "width": 800, "height": 600},
                client_local=True, settings=path, hub=hub, now=1.0,
            )
            self.assertTrue(local["saved"])
            remote = handle_geometry_post(
                {"placed": True, "x": 9000, "y": 9000, "width": 900, "height": 700},
                client_local=False, settings=path, hub=hub, now=2.0,
            )
            self.assertFalse(remote["saved"])
            # A tab on this PC that the launcher did not open.
            other = handle_geometry_post(
                {"placed": False, "x": 1, "y": 2, "width": 500, "height": 400},
                client_local=True, settings=path, hub=hub, now=3.0,
            )
            self.assertFalse(other["saved"])
            self.assertEqual(
                load_geometry(path),
                {"x": 11, "y": 22, "width": 800, "height": 600},
            )
            # The local save pinged at t=1. The remote report at t=2 must
            # not refresh that, so by t=7 the page is no longer "open".
            self.assertTrue(hub.presence(3.0)["local_open"])
            self.assertFalse(hub.presence(7.0)["local_open"])

    def test_who_may_write_the_saved_spot(self):
        self.assertTrue(geometry_applies(client_local=True, placed=True))
        self.assertFalse(geometry_applies(client_local=True, placed=False))
        self.assertFalse(geometry_applies(client_local=False, placed=True))
        self.assertFalse(geometry_applies(client_local=False, placed=False))


class ClampTests(unittest.TestCase):
    def test_window_already_on_a_screen_stays(self):
        geom = {"x": 100, "y": 80, "width": 900, "height": 640}
        self.assertEqual(clamp_geometry(geom, [PRIMARY, SECOND]), geom)

    def test_window_on_the_left_monitor_stays(self):
        geom = {"x": -1800, "y": 40, "width": 800, "height": 600}
        self.assertEqual(clamp_geometry(geom, [LEFT, PRIMARY]), geom)

    def test_off_screen_moves_onto_the_nearest_display(self):
        # Center sits nearer the right-hand display than the primary.
        geom = {"x": 5000, "y": 100, "width": 900, "height": 640}
        placed = clamp_geometry(geom, [PRIMARY, SECOND])
        self.assertEqual(placed["width"], 900)
        self.assertEqual(placed["height"], 640)
        self.assertGreaterEqual(placed["x"], SECOND.x)
        self.assertLessEqual(placed["x"] + placed["width"], SECOND.x + SECOND.width)
        self.assertGreaterEqual(placed["y"], SECOND.y)
        self.assertLessEqual(placed["y"] + placed["height"], SECOND.y + SECOND.height)

    def test_negative_off_screen_is_pulled_onto_the_primary(self):
        placed = clamp_geometry(
            {"x": -4000, "y": -2000, "width": 900, "height": 640},
            [PRIMARY, SECOND],
        )
        self.assertEqual(placed, {"x": 0, "y": 0, "width": 900, "height": 640})

    def test_oversized_window_shrinks_to_the_display(self):
        placed = clamp_geometry(
            {"x": 2000, "y": 10, "width": 4000, "height": 3000},
            [PRIMARY, SECOND],
        )
        self.assertLessEqual(placed["width"], SECOND.width)
        self.assertLessEqual(placed["height"], SECOND.height)
        self.assertGreaterEqual(placed["x"], SECOND.x)
        self.assertLessEqual(placed["x"] + placed["width"], SECOND.x + SECOND.width)
        self.assertGreaterEqual(placed["y"], SECOND.y)
        self.assertLessEqual(placed["y"] + placed["height"], SECOND.y + SECOND.height)

    def test_unknown_displays_use_the_origin_corner(self):
        placed = clamp_geometry(
            {"x": 9000, "y": -4000, "width": 2000, "height": 2000},
            [],
        )
        self.assertEqual(placed, {"x": 40, "y": 40, "width": 1280, "height": 800})
        self.assertIsNone(clamp_geometry(None, [PRIMARY]))

    def test_xrandr_text_lists_connected_displays_only(self):
        screens = parse_xrandr(XRANDR)
        self.assertEqual(screens, [PRIMARY, SECOND])
        left = parse_xrandr(LISTMONITORS)
        self.assertEqual(left, [PRIMARY, LEFT])

    def test_default_spot_is_on_the_only_display(self):
        only = Screen(1920, 0, 1600, 900)
        geom = default_geometry([only])
        self.assertGreaterEqual(geom["x"], only.x)
        self.assertLessEqual(geom["x"] + geom["width"], only.x + only.width)
        self.assertGreaterEqual(geom["y"], only.y)
        self.assertLessEqual(geom["y"] + geom["height"], only.y + only.height)


class CommandLineTests(unittest.TestCase):
    def test_app_window_profile_and_saved_spot(self):
        cmd = build_chromium_command(
            "/usr/bin/chromium",
            "http://127.0.0.1:8787/?wims_place=1",
            "/home/op/.local/state/wims/console-browser",
            {"x": 12, "y": 34, "width": 800, "height": 600},
        )
        self.assertEqual(cmd[0], "/usr/bin/chromium")
        self.assertIn("--app=http://127.0.0.1:8787/?wims_place=1", cmd)
        self.assertIn(
            "--user-data-dir=/home/op/.local/state/wims/console-browser",
            cmd,
        )
        self.assertIn("--window-size=800,600", cmd)
        self.assertIn("--window-position=12,34", cmd)
        self.assertIn("--no-first-run", cmd)
        self.assertIn("--no-default-browser-check", cmd)

    def test_no_saved_spot_omits_position_flags(self):
        cmd = build_chromium_command(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "http://127.0.0.1:8787/?wims_place=1",
            r"C:\Users\op\AppData\Local\WIMS\console-browser",
            None,
        )
        joined = " ".join(cmd)
        self.assertNotIn("--window-size", joined)
        self.assertNotIn("--window-position", joined)
        self.assertTrue(any(part.startswith("--user-data-dir=") for part in cmd))
        self.assertTrue(cmd[1].startswith("--app="))

    def test_placed_url_marks_only_the_launcher_window(self):
        self.assertEqual(
            placed_console_url("http://127.0.0.1:8787/status"),
            "http://127.0.0.1:8787/status?wims_place=1",
        )


class ReuseDecisionTests(unittest.TestCase):
    def test_local_page_reuses_and_remote_viewers_do_not_block_open(self):
        self.assertEqual(
            decide_reuse(local_sse=1, ping_age_s=None, remote_sse=0),
            "reuse",
        )
        self.assertEqual(
            decide_reuse(local_sse=0, ping_age_s=None, remote_sse=4),
            "open",
        )
        self.assertEqual(
            decide_reuse(local_sse=1, ping_age_s=None, remote_sse=9),
            "reuse",
        )
        self.assertEqual(
            decide_reuse(local_sse=0, ping_age_s=2.0, remote_sse=4),
            "reuse",
        )
        self.assertEqual(
            decide_reuse(local_sse=0, ping_age_s=5.0, remote_sse=0),
            "reuse",
        )
        self.assertEqual(
            decide_reuse(local_sse=0, ping_age_s=5.1, remote_sse=0),
            "open",
        )
        self.assertEqual(
            decide_reuse(local_sse=0, ping_age_s=None, remote_sse=0),
            "open",
        )

    def test_hub_counts_local_pages_only(self):
        hub = ConsoleHub(boot="b")
        self.assertFalse(hub.presence(10.0)["local_open"])
        # A remote ping must not count, even if it claims to be the placed window.
        ignored = handle_ping_post(
            {"placed": True}, client_local=False, hub=hub, now=10.0,
        )
        self.assertFalse(ignored["counted"])
        self.assertFalse(hub.presence(10.0)["local_open"])
        counted = handle_ping_post(
            {"placed": True}, client_local=True, hub=hub, now=10.0,
        )
        self.assertTrue(counted["counted"])
        self.assertTrue(hub.presence(12.0)["local_open"])
        self.assertFalse(hub.presence(16.0)["local_open"])
        hub.sse_enter()
        self.assertTrue(hub.presence(100.0)["local_open"])
        self.assertEqual(hub.presence(100.0)["local_sse"], 1)
        hub.sse_exit()
        self.assertFalse(hub.presence(100.0)["local_open"])

    def test_another_pc_is_not_a_local_client_or_this_pc(self):
        own = {"192.168.1.5"}
        self.assertTrue(client_is_local("127.0.0.1", own))
        self.assertTrue(client_is_local("::1", own))
        self.assertTrue(client_is_local("::ffff:127.0.0.1", own))
        self.assertTrue(client_is_local("192.168.1.5", own))
        self.assertFalse(client_is_local("192.168.1.20", own))
        self.assertTrue(console_is_on_this_pc("http://127.0.0.1:8787/", own))
        self.assertTrue(console_is_on_this_pc("http://192.168.1.5:8787/", own))
        self.assertFalse(console_is_on_this_pc("http://10.9.9.9:8787/", own))

    def test_remote_server_presence_does_not_stop_this_pc_opening(self):
        def fetch(*_args, **_kwargs):
            raise AssertionError("asked the other PC whether its console is open")

        self.assertFalse(local_console_is_open(
            "http://10.9.9.9:8787/",
            own={"192.168.1.5"},
            fetch=fetch,
        ))
        seen = {}

        def fetch_local(url, _timeout):
            seen["url"] = url
            return {"ok": True, "local_open": False, "local_sse": 0}

        self.assertFalse(local_console_is_open(
            "http://127.0.0.1:8787/",
            own=set(),
            fetch=fetch_local,
        ))
        self.assertIn("/api/console/presence", seen["url"])

    def test_reload_and_reset_do_not_touch_remote_pages(self):
        hub = ConsoleHub(boot="boot-1")
        snap = {"instances": [], "roster": {"count": 0}}
        remote = attach_console_ctrl(snap, None)
        self.assertIs(remote, snap)
        self.assertNotIn("console_ctrl", remote)

        refused, body = handle_reload_post(client_local=False, hub=hub)
        self.assertFalse(refused)
        self.assertFalse(body["ok"])
        self.assertEqual(hub.control()["reload"], 0)

        reset_refused, reset_body = handle_reset_post(
            {"x": 1, "y": 2, "width": 900, "height": 640},
            client_local=False, hub=hub,
        )
        self.assertFalse(reset_refused)
        self.assertFalse(reset_body["ok"])
        self.assertEqual(hub.control()["reset"], 0)
        self.assertNotIn("reset_to", hub.control())

        accepted, _ = handle_reload_post(client_local=True, hub=hub)
        self.assertTrue(accepted)
        local = attach_console_ctrl(dict(snap), hub.control())
        self.assertEqual(local["console_ctrl"]["local"], True)
        self.assertEqual(local["console_ctrl"]["boot"], "boot-1")
        self.assertEqual(local["console_ctrl"]["reload"], 1)
        # The shared snapshot the remote page would render is unchanged.
        self.assertEqual(snap, {"instances": [], "roster": {"count": 0}})
        self.assertNotIn("console_ctrl", attach_console_ctrl(dict(snap), None))

        # A restart is a new boot. Only the local payload carries it, so a
        # remote page is not told to reload.
        restarted = ConsoleHub(boot="boot-2")
        after = attach_console_ctrl(dict(snap), restarted.control())
        self.assertEqual(after["console_ctrl"]["boot"], "boot-2")
        self.assertEqual(after["console_ctrl"]["reload"], 0)
        untouched = attach_console_ctrl(dict(snap), None)
        self.assertEqual(untouched, snap)

        moved, _ = handle_reset_post(
            {"x": 40, "y": 40, "width": 900, "height": 640},
            client_local=True, hub=hub,
        )
        self.assertTrue(moved)
        ctrl = hub.control()
        self.assertEqual(ctrl["reset"], 1)
        self.assertEqual(ctrl["reset_to"]["x"], 40)
        remote_again = attach_console_ctrl(dict(snap), None)
        self.assertNotIn("console_ctrl", remote_again)

    def test_reload_is_not_posted_to_another_pc(self):
        def post(*_args, **_kwargs):
            raise AssertionError("reload posted to the other PC")

        self.assertFalse(request_console_reload(
            "http://10.9.9.9:8787/",
            own={"192.168.1.5"},
            post=post,
        ))

    def test_open_message_is_plain(self):
        for mode in ("reuse", "app", "browser", "kiosk"):
            text = console_open_message(mode)
            self.assertNotIn("--", text)
            self.assertNotIn("PYTHONPATH", text)
            self.assertNotIn("python", text.lower())
        self.assertIn("already open", console_open_message("reuse").lower())
        self.assertIn("cannot be placed", console_open_message("browser"))
        self.assertIn("cannot be placed", console_open_message("kiosk"))
        self.assertIn("Chrome", console_open_message("browser"))


if __name__ == "__main__":
    unittest.main()
