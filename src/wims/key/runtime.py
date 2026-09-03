# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Key runtime: live band + plane-A discovery + CTS → type-18 holds.

Fail closed: no holds until ``live_band`` is set. Same-band policy: only
targets from ``InhibitTargetTable.targets_for_band(live_band)``.
Optional ``WIMS_KEY_TARGETS=host:port,…`` overrides discovery (lab).
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from wims.core.bands import band_label
from wims.interlock.inhibit import KeyAgentScheduler
from wims.key.cts import CtsSource
from wims.key.discovery import InhibitTargetTable, stream_port_for_band
from wims.log import GROUP
from wims.udp import messages as M
from wims.udp.sink import open_socket

TICK_S = 0.05


def parse_target_override(text: str) -> list[tuple[str, int]]:
    out = []
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.rpartition(":")
        if not host or not port:
            continue
        out.append((host, int(port)))
    return out


def default_controller_id() -> str:
    env = (os.environ.get("WIMS_KEY_CONTROLLER_ID") or "").strip()
    if env:
        return env
    host = socket.gethostname().split(".")[0] or "wims"
    return f"{host}-key"


@dataclass
class KeyRuntimeState:
    live_band: str | None = None
    keyed: bool = False
    holding: bool = False
    targets: list[tuple[str, int, str]] = field(default_factory=list)  # host,port,id
    discover_port: int | None = None
    discover_error: str | None = None
    cts_error: str | None = None
    last_emit: str = ""
    n_hold_sent: int = 0
    n_release_sent: int = 0
    controller_id: str = ""
    station: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "live_band": self.live_band,
                "keyed": self.keyed,
                "holding": self.holding,
                "targets": list(self.targets),
                "discover_port": self.discover_port,
                "discover_error": self.discover_error,
                "cts_error": self.cts_error,
                "last_emit": self.last_emit,
                "n_hold_sent": self.n_hold_sent,
                "n_release_sent": self.n_release_sent,
                "controller_id": self.controller_id,
                "station": self.station,
            }


class KeyRuntime:
    """Background discover + CTS + emit loops. ``set_live_band`` from RadioInfo."""

    def __init__(
        self,
        *,
        device: str,
        controller_id: str | None = None,
        station: str | None = None,
        group: str = GROUP,
        iface: str = "0.0.0.0",
        target_override: str | None = None,
        get_band: Callable[[], str | None] | None = None,
    ):
        self.device = device
        self.group = group
        self.iface = iface
        self.get_band = get_band
        self.override = parse_target_override(
            target_override if target_override is not None
            else os.environ.get("WIMS_KEY_TARGETS", "")
        )
        cid = controller_id or default_controller_id()
        self.state = KeyRuntimeState(
            controller_id=cid,
            station=station or cid,
        )
        self.table = InhibitTargetTable()
        self.sched = KeyAgentScheduler(cid, station=self.state.station)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_band: str | None = None
        self._last_targets: list[tuple[str, int]] = []

    def set_live_band(self, band: str | None) -> None:
        with self.state._lock:
            self.state.live_band = band

    def start(self) -> None:
        for name, target in (
            ("key-discover", self._discover_loop),
            ("key-sense", self._sense_loop),
        ):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        # Best-effort release if we were holding.
        now = time.monotonic()
        if self.sched.holding:
            self.sched.set_key(False, now)
            # Force hang 0 drain
            self.sched.last_hang_s = 0.0
            self.sched._release_at = now
            for _ in range(5):
                self._emit(self.sched.poll(time.monotonic()), force_targets=self._last_targets)
                time.sleep(0.02)
        for t in self._threads:
            t.join(timeout=1.0)
        try:
            self._tx.close()
        except OSError:
            pass

    def _band(self) -> str | None:
        if self.get_band is not None:
            return self.get_band()
        with self.state._lock:
            return self.state.live_band

    def _current_targets(self, band: str | None, now: float) -> list[tuple[str, int, str]]:
        if self.override:
            return [(h, p, "override") for h, p in self.override]
        if not band:
            return []
        return [(t.host, t.inhibit_port, t.instance_id)
                for t in self.table.targets_for_band(band, now)]

    def _emit(self, datagrams: list[bytes], *, force_targets: list[tuple[str, int]] | None = None) -> None:
        if not datagrams:
            return
        if force_targets is not None:
            dests = force_targets
        else:
            band = self._band()
            now = time.monotonic()
            dests = [(h, p) for h, p, _ in self._current_targets(band, now)]
        if not dests:
            return
        for d in datagrams:
            ttl_zero = False
            try:
                from wims.interlock.inhibit import parse_datagram
                msg = parse_datagram(d)
                ttl_zero = bool(msg and msg["ttl_ms"] == 0)
            except Exception:
                pass
            for host, port in dests:
                try:
                    self._tx.sendto(d, (host, port))
                except OSError as e:
                    with self.state._lock:
                        self.state.last_emit = f"send fail {host}:{port}: {e}"
                    continue
            with self.state._lock:
                if ttl_zero:
                    self.state.n_release_sent += 1
                    self.state.last_emit = f"release → {len(dests)} target(s)"
                else:
                    self.state.n_hold_sent += 1
                    self.state.last_emit = f"hold → {len(dests)} target(s)"

    def _discover_loop(self) -> None:
        sock: socket.socket | None = None
        joined_port: int | None = None
        while not self._stop.is_set():
            band = self._band()
            with self.state._lock:
                self.state.live_band = band
            want = stream_port_for_band(band) if not self.override else None
            if want != joined_port:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    sock = None
                    joined_port = None
                if want is not None:
                    try:
                        sock = open_socket(self.iface, want, self.group)
                        sock.settimeout(0.5)
                        joined_port = want
                        with self.state._lock:
                            self.state.discover_port = want
                            self.state.discover_error = None
                    except OSError as e:
                        with self.state._lock:
                            self.state.discover_error = str(e)
                            self.state.discover_port = None
                        self._stop.wait(1.0)
                        continue
                else:
                    with self.state._lock:
                        self.state.discover_port = None
            now = time.monotonic()
            self.table.sweep(now)
            targets = self._current_targets(band, now)
            with self.state._lock:
                self.state.targets = targets
            if sock is None:
                self._stop.wait(TICK_S)
                continue
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as e:
                with self.state._lock:
                    self.state.discover_error = str(e)
                sock = None
                joined_port = None
                continue
            host = addr[0]
            msg = M.parse(data)
            if isinstance(msg, M.Status):
                b = band_label(msg.dial_frequency or 0)
                self.table.on_status(msg.id or "", b, host, time.monotonic())
            elif isinstance(msg, M.InhibitStatus):
                self.table.on_inhibit_status(
                    msg.id or "",
                    msg.inhibit_port,
                    host,
                    time.monotonic(),
                    inhibited=msg.inhibited,
                    source_station=msg.source_station or "",
                )
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _sense_loop(self) -> None:
        cts = CtsSource.open(self.device)
        with self.state._lock:
            self.state.cts_error = cts.error
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                band = self._band()
                keyed = cts.read()

                # Band change while holding: release previous target set first.
                if band != self._last_band and self.sched.holding and self._last_targets:
                    self._emit(
                        self.sched.force_release(now),
                        force_targets=self._last_targets,
                    )
                    if keyed:
                        self._emit(self.sched.set_key(True, now))
                self._last_band = band
                with self.state._lock:
                    self.state.keyed = keyed
                    self.state.cts_error = cts.error
                    self.state.holding = self.sched.holding

                # Fail closed: no band ⇒ do not assert new holds.
                if not band and not self.override:
                    if self.sched.holding:
                        self._emit(self.sched.set_key(False, now))
                        self._emit(self.sched.poll(now))
                    else:
                        self.sched.set_key(False, now)
                    self._stop.wait(TICK_S)
                    continue

                targets = self._current_targets(band, now)
                self._last_targets = [(h, p) for h, p, _ in targets]
                with self.state._lock:
                    self.state.targets = targets

                if not targets and not self.sched.holding:
                    self.sched.set_key(keyed, now)  # track edges but nowhere to send
                    self._stop.wait(TICK_S)
                    continue

                self._emit(self.sched.set_key(keyed, now))
                self._emit(self.sched.poll(now))
                with self.state._lock:
                    self.state.holding = self.sched.holding
                self._stop.wait(TICK_S)
        finally:
            cts.close()
