# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restart the site server on this PC, and refuse every other case.

No real process is killed. The OS and HTTP edges are injected.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.server_rev import RESTART_NEEDED_MARK  # noqa: E402
from wims.launcher.site_restart import (  # noqa: E402
    DID_NOT_COME_UP_MESSAGE,
    NOT_IDENTIFIED_MESSAGE,
    NOT_WIMS_MESSAGE,
    NOT_WIMS_PROCESS_MESSAGE,
    STILL_OLD_MESSAGE,
    banner_for_restart,
    clear_site_server_pid,
    client_is_loopback,
    handle_shutdown_request,
    identify_site_server,
    is_wims_site_server_argv,
    other_pc_message,
    parse_netstat_listeners,
    parse_proc_net_inodes,
    perform_site_restart,
    read_site_server_pid,
    restarted_message,
    shutdown_status,
    write_site_server_pid,
)


_OLD = "bbb2222 2026-10-01 08:00:00 +0000"
_NEW = "ccc3333 2026-10-19 12:00:00 +0000"
_SOLO = ["python3", "-m", "wims.solo"]
_NGINX = ["nginx", "-g", "daemon off;"]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += float(dt)


def _health(rev: str, *, pid: int | None = None, host: str = "shack") -> dict:
    body = {
        "ok": True,
        "role": "wims-site-server",
        "server_rev": rev,
        "hostname": host,
    }
    if pid is not None:
        body["pid"] = pid
    return body


class IdentifyTests(unittest.TestCase):
    def test_port_owner_solo_is_the_local_server(self):
        found = identify_site_server(
            health=_health(_OLD),
            port=8787,
            listener_pids=[4242],
            pid_file=None,
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda _pid: True,
        )
        self.assertEqual(found.pids, (4242,))
        self.assertEqual(found.source, "port")

    def test_pid_file_when_the_port_lookup_is_empty(self):
        found = identify_site_server(
            health=_health(_OLD, pid=4242),
            port=8787,
            listener_pids=[],
            pid_file=(4242, 8787),
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda _pid: True,
        )
        self.assertEqual(found.pids, (4242,))
        self.assertEqual(found.source, "pidfile")

    def test_nginx_on_the_port_is_refused(self):
        found = identify_site_server(
            health=_health(_OLD, pid=77),
            port=8787,
            listener_pids=[77],
            pid_file=(77, 8787),
            argv_of=lambda _pid: _NGINX,
            alive=lambda _pid: True,
        )
        self.assertEqual(found.pids, ())
        self.assertEqual(found.reason, "not-wims-process")

    def test_health_that_is_not_wims_names_no_pid(self):
        found = identify_site_server(
            health={"ok": True, "role": "something-else"},
            port=8787,
            listener_pids=[4242],
            pid_file=(4242, 8787),
            argv_of=lambda _pid: _SOLO,
            alive=lambda _pid: True,
        )
        self.assertEqual(found.pids, ())
        self.assertEqual(found.reason, "not-wims")

    def test_stale_pid_file_is_not_the_process_health_named(self):
        found = identify_site_server(
            health=_health(_OLD, pid=4242),
            port=8787,
            listener_pids=[],
            pid_file=(99, 8787),
            argv_of=lambda pid: _NGINX if pid == 99 else _SOLO,
            alive=lambda _pid: True,
        )
        self.assertEqual(found.pids, ())

    def test_argv_recognises_solo_and_rejects_other_programs(self):
        self.assertTrue(is_wims_site_server_argv(["python3", "-m", "wims.solo"]))
        self.assertTrue(is_wims_site_server_argv(
            ["python", "-m", "wims.server.app"],
        ))
        self.assertFalse(is_wims_site_server_argv(["python3", "-m", "wims.launcher"]))
        self.assertFalse(is_wims_site_server_argv(_NGINX))


class RestartTests(unittest.TestCase):
    def _run(self, **kwargs):
        clock = _Clock()
        kwargs.setdefault("port", 8787)
        kwargs.setdefault("disk_rev", _NEW)
        kwargs.setdefault("sleep", clock.sleep)
        kwargs.setdefault("monotonic", clock.monotonic)
        kwargs.setdefault("read_pid_file", lambda: None)
        kwargs.setdefault("on_this_pc", True)
        return perform_site_restart(**kwargs)

    def test_local_orphaned_solo_restarts_and_revision_matches(self):
        """The bug: python -m wims.solo left running by an earlier window."""
        state = {"up": True, "started": False}
        stopped: list[int] = []

        def fetch():
            if not state["up"]:
                return None
            # Older build: /healthz has no pid. The pid file names a different process.
            if state["started"]:
                return _health(_NEW, pid=5000)
            return _health(_OLD)

        def stop(pid: int) -> None:
            stopped.append(pid)
            state["up"] = False

        def start() -> None:
            state["started"] = True
            state["up"] = True

        outcome = self._run(
            fetch_health=fetch,
            start_server=start,
            request_stop=lambda: False,
            stop_pid=stop,
            listener_pids=[4242],
            pid_file=(99, 8787),
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda pid: pid == 4242 and state["up"] and not state["started"],
            port_open=lambda: state["up"],
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.message, restarted_message("ccc3333"))
        self.assertEqual(outcome.rev, "ccc3333")
        self.assertEqual(stopped, [4242])

    def test_pid_file_orphan_is_restarted_when_the_port_lookup_is_empty(self):
        state = {"up": True, "started": False}
        stopped: list[int] = []

        def fetch():
            if not state["up"]:
                return None
            if state["started"]:
                return _health(_NEW, pid=5000)
            return _health(_OLD, pid=4242)

        outcome = self._run(
            fetch_health=fetch,
            start_server=lambda: state.update(started=True, up=True),
            request_stop=lambda: False,
            stop_pid=lambda pid: stopped.append(pid) or state.update(up=False),
            listener_pids=[],
            pid_file=(4242, 8787),
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda pid: pid == 4242 and state["up"] and not state["started"],
            port_open=lambda: state["up"],
        )
        self.assertEqual(stopped, [4242])
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.message, "Restarted on ccc3333")

    def test_other_pc_is_refused_and_restart_needed_stays(self):
        stopped: list[int] = []
        started: list[int] = []
        asked: list[int] = []
        outcome = self._run(
            on_this_pc=False,
            other_host="trailer",
            fetch_health=lambda: _health(_OLD, host="trailer"),
            start_server=lambda: started.append(1),
            request_stop=lambda: asked.append(1) or False,
            stop_pid=lambda pid: stopped.append(pid),
            listener_pids=[4242],
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda _pid: True,
            port_open=lambda: True,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(stopped, [])
        self.assertEqual(started, [])
        self.assertEqual(asked, [])
        self.assertEqual(outcome.message, other_pc_message("trailer"))
        self.assertIn("trailer", outcome.message)
        self.assertIn("Restart it on that PC", outcome.message)
        level, title, detail = banner_for_restart(
            in_progress=False, message=outcome.message, ok=False, stale=True,
        )
        self.assertEqual(level, "warn")
        self.assertEqual(title, RESTART_NEEDED_MARK)
        self.assertIn("trailer", detail)

    def test_non_wims_process_is_not_stopped(self):
        stopped: list[int] = []
        started: list[int] = []
        asked: list[int] = []
        outcome = self._run(
            fetch_health=lambda: _health(_OLD, pid=77),
            start_server=lambda: started.append(1),
            request_stop=lambda: asked.append(1) or True,
            stop_pid=lambda pid: stopped.append(pid),
            listener_pids=[77],
            pid_file=(77, 8787),
            argv_of=lambda _pid: _NGINX,
            alive=lambda _pid: True,
            port_open=lambda: True,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(stopped, [])
        self.assertEqual(started, [])
        self.assertEqual(asked, [])
        self.assertEqual(outcome.message, NOT_WIMS_PROCESS_MESSAGE)

    def test_closed_port_that_is_not_wims_is_left_alone(self):
        stopped: list[int] = []
        outcome = self._run(
            fetch_health=lambda: None,
            start_server=lambda: None,
            stop_pid=lambda pid: stopped.append(pid),
            listener_pids=[77],
            argv_of=lambda _pid: _NGINX,
            port_open=lambda: True,
        )
        self.assertEqual(outcome.message, NOT_WIMS_MESSAGE)
        self.assertEqual(stopped, [])

    def test_revision_mismatch_after_restart_is_a_plain_failure(self):
        state = {"up": True, "started": False}

        def fetch():
            if not state["up"]:
                return None
            return _health(_OLD, pid=4242 if not state["started"] else 5000)

        def start() -> None:
            state["started"] = True
            state["up"] = True

        outcome = self._run(
            fetch_health=fetch,
            start_server=start,
            request_stop=lambda: False,
            stop_pid=lambda _pid: state.update(up=False),
            listener_pids=[4242],
            argv_of=lambda pid: _SOLO if pid == 4242 else _NGINX,
            alive=lambda pid: pid == 4242 and not state["started"],
            port_open=lambda: state["up"],
        )
        self.assertFalse(outcome.ok)
        self.assertTrue(state["started"])
        self.assertEqual(outcome.message, STILL_OLD_MESSAGE)
        self.assertNotEqual(outcome.message, restarted_message("ccc3333"))

    def test_server_that_does_not_come_back_says_so(self):
        state = {"up": True}

        outcome = self._run(
            fetch_health=lambda: _health(_OLD, pid=4242) if state["up"] else None,
            start_server=lambda: None,
            request_stop=lambda: False,
            stop_pid=lambda _pid: state.update(up=False),
            listener_pids=[4242],
            argv_of=lambda pid: _SOLO if pid == 4242 else None,
            alive=lambda pid: state["up"] and pid == 4242,
            port_open=lambda: state["up"],
        )
        self.assertEqual(outcome.message, DID_NOT_COME_UP_MESSAGE)

    def test_unidentified_local_server_is_not_killed_or_replaced(self):
        stopped: list[int] = []
        started: list[int] = []
        outcome = self._run(
            fetch_health=lambda: _health(_OLD),
            start_server=lambda: started.append(1),
            stop_pid=lambda pid: stopped.append(pid),
            listener_pids=[],
            pid_file=None,
            argv_of=lambda _pid: None,
            port_open=lambda: True,
        )
        self.assertEqual(outcome.message, NOT_IDENTIFIED_MESSAGE)
        self.assertEqual(stopped, [])
        self.assertEqual(started, [])


class PidFileTests(unittest.TestCase):
    def test_round_trip_and_a_newer_pid_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site-server.pid"
            write_site_server_pid(4242, 8787, path)
            self.assertEqual(read_site_server_pid(path), (4242, 8787))
            write_site_server_pid(5000, 8787, path)
            clear_site_server_pid(path, pid=4242)
            self.assertEqual(read_site_server_pid(path), (5000, 8787))
            clear_site_server_pid(path, pid=5000)
            self.assertIsNone(read_site_server_pid(path))


class ShutdownTests(unittest.TestCase):
    def test_loopback_only(self):
        self.assertTrue(client_is_loopback("127.0.0.1"))
        self.assertTrue(client_is_loopback("::1"))
        self.assertFalse(client_is_loopback("192.168.1.50"))
        self.assertEqual(shutdown_status("127.0.0.1"), 200)
        self.assertEqual(shutdown_status("10.1.2.3"), 403)

        class Handler:
            client_address = ("192.168.1.50", 4000)
            sent: list = []

            def _send_json(self, code, obj):
                self.sent.append((code, obj))

        remote = Handler()
        self.assertFalse(handle_shutdown_request(remote))
        self.assertEqual(remote.sent, [(403, {"ok": False})])

    def test_healthz_pid_and_localhost_shutdown(self):
        import wims.server.app as server_app

        httpd = HTTPServer(("127.0.0.1", 0), server_app.make_handler(object(), 1.0))
        called: list[int] = []
        httpd.shutdown = lambda: called.append(1)  # type: ignore[method-assign]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["role"], "wims-site-server")
            self.assertEqual(data["pid"], os.getpid())
            req = Request(
                f"http://127.0.0.1:{port}/shutdown",
                data=b"{}",
                method="POST",
            )
            with urlopen(req, timeout=2) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
            self.assertTrue(body.get("ok"))
            import time
            for _ in range(50):
                if called:
                    break
                time.sleep(0.02)
            self.assertEqual(called, [1])
        finally:
            httpd.server_close()
            thread.join(timeout=1)


class PortOwnerTests(unittest.TestCase):
    def test_listening_pids_sees_this_process(self):
        import socket
        from wims.launcher.site_restart import listening_pids

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            pids = listening_pids(port)
        finally:
            sock.close()
        self.assertIn(os.getpid(), pids)


class PortParseTests(unittest.TestCase):
    def test_proc_net_listen_inode(self):
        text = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:2253 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4242 1 00000000 100 0 0 10 0\n"
            "   1: 0100007F:2254 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 9999 1 00000000 100 0 0 10 0\n"
        )
        self.assertEqual(parse_proc_net_inodes(text, 8787), ["4242"])

    def test_netstat_listening_pid(self):
        text = (
            "  TCP    0.0.0.0:8787           0.0.0.0:0              LISTENING       4242\n"
            "  TCP    127.0.0.1:87870        0.0.0.0:0              LISTENING       9999\n"
            "  TCP    [::]:8787              [::]:0                 LISTENING       4242\n"
        )
        self.assertEqual(parse_netstat_listeners(text, 8787), [4242])


if __name__ == "__main__":
    unittest.main()
