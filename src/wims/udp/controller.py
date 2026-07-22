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

"""UDP controller / sender — issue Reply / Halt Tx to a WSJT-X instance (plan §3.2).

The actuator side: turn an arbiter grant + a chosen decode into the actual UDP
command. A Reply must exactly echo a prior CQ/QRZ decode for WSJT-X to act on it,
so `reply()` takes the parsed `Decode` and mirrors its fields. Sends to the same
multicast group WSJT-X listens on; addressed per-instance by the WSJT-X `id`.

Lease/arbiter gating lives above this (§3.4/§4.5) — this layer just sends.
"""

from __future__ import annotations

import socket
import struct

from wims.udp import encode as E
from wims.udp import messages as M


def open_send_socket(iface: str = "0.0.0.0", ttl: int = 1) -> socket.socket:
    """Multicast send socket. ``iface`` should be a real LAN IP when commanding
    remote WSJT-X (VMs); 0.0.0.0 leaves interface selection to the kernel."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
    if iface and iface not in ("0.0.0.0", "::"):
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                         socket.inet_aton(iface))
        except OSError:
            pass
    return s


def open_unicast_socket() -> socket.socket:
    """A bare UDP socket for sending to a plain (unicast/loopback) WSJT-X listener —
    no multicast options. Used when WSJT-X's 'UDP Server' is an ordinary address such
    as 127.0.0.1 (the common single-PC / solo case) rather than a multicast group."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class TxController:
    """Sends control datagrams. `sock` is a UDP socket; `dest` is default (host, port).

    Multi-host: callers should pass ``dests`` with the instance's LAN IP first
    (unicast), then the multicast group — many Windows WSJT-X setups only act on
    unicast Reply even when Status/Decode leave via multicast.
    """

    def __init__(self, sock: socket.socket, dest: tuple[str, int]):
        self.sock = sock
        self.dest = dest

    def _send_all(self, raw: bytes, dests: list[tuple[str, int]] | None) -> list[tuple[str, int]]:
        """Send to each destination; return those that did not raise."""
        targets = list(dests) if dests else [self.dest]
        # De-dupe while preserving order
        seen: set[tuple[str, int]] = set()
        ordered: list[tuple[str, int]] = []
        for d in targets:
            if d not in seen:
                seen.add(d)
                ordered.append(d)
        ok: list[tuple[str, int]] = []
        last_err: OSError | None = None
        for d in ordered:
            try:
                self.sock.sendto(raw, d)
                ok.append(d)
            except OSError as e:
                last_err = e
        if not ok and last_err is not None:
            raise last_err
        return ok

    def reply(self, instance_id: str, decode: M.Decode, *, modifiers: int = 0,
              dests: list[tuple[str, int]] | None = None) -> bytes:
        """Tell `instance_id` to start a QSO with the station in `decode` (a CQ/QRZ).

        Echoes the prior Decode fields exactly — WSJT-X will not enable TX / fill DX
        unless the Reply matches a decode it still holds and Accept UDP is on.
        """
        raw = E.build_reply(
            instance_id, time_ms=decode.time_ms, snr=decode.snr,
            delta_time=decode.delta_time, delta_frequency=decode.delta_frequency,
            message=decode.message or "", mode=decode.mode or "~",
            low_confidence=decode.low_confidence, modifiers=modifiers,
        )
        self._send_all(raw, dests)
        return raw

    def halt(self, instance_id: str, *, auto_only: bool = False,
             dests: list[tuple[str, int]] | None = None) -> bytes:
        """Stop `instance_id` transmitting (immediately, or just unset Auto)."""
        raw = E.build_halt_tx(instance_id, auto_only=auto_only)
        self._send_all(raw, dests)
        return raw

    @staticmethod
    def for_group(group: str, port: int, iface: str = "0.0.0.0", ttl: int = 1) -> "TxController":
        return TxController(open_send_socket(iface, ttl), (group, port))

    @staticmethod
    def for_unicast(host: str, port: int) -> "TxController":
        """Controller that sends to a plain (unicast/loopback) WSJT-X listener, e.g.
        the solo single-PC case where WSJT-X's UDP Server is 127.0.0.1:2237."""
        return TxController(open_unicast_socket(), (host, port))
