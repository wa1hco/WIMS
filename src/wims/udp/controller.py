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
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    return s


class TxController:
    """Sends control datagrams. `sock` is a UDP socket; `dest` is (group, port)."""

    def __init__(self, sock: socket.socket, dest: tuple[str, int]):
        self.sock = sock
        self.dest = dest

    def reply(self, instance_id: str, decode: M.Decode, *, modifiers: int = 0) -> bytes:
        """Tell `instance_id` to start a QSO with the station in `decode` (a CQ/QRZ)."""
        raw = E.build_reply(
            instance_id, time_ms=decode.time_ms, snr=decode.snr,
            delta_time=decode.delta_time, delta_frequency=decode.delta_frequency,
            message=decode.message or "", mode=decode.mode or "~",
            low_confidence=decode.low_confidence, modifiers=modifiers,
        )
        self.sock.sendto(raw, self.dest)
        return raw

    def halt(self, instance_id: str, *, auto_only: bool = False) -> bytes:
        """Stop `instance_id` transmitting (immediately, or just unset Auto)."""
        raw = E.build_halt_tx(instance_id, auto_only=auto_only)
        self.sock.sendto(raw, self.dest)
        return raw

    @staticmethod
    def for_group(group: str, port: int, iface: str = "0.0.0.0", ttl: int = 1) -> "TxController":
        return TxController(open_send_socket(iface, ttl), (group, port))
