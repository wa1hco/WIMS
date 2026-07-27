# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Experimental GridTracker bridge — merge WSJT-X streams for a remote GT.

WIMS already joins every band port. This module:

1. **Forward** — re-send every raw WSJT-X NetworkMessage datagram to one
   ``(host, port)`` where GridTracker is listening (typically a Linux desktop).
2. **Reverse** — listen on a local UDP port for GT → WSJT control (Reply / Halt /
   FreeText / … from Call Roster click) and unicast the **raw** datagram to the
   instance's last MessageClient ``control_addr`` (ephemeral source of Status/Decode).

Not a logger path. N1MM must keep reading band streams (S_B), not this port.
Experimental: reverse path is pass-through (human click in GT) without the full
browser Work arbiter — decide later how strict to make it.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import Callable

from wims.udp import messages as M

# NetworkMessage types WSJT-X *accepts* from external apps (GT / WIMS).
_CONTROL_TYPES = frozenset({
    M.REPLY,
    M.REPLAY,
    M.HALT_TX,
    M.FREE_TEXT,
    M.LOCATION,
    M.CONFIGURE,
})

# Default ports for experiments (avoid 2237–2243 band table).
# GT listens on FORWARD port; WIMS reverse-bind uses BRIDGE port.
# Same-host: these **must differ** — if both bind 22370, sendto(127.0.0.1:22370)
# loops into WIMS (SO_REUSEADDR) and GT never sees traffic.
DEFAULT_GT_FORWARD_PORT = 22370   # GridTracker Receive UDP
DEFAULT_GT_BRIDGE_PORT = 22371    # WIMS bind / GT Reply return path


def parse_host_port(spec: str, *, default_port: int = DEFAULT_GT_FORWARD_PORT
                    ) -> tuple[str, int]:
    """Parse ``host:port`` or ``host`` (default_port). IPv6 not supported here."""
    s = (spec or "").strip()
    if not s:
        raise ValueError("empty host:port")
    if ":" in s:
        host, _, port_s = s.rpartition(":")
        host = host.strip()
        if not host:
            raise ValueError(f"bad host:port {spec!r}")
        return host, int(port_s)
    return s, int(default_port)


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


def message_type_name(type_num: int | None) -> str:
    names = {
        M.HEARTBEAT: "Heartbeat",
        M.STATUS: "Status",
        M.DECODE: "Decode",
        M.CLEAR: "Clear",
        M.REPLY: "Reply",
        M.QSO_LOGGED: "QSOLogged",
        M.CLOSE: "Close",
        M.REPLAY: "Replay",
        M.HALT_TX: "HaltTx",
        M.FREE_TEXT: "FreeText",
        M.WSPR_DECODE: "WSPRDecode",
        M.LOCATION: "Location",
        M.LOGGED_ADIF: "LoggedADIF",
        M.CONFIGURE: "Configure",
    }
    if type_num is None:
        return "?"
    return names.get(int(type_num), f"type{type_num}")


def peek_message_type(data: bytes) -> int | None:
    """Read NetworkMessage type without full parse (magic + schema + type)."""
    if len(data) < 12:
        return None
    magic, _schema, typ = struct.unpack_from(">III", data, 0)
    if magic != M.MAGIC:
        return None
    return int(typ)


class GridTrackerBridge:
    """UDP forwarder: fleet WSJT-X → GT, and GT control → instance control_addr."""

    def __init__(
        self,
        gt_host: str,
        gt_port: int,
        *,
        bind_host: str = "0.0.0.0",
        bind_port: int = DEFAULT_GT_BRIDGE_PORT,
        control_enabled: bool = True,
        control_addr_for: Callable[[str], list[tuple[str, int]]] | None = None,
        log: Callable[[str], None] | None = None,
    ):
        self.gt_dest = (gt_host, int(gt_port))
        self.bind_host = bind_host
        self.bind_port = int(bind_port)
        self.control_enabled = bool(control_enabled)
        self._control_addr_for = control_addr_for
        self._log = log or (lambda m: print(m, flush=True))
        # Exclusive bind preferred: sharing the GT receive port with SO_REUSEADDR
        # steals or loops same-host traffic. Cross-host, GT and WIMS use different
        # machines so the same port number is fine.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        except OSError:
            pass
        self.sock.bind((bind_host, self.bind_port))
        self.sock.setblocking(False)
        # Separate unicast sender for WSJT control (don't share bind with GT sock).
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.forwarded = 0
        self.control_in = 0
        self.control_fwd = 0
        self.control_drop = 0
        self.last_forward_ts: float | None = None
        self.last_control_ts: float | None = None
        self.last_control_detail: str | None = None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            self._tx.close()
        except OSError:
            pass

    def forward_wsjt(self, data: bytes, *, now: float | None = None) -> None:
        """Re-send one raw WSJT-X datagram to GridTracker."""
        if not data:
            return
        try:
            self.sock.sendto(data, self.gt_dest)
            self.forwarded += 1
            self.last_forward_ts = now if now is not None else time.time()
        except OSError as e:
            # Rate-limit noise: log first failures only occasionally via counter.
            if self.forwarded == 0 or self.forwarded % 200 == 0:
                self._log(f"gt-bridge: forward to {self.gt_dest[0]}:{self.gt_dest[1]} "
                          f"failed: {e}")

    def handle_gt_datagram(self, data: bytes, addr: tuple[str, int],
                           *, now: float | None = None) -> dict:
        """Process one datagram from GT (or anything sending to the bridge port)."""
        now = time.time() if now is None else now
        self.control_in += 1
        self.last_control_ts = now
        typ = peek_message_type(data)
        tname = message_type_name(typ)
        msg = M.parse(data)
        mid = getattr(msg, "id", None) if msg is not None else None
        if mid is None and len(data) >= 16:
            # Best-effort id from full parse failure — skip.
            mid = None

        if not self.control_enabled:
            self.control_drop += 1
            self.last_control_detail = f"ignored {tname} id={mid!r} from {addr} (control off)"
            return {"ok": False, "error": "control_disabled", "type": tname, "id": mid}

        if typ is None or typ not in _CONTROL_TYPES:
            self.control_drop += 1
            self.last_control_detail = (
                f"ignored non-control {tname} id={mid!r} from {addr[0]}:{addr[1]}")
            return {"ok": False, "error": "not_control", "type": tname, "id": mid}

        if not mid:
            self.control_drop += 1
            self.last_control_detail = f"ignored {tname} (no id) from {addr}"
            return {"ok": False, "error": "no_id", "type": tname}

        dests: list[tuple[str, int]] = []
        if self._control_addr_for is not None:
            try:
                dests = list(self._control_addr_for(mid) or [])
            except Exception as e:
                self.control_drop += 1
                self.last_control_detail = f"{tname} {mid!r}: dest lookup failed: {e}"
                self._log(f"gt-bridge: {self.last_control_detail}")
                return {"ok": False, "error": "dest_lookup", "id": mid, "type": tname}

        if not dests:
            self.control_drop += 1
            self.last_control_detail = (
                f"{tname} {mid!r}: no control_addr yet (wait for Status/Decode)")
            self._log(f"gt-bridge: {self.last_control_detail}")
            return {"ok": False, "error": "no_dest", "id": mid, "type": tname}

        sent: list[tuple[str, int]] = []
        last_err: OSError | None = None
        for d in dests:
            try:
                self._tx.sendto(data, d)
                sent.append(d)
            except OSError as e:
                last_err = e
        if not sent:
            self.control_drop += 1
            self.last_control_detail = f"{tname} {mid!r}: send failed: {last_err}"
            self._log(f"gt-bridge: {self.last_control_detail}")
            return {"ok": False, "error": "send_failed", "id": mid, "type": tname,
                    "detail": str(last_err)}

        self.control_fwd += 1
        dest_s = ", ".join(f"{h}:{p}" for h, p in sent)
        self.last_control_detail = (
            f"{tname} {mid!r} from {addr[0]}:{addr[1]} → [{dest_s}]")
        self._log(f"gt-bridge: control {self.last_control_detail}")
        return {"ok": True, "id": mid, "type": tname, "dests": sent}

    def poll_control(self, *, now: float | None = None, max_msgs: int = 32) -> int:
        """Non-blocking drain of GT→bridge datagrams. Returns number handled."""
        n = 0
        for _ in range(max_msgs):
            try:
                data, addr = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            self.handle_gt_datagram(data, addr, now=now)
            n += 1
        return n

    def status_dict(self) -> dict:
        return {
            "gt_dest": f"{self.gt_dest[0]}:{self.gt_dest[1]}",
            "bind": f"{self.bind_host}:{self.bind_port}",
            "control_enabled": self.control_enabled,
            "forwarded": self.forwarded,
            "control_in": self.control_in,
            "control_fwd": self.control_fwd,
            "control_drop": self.control_drop,
            "last_forward_age": (
                None if self.last_forward_ts is None
                else round(time.time() - self.last_forward_ts, 1)),
            "last_control_age": (
                None if self.last_control_ts is None
                else round(time.time() - self.last_control_ts, 1)),
            "last_control": self.last_control_detail,
        }
