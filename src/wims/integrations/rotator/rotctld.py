# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only hamlib rotctld client (plan §2.10 step 1).

Polls position with the ``p`` command. This module does not turn a rotor
and does not send a position or a stop.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable

# Hamlib rigctld on the preferred Icom seat already uses 4533.
# A rotator endpoint on that port is the radio, not a rotor.
RADIO_PORT = 4533

# About once a second. Three misses, then the heading is unknown.
POLL_INTERVAL_S = 1.0
MISS_LIMIT = 3
CONNECT_TIMEOUT_S = 0.8
READ_TIMEOUT_S = 0.8

# The only bytes this module writes to rotctld.
_GET_POS = b"p\n"


class _Link:
    """One TCP session and its miss count."""

    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.misses: int = 0
        self.az: float | None = None
        self.el: float | None = None
        self.refused: bool = False
        self.detail: str = ""


def parse_get_pos(payload: str) -> tuple[float, float | None]:
    """Parse a rotctld ``get_pos`` reply into ``(azimuth, elevation)``.

    Accepts bare floats (``212.0`` / ``0.0`` / ``RPRT 0``) and labeled lines
    (``Azimuth:`` / ``Elevation:``). A non-zero ``RPRT`` is a failed read.
    """
    az: float | None = None
    el: float | None = None
    rprt: int | None = None
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("RPRT"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    rprt = int(float(parts[1]))
                except ValueError:
                    rprt = -1
            else:
                rprt = -1
            continue
        if ":" in line:
            label, _, rest = line.partition(":")
            token = rest.strip().split()[0] if rest.strip() else ""
            try:
                val = float(token)
            except ValueError:
                continue
            key = label.strip().lower()
            if key.startswith("az"):
                az = val
            elif key.startswith("el"):
                el = val
            elif az is None:
                az = val
            elif el is None:
                el = val
            continue
        try:
            val = float(line.split()[0])
        except ValueError:
            continue
        if az is None:
            az = val
        elif el is None:
            el = val
    if rprt is not None and rprt != 0:
        raise ValueError(f"rotctld RPRT {rprt}")
    if az is None or az != az or abs(az) == float("inf"):
        raise ValueError("rotctld position had no azimuth")
    if el is not None and (el != el or abs(el) == float("inf")):
        el = None
    return az, el


def read_get_pos(sock: socket.socket, timeout: float) -> tuple[float, float | None]:
    """Read one ``get_pos`` reply. Waits for ``RPRT`` or the timeout."""
    sock.settimeout(timeout)
    buf = b""
    deadline = time.monotonic() + max(0.05, float(timeout))
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(512)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        if b"RPRT" in buf.upper() or len(buf) > 4096:
            break
    if not buf:
        raise ValueError("rotctld sent no position")
    return parse_get_pos(buf.decode("ascii", "replace"))


def _close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _rotator_device(dev: dict, link: _Link, *, misses: int) -> dict:
    """Public rotator device. No host and no port."""
    from wims.integrations.antenna.model import KIND_ROTATOR
    live = (
        not link.refused
        and link.az is not None
        and link.misses < misses
    )
    detail = "" if live else (link.detail or "Heading unknown.")
    return {
        "id": str(dev.get("id") or ""),
        "kind": KIND_ROTATOR,
        "az": None if not live else float(link.az),
        "el": None if not live else link.el,
        "link": "up" if live else "down",
        "link_ok": live,
        "connection": "connected" if live else "stale",
        "health": "FAULT" if link.refused else ("OK" if live else "STALE"),
        "moving": False,
        "detail": detail,
    }


def _incomplete_rotator(dev: dict) -> dict:
    from wims.integrations.antenna.model import KIND_ROTATOR
    return {
        "id": str(dev.get("id") or ""),
        "kind": KIND_ROTATOR,
        "az": None,
        "el": None,
        "link": "down",
        "link_ok": False,
        "connection": "stale",
        "health": "STALE",
        "moving": False,
        "detail": "Add the rotctld address on this PC.",
    }


class AntennaPoller:
    """Poll antennas remembered on this PC while Antennas is checked.

    Only a rotator device opens rotctld, and only to read position. Tuner
    and switch devices are reported as not read yet. The launcher writes
    the list. This poller reads that file. It does not take a command-line
    flag or an environment variable.
    """

    def __init__(
        self,
        *,
        interval: float = POLL_INTERVAL_S,
        misses: int = MISS_LIMIT,
        connect_timeout: float = CONNECT_TIMEOUT_S,
        read_timeout: float = READ_TIMEOUT_S,
    ) -> None:
        self.interval = max(0.2, float(interval))
        self.misses = max(1, int(misses))
        self.connect_timeout = max(0.05, float(connect_timeout))
        self.read_timeout = max(0.05, float(read_timeout))
        self._lock = threading.Lock()
        self._links: dict[str, _Link] = {}
        self._rows: list[dict] = []
        self._intent_on = False
        self._polled = False
        self._last_job: tuple[bool, list[dict]] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_cycle: Callable[[list, bool], None] | None = None

    def intent_enabled(self) -> bool:
        job = self._read_job()
        return bool(job and job[0])

    def snapshot_for_report(self) -> list[dict] | None:
        """Antennas to put on the agent report.

        ``None`` means the antenna side is off, so the caller keeps the lab
        rotator path. A list (possibly empty) means Antennas is checked.
        """
        with self._lock:
            polled = self._polled
            intent_on = self._intent_on
            rows = list(self._rows)
        if not polled:
            job = self._read_job()
            if job is None or not job[0]:
                return None
            return []
        if not intent_on:
            return None
        return rows

    def poll_once(self) -> list[dict]:
        """One pass over remembered antennas. Safe to call from a test."""
        from wims.integrations.antenna.model import KIND_ROTATOR, unread_device
        job = self._read_job()
        if job is None:
            with self._lock:
                return list(self._rows)
        intent_on, antennas = job
        if not intent_on:
            self._close_all()
            with self._lock:
                self._intent_on = False
                self._polled = True
                self._rows = []
            return []
        rows: list[dict] = []
        keep: dict[str, _Link] = {}
        for ant in antennas:
            devices_out: list[dict] = []
            for dev in ant.get("devices") or []:
                if not isinstance(dev, dict):
                    continue
                kind = str(dev.get("kind") or "")
                if kind != KIND_ROTATOR:
                    devices_out.append(unread_device(dev))
                    continue
                rid = str(dev.get("id") or "")
                host = str(dev.get("host") or "").strip()
                port = dev.get("port")
                if not rid:
                    continue
                if not host or not isinstance(port, int):
                    devices_out.append(_incomplete_rotator(dev))
                    continue
                link = self._links.get(rid) or _Link()
                self._poll_link(host, int(port), link)
                keep[rid] = link
                devices_out.append(
                    _rotator_device(dev, link, misses=self.misses)
                )
            name = str(ant.get("name") or "").strip() or "Antenna"
            rows.append({
                "id": str(ant.get("id") or name),
                "name": name,
                "devices": devices_out,
            })
        for rid, link in list(self._links.items()):
            if rid not in keep:
                _close_socket(link.sock)
                link.sock = None
        self._links = keep
        with self._lock:
            self._intent_on = True
            self._polled = True
            self._rows = rows
        return list(rows)

    def start(self, on_cycle: Callable[[list, bool], None] | None = None) -> None:
        """Background poll. ``on_cycle(rows, intent_on)`` runs after each pass."""
        self._on_cycle = on_cycle
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="wims-antenna", daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop polling and drop every socket."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._close_all()

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            intent_on = False
            rows: list[dict] = []
            try:
                rows = self.poll_once()
                with self._lock:
                    intent_on = self._intent_on
            except Exception:
                with self._lock:
                    rows = list(self._rows)
                    intent_on = self._intent_on
            cb = self._on_cycle
            if cb is not None:
                try:
                    cb(rows, intent_on)
                except Exception:
                    pass
            remain = self.interval - (time.monotonic() - started)
            if self._stop.wait(max(0.05, remain)):
                break

    def _read_job(self) -> tuple[bool, list[dict]] | None:
        from wims.launcher.assets import load_antenna_side
        job = load_antenna_side()
        if job is None:
            return self._last_job
        self._last_job = job
        return job

    def _poll_link(self, host: str, port: int, link: _Link) -> None:
        if port == RADIO_PORT:
            _close_socket(link.sock)
            link.sock = None
            link.misses = self.misses
            link.az = None
            link.el = None
            link.refused = True
            link.detail = "That address belongs to the radio, not a rotator."
            return
        link.refused = False
        try:
            if link.sock is None:
                link.sock = socket.create_connection(
                    (host, port), self.connect_timeout,
                )
            link.sock.settimeout(self.read_timeout)
            link.sock.sendall(_GET_POS)
            az, el = read_get_pos(link.sock, self.read_timeout)
        except Exception:
            _close_socket(link.sock)
            link.sock = None
            link.misses = min(self.misses, link.misses + 1)
            if link.misses >= self.misses:
                link.az = None
                link.el = None
                link.detail = "Heading unknown."
            return
        link.misses = 0
        link.az = az
        link.el = el
        link.detail = ""

    def _close_all(self) -> None:
        for link in self._links.values():
            _close_socket(link.sock)
            link.sock = None
        self._links.clear()
