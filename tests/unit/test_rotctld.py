# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only rotctld poll: fake server, heading, and a clean disconnect."""

from __future__ import annotations

import json
import socket
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

from wims.agent.report import build_report, format_report_text  # noqa: E402
from wims.integrations.rotator.registry import RotatorRegistry  # noqa: E402
from wims.integrations.antenna.model import public_antennas  # noqa: E402
from wims.integrations.rotator.rotctld import (  # noqa: E402
    RADIO_PORT,
    AntennaPoller,
    parse_get_pos,
)
from wims.launcher.assets import (  # noqa: E402
    INTENT_ANTENNAS,
    save_antennas,
    save_seat_intent,
)
from wims.server.app import LiveFleet  # noqa: E402


class FakeRotctld:
    """Minimal hamlib rotctld: answers ``p`` with azimuth, elevation, RPRT 0."""

    def __init__(self, az: float = 212.0, el: float = 0.0, *, reply: bool = True):
        self.az = az
        self.el = el
        self.reply = reply
        self.commands: list[bytes] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients: list[socket.socket] = []
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind(("127.0.0.1", 0))
        self._listen.listen(8)
        self._listen.settimeout(0.2)
        self.port = self._listen.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(0.2)
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(256)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.strip()
                    with self._lock:
                        self.commands.append(cmd)
                    if not self.reply:
                        continue
                    if cmd == b"p":
                        msg = f"{self.az:.6f}\n{self.el:.6f}\nRPRT 0\n".encode()
                    else:
                        msg = b"RPRT -1\n"
                    try:
                        conn.sendall(msg)
                    except OSError:
                        return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._listen.close()
        except OSError:
            pass
        with self._lock:
            clients = list(self._clients)
        for conn in clients:
            try:
                conn.close()
            except OSError:
                pass
        self._thread.join(timeout=1.0)


class ParseTests(unittest.TestCase):
    def test_bare_floats_and_rprt(self):
        az, el = parse_get_pos("212.000000\n0.000000\nRPRT 0\n")
        self.assertEqual(az, 212.0)
        self.assertEqual(el, 0.0)

    def test_labeled_lines(self):
        az, el = parse_get_pos("Azimuth: 212.5\nElevation: 10\nRPRT 0\n")
        self.assertEqual(az, 212.5)
        self.assertEqual(el, 10.0)

    def test_azimuth_only(self):
        az, el = parse_get_pos("90\n")
        self.assertEqual(az, 90.0)
        self.assertIsNone(el)

    def test_rprt_error(self):
        with self.assertRaises(ValueError):
            parse_get_pos("RPRT -1\n")


class PollTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        pref = Path(self._td.name) / "seat_intent.json"
        self._env = mock.patch.dict("os.environ", {"WIMS_SEAT_INTENT": str(pref)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _enable(self, antennas: list[dict]) -> None:
        save_seat_intent({INTENT_ANTENNAS: True})
        save_antennas(antennas)

    def _one(self, host: str, port: int, *, name: str = "6m beam",
             extra: list | None = None) -> list[dict]:
        devices = [{
            "id": "dev-rot",
            "kind": "rotator",
            "host": host,
            "port": port,
        }]
        if extra:
            devices.extend(extra)
        return [{
            "id": "ant-6m",
            "name": name,
            "devices": devices,
        }]

    def _poller(self) -> AntennaPoller:
        return AntennaPoller(
            interval=0.2, misses=3, connect_timeout=0.4, read_timeout=0.4,
        )

    @staticmethod
    def _rot(row: dict) -> dict:
        return next(d for d in row["devices"] if d.get("kind") == "rotator")

    def test_reads_heading_and_sends_only_position_poll(self):
        server = FakeRotctld(az=212.0, el=4.0)
        self.addCleanup(server.stop)
        self._enable(self._one("127.0.0.1", server.port))
        poller = self._poller()
        self.addCleanup(poller.close)
        row = poller.poll_once()[0]
        dev = self._rot(row)
        self.assertEqual(row["name"], "6m beam")
        self.assertEqual(dev["kind"], "rotator")
        self.assertEqual(dev["az"], 212.0)
        self.assertEqual(dev["el"], 4.0)
        self.assertEqual(dev["connection"], "connected")
        self.assertEqual(dev["link"], "up")
        self.assertTrue(dev["link_ok"])
        blob = json.dumps(row)
        self.assertNotIn("host", dev)
        self.assertNotIn("port", dev)
        self.assertNotIn(str(server.port), blob)
        poller.poll_once()
        poller.close()
        self.assertTrue(server.commands)
        self.assertTrue(all(cmd == b"p" for cmd in server.commands))

    def test_three_misses_then_heading_unknown(self):
        server = FakeRotctld(az=180.0, el=0.0)
        self.addCleanup(server.stop)
        self._enable(self._one("127.0.0.1", server.port))
        poller = self._poller()
        self.addCleanup(poller.close)
        self.assertEqual(self._rot(poller.poll_once()[0])["connection"], "connected")
        server.stop()
        first = self._rot(poller.poll_once()[0])
        second = self._rot(poller.poll_once()[0])
        third = self._rot(poller.poll_once()[0])
        self.assertEqual(first["connection"], "connected")
        self.assertEqual(first["az"], 180.0)
        self.assertEqual(second["connection"], "connected")
        self.assertEqual(second["az"], 180.0)
        self.assertEqual(third["connection"], "stale")
        self.assertIsNone(third["az"])
        self.assertEqual(third["link"], "down")
        self.assertIn("unknown", third["detail"].lower())

    def test_silent_rotctld_is_a_miss(self):
        server = FakeRotctld(reply=False)
        self.addCleanup(server.stop)
        self._enable(self._one("127.0.0.1", server.port, name="quiet"))
        poller = AntennaPoller(
            interval=0.2, misses=3, connect_timeout=0.3, read_timeout=0.2,
        )
        self.addCleanup(poller.close)
        started = time.monotonic()
        dev = self._rot(poller.poll_once()[0])
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(dev["connection"], "stale")
        self.assertIsNone(dev["az"])
        self.assertEqual(server.commands, [b"p"])

    def test_radio_port_is_not_opened(self):
        self._enable(self._one("127.0.0.1", RADIO_PORT))
        poller = self._poller()
        self.addCleanup(poller.close)
        with mock.patch(
            "wims.integrations.rotator.rotctld.socket.create_connection",
            side_effect=AssertionError("should not connect"),
        ):
            row = poller.poll_once()[0]
        dev = self._rot(row)
        self.assertEqual(dev["connection"], "stale")
        self.assertIsNone(dev["az"])
        self.assertIn("radio", dev["detail"].lower())
        blob = json.dumps(row)
        self.assertNotIn(str(RADIO_PORT), blob)
        self.assertNotIn("host", dev)
        self.assertNotIn("port", dev)

    def test_intent_off_does_not_connect(self):
        server = FakeRotctld()
        self.addCleanup(server.stop)
        save_seat_intent({INTENT_ANTENNAS: False})
        save_antennas(self._one("127.0.0.1", server.port))
        poller = self._poller()
        self.addCleanup(poller.close)
        self.assertEqual(poller.poll_once(), [])
        self.assertIsNone(poller.snapshot_for_report())
        self.assertEqual(server.commands, [])

    def test_stopped_rotctld_does_not_raise(self):
        self._enable(self._one("127.0.0.1", 1))  # nothing is listening
        poller = AntennaPoller(
            interval=0.2, misses=1, connect_timeout=0.2, read_timeout=0.2,
        )
        self.addCleanup(poller.close)
        dev = self._rot(poller.poll_once()[0])
        self.assertEqual(dev["connection"], "stale")
        self.assertIsNone(dev["az"])
        again = self._rot(poller.poll_once()[0])
        self.assertEqual(again["connection"], "stale")
        self.assertIsNone(again["az"])

    def test_tuner_and_switch_are_not_opened(self):
        server = FakeRotctld(az=10.0, el=0.0)
        self.addCleanup(server.stop)
        self._enable(self._one("127.0.0.1", server.port, extra=[
            {"id": "dev-tun", "kind": "tuner"},
            {"id": "dev-sw", "kind": "switch"},
        ]))
        poller = self._poller()
        self.addCleanup(poller.close)
        row = poller.poll_once()[0]
        kinds = [d["kind"] for d in row["devices"]]
        self.assertEqual(kinds, ["rotator", "tuner", "switch"])
        for dev in row["devices"]:
            if dev["kind"] == "rotator":
                self.assertEqual(dev["connection"], "connected")
            else:
                self.assertEqual(dev["connection"], "stale")
                self.assertEqual(dev["detail"], "Not read yet.")
                self.assertIsNone(dev["az"])
        self.assertTrue(server.commands)
        self.assertTrue(all(cmd == b"p" for cmd in server.commands))
        blob = json.dumps(row)
        self.assertNotIn("tty", blob)
        self.assertNotIn("serial", blob.lower())


class ReportPathTests(unittest.TestCase):
    def test_registry_clears_heading_when_link_down(self):
        reg = RotatorRegistry()
        n = reg.ingest_report([{
            "id": "rot-6m",
            "name": "6m beam",
            "az": 212.0,
            "link": "up",
            "connection": "connected",
            "link_ok": True,
        }], agent_id="seat-1")
        self.assertEqual(n, 1)
        st = reg.get("rot-6m")
        assert st is not None
        self.assertEqual(st.az, 212.0)
        self.assertEqual(st.label, "6m beam")
        reg.ingest_report([{
            "id": "rot-6m",
            "name": "6m beam",
            "az": 212.0,
            "link": "down",
            "connection": "stale",
        }], agent_id="seat-1")
        st = reg.get("rot-6m")
        assert st is not None
        self.assertIsNone(st.az)
        self.assertFalse(st.link_ok)

    def test_empty_report_drops_that_agents_rotors(self):
        reg = RotatorRegistry()
        reg.ingest_report(
            [{"id": "rot-6m", "name": "6m beam", "az": 10, "link_ok": True}],
            agent_id="seat-1",
        )
        reg.ingest_report(
            [{"id": "other", "az": 20, "link_ok": True}],
            agent_id="seat-2",
        )
        reg.ingest_report([], agent_id="seat-1")
        self.assertIsNone(reg.get("rot-6m"))
        self.assertIsNotNone(reg.get("other"))
        # A report with no rotators key does not wipe the rest.
        reg.ingest_report(None, agent_id="seat-2")
        self.assertIsNotNone(reg.get("other"))

    def test_live_snapshot_hides_stale_heading(self):
        live = LiveFleet()
        live.accept_agent_report({
            "agent_id": "seat-a",
            "antennas": [{
                "id": "ant-6m",
                "name": "6m beam",
                "devices": [{
                    "id": "dev-rot",
                    "kind": "rotator",
                    "az": 212.0,
                    "connection": "connected",
                    "host": "127.0.0.1",
                    "port": 4535,
                    "serial": "/dev/ttyUSB0",
                }],
            }],
        })
        snap = live.snapshot(time.time())
        ant = snap["antennas"][0]
        dev = ant["devices"][0]
        self.assertEqual(ant["name"], "6m beam")
        self.assertEqual(dev["kind"], "rotator")
        self.assertEqual(dev["az"], 212.0)
        self.assertEqual(dev["connection"], "connected")
        blob = json.dumps(ant)
        self.assertNotIn("127.0.0.1", blob)
        self.assertNotIn("4535", blob)
        self.assertNotIn("ttyUSB", blob)
        live.accept_agent_report({
            "agent_id": "seat-a",
            "antennas": [{
                "id": "ant-6m",
                "name": "6m beam",
                "devices": [{
                    "id": "dev-rot",
                    "kind": "rotator",
                    "az": 212.0,
                    "connection": "stale",
                    "link": "down",
                    "detail": "Heading unknown.",
                }],
            }],
        })
        snap = live.snapshot(time.time())
        dev = snap["antennas"][0]["devices"][0]
        self.assertIsNone(dev["az"])
        self.assertEqual(dev["connection"], "stale")
        self.assertEqual(dev["link"], "down")
        live.accept_agent_report({"agent_id": "seat-a", "antennas": []})
        snap = live.snapshot(time.time())
        self.assertEqual(snap["antennas"], [])

    def test_public_view_drops_address(self):
        rows = public_antennas([{
            "name": "6m beam",
            "devices": [{
                "kind": "rotator",
                "connection": "connected",
                "az": 1,
                "host": "10.0.0.1",
                "port": 4535,
                "serial": "/dev/ttyUSB0",
            }],
        }])
        blob = json.dumps(rows)
        self.assertNotIn("10.0.0.1", blob)
        self.assertNotIn("4535", blob)
        self.assertNotIn("ttyUSB", blob)

    def test_report_text_names_the_heading(self):
        text = format_report_text({
            "agent_id": "seat",
            "host": {"hostname": "pc"},
            "summary": {"severity": "ok", "message": "ok"},
            "apps": {},
            "antennas": [{
                "name": "6m beam",
                "devices": [{
                    "kind": "rotator",
                    "az": 212.0,
                    "connection": "connected",
                }],
            }],
        }, skip_wsjtx=True)
        self.assertIn("6m beam (rotator): 212.0 deg, connected", text)
        stale = format_report_text({
            "agent_id": "seat",
            "host": {},
            "summary": {},
            "apps": {},
            "antennas": [{
                "name": "6m beam",
                "devices": [{
                    "kind": "rotator",
                    "az": None,
                    "connection": "stale",
                }],
            }],
        }, skip_wsjtx=True)
        self.assertIn("6m beam (rotator): heading unknown, stale", stale)

    def test_build_report_uses_polled_rows(self):
        rep = build_report(rotator_reports=[{
            "id": "rot-6m",
            "name": "6m beam",
            "az": 212.0,
            "connection": "connected",
        }])
        self.assertEqual(rep["rotators"][0]["name"], "6m beam")
        self.assertEqual(rep["rotators"][0]["az"], 212.0)


if __name__ == "__main__":
    unittest.main()
