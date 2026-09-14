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
so `reply()` takes the parsed `Decode` and mirrors its fields.

**Multi-host note:** Status/Decode often arrive via multicast, but control (Reply)
must be **unicast to the packet source IP:port** — WSJT-X MessageClient binds an
ephemeral port and only receives there (not on the UDP Server port). Typical
dest list: ``[(vm_ip, ephemeral), (224.x.x.x, 2237)]`` — unicast socket for hosts,
multicast socket for groups.

Lease/arbiter gating lives above this (§3.4/§4.5) — this layer just sends.
"""

from __future__ import annotations

import ipaddress
import socket
import struct

from wims.udp import encode as E
from wims.udp import messages as M


def _is_multicast(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(host or "").split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is None:
            return False
        ip = mapped
    return ip.version == 4 and ip.is_multicast


def _v4_mcast_dest(host, port) -> tuple[str, int] | None:
    """IPv4 multicast dest for the AF_INET mcast socket (else skip)."""
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        return None
    if port_i <= 0 or port_i > 65535:
        return None
    h = str(host or "").strip()
    if "%" in h:
        h = h.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if ip.version == 6:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is None:
            return None
        ip = mapped
    if ip.version != 4 or not ip.is_multicast:
        return None
    return (str(ip), port_i)


def v4_unicast_dest(host, port) -> tuple[str, int] | None:
    """Reply/Halt dest that an AF_INET socket can sendto (else Windows err 22).

    Accepts IPv4, IPv4-mapped IPv6 (``::ffff:192.168.x.x``), and ``%zone``
    suffixes. Drops real IPv6, multicast, and unspecified.
    """
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        return None
    if port_i <= 0 or port_i > 65535:
        return None
    h = str(host or "").strip()
    if "%" in h:
        h = h.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if ip.version == 6:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is None:
            return None
        ip = mapped
    if ip.version != 4:
        return None
    if ip.is_unspecified or ip.is_multicast:
        return None
    return (str(ip), port_i)


def open_send_socket(iface: str = "0.0.0.0", ttl: int = 3) -> socket.socket:
    """Multicast send socket. ``iface`` should be a real LAN IP when commanding
    remote WSJT-X (VMs); 0.0.0.0 leaves interface selection to the kernel.

    Default TTL=3 matches contest-LAN practice (cross-switch multi-host)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
    if iface and iface not in ("0.0.0.0", "::"):
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                         socket.inet_aton(iface))
        except OSError:
            pass
    return s


def open_unicast_socket(iface: str = "0.0.0.0") -> socket.socket:
    """AF_INET UDP socket for MessageClient unicast. Bind to ``iface`` when it is
    a real LAN IPv4 so dual-stack / extra NICs cannot pick an IPv6 path."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if iface and iface not in ("0.0.0.0", "::"):
        try:
            ipaddress.IPv4Address(iface)
            s.bind((iface, 0))
        except (OSError, ValueError):
            pass
    return s


class TxController:
    """Sends control datagrams to one or more (host, port) destinations.

    Holds a **unicast** socket always, and optionally a **multicast** socket for
    group destinations. Multi-host Work should list the instance source IP first.
    """

    def __init__(self, sock: socket.socket, dest: tuple[str, int],
                 *, mcast_sock: socket.socket | None = None,
                 iface: str = "0.0.0.0", ttl: int = 3):
        self.sock = sock              # unicast (and fallback)
        self.mcast_sock = mcast_sock  # optional dedicated multicast sender
        self.dest = dest
        self._iface = iface or "0.0.0.0"
        self._ttl = int(ttl)

    def _sock_for(self, host: str) -> socket.socket:
        if _is_multicast(host) and self.mcast_sock is not None:
            return self.mcast_sock
        return self.sock

    def _refresh_socks(self) -> None:
        """Replace send sockets after EINVAL / stale handle (hours-long contest)."""
        iface = self._iface
        ttl = self._ttl
        old_m = self.mcast_sock
        if old_m is not None:
            try:
                ttl = int(old_m.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL) or 3)
            except OSError:
                pass
            try:
                old_m.close()
            except OSError:
                pass
            self.mcast_sock = open_send_socket(iface, ttl)
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = open_unicast_socket(self._iface)

    def _send_all(self, raw: bytes, dests: list[tuple[str, int]] | None) -> list[tuple[str, int]]:
        """Send to each destination; return those that did not raise.

        ``dests is None`` (legacy Reply/Halt with no override) uses ``self.dest``.
        An explicit empty list means "nowhere" — never fall back to the multicast
        group (that sendto is Windows errno 22 / 10022 on some stacks).
        """
        if dests is None:
            targets = [self.dest]
        else:
            targets = list(dests)
        seen: set[tuple[str, int]] = set()
        ordered: list[tuple[str, int]] = []
        for d in targets:
            try:
                host, port = d[0], d[1]
            except (TypeError, ValueError, IndexError):
                continue
            key = _v4_mcast_dest(host, port)
            if key is not None:
                if self.mcast_sock is None:
                    continue
            else:
                key = v4_unicast_dest(host, port)
                if key is None:
                    continue
            if key not in seen:
                seen.add(key)
                ordered.append(key)
        ok: list[tuple[str, int]] = []
        last_err: OSError | None = None
        refreshed = False
        for d in ordered:
            try:
                self._sock_for(d[0]).sendto(raw, d)
                ok.append(d)
                continue
            except OSError as e:
                last_err = e
            # WinError 10022 / errno 22 / 10038: stale UDP socket or bad multicast IF.
            if not refreshed:
                refreshed = True
                try:
                    self._refresh_socks()
                    self._sock_for(d[0]).sendto(raw, d)
                    ok.append(d)
                    last_err = None
                    continue
                except OSError as e2:
                    last_err = e2
                except Exception:
                    pass
        if not ok:
            if last_err is not None:
                raise OSError(
                    f"UDP send failed to {ordered}: {last_err}"
                ) from last_err
            raise OSError("no valid UDP dest for Work/Halt (missing control port)")
        return ok

    def reply(self, instance_id: str, decode: M.Decode, *, modifiers: int = 0,
              dests: list[tuple[str, int]] | None = None) -> bytes:
        """Tell `instance_id` to start a QSO with the station in `decode` (a CQ/QRZ).

        Echoes the prior Decode fields exactly (including schema). WSJT-X will not
        enable TX / fill DX unless the Reply matches a decode it still holds,
        Accept UDP is on, and the datagram reaches MessageClient's *ephemeral*
        control port (the source port of Status/Decode packets).
        """
        schema = int(getattr(decode, "schema", None) or 2)
        raw = E.build_reply(
            instance_id, time_ms=decode.time_ms, snr=decode.snr,
            delta_time=decode.delta_time, delta_frequency=decode.delta_frequency,
            message=decode.message or "", mode=decode.mode or "~",
            low_confidence=bool(getattr(decode, "low_confidence", False)),
            modifiers=modifiers, schema=schema,
        )
        self._send_all(raw, dests)
        return raw

    def halt(self, instance_id: str, *, auto_only: bool = False,
             dests: list[tuple[str, int]] | None = None) -> bytes:
        """Stop `instance_id` transmitting (immediately, or just unset Auto)."""
        raw = E.build_halt_tx(instance_id, auto_only=auto_only)
        self._send_all(raw, dests)
        return raw

    def replay(self, instance_id: str, *, dests: list[tuple[str, int]] | None = None,
               schema: int = 2) -> bytes:
        """Ask `instance_id` to replay decodes and emit Status (dial/band)."""
        raw = E.build_replay(instance_id, schema=schema)
        self._send_all(raw, dests)
        return raw

    def configure(self, instance_id: str, *, dx_call: str, dx_grid: str = "",
                  rx_df: int | None = None, generate_messages: bool = True,
                  mode: str = "", schema: int = 2,
                  dests: list[tuple[str, int]] | None = None) -> bytes:
        """Fill DX Call/Grid (and optionally gen Std Msgs). Does not Enable Tx."""
        raw = E.build_configure(
            instance_id, mode=mode, rx_df=rx_df,
            dx_call=dx_call or "", dx_grid=dx_grid or "",
            generate_messages=generate_messages, schema=schema,
        )
        self._send_all(raw, dests)
        return raw

    @staticmethod
    def for_group(group: str, port: int, iface: str = "0.0.0.0", ttl: int = 3) -> "TxController":
        """Default dest = multicast group; also keeps a unicast socket for per-host Reply."""
        return TxController(
            open_unicast_socket(iface),
            (group, port),
            mcast_sock=open_send_socket(iface, ttl),
            iface=iface, ttl=ttl,
        )

    @staticmethod
    def for_unicast(host: str, port: int) -> "TxController":
        """Controller that sends to a plain (unicast/loopback) WSJT-X listener, e.g.
        the solo single-PC case where WSJT-X's UDP Server is 127.0.0.1:2237."""
        return TxController(open_unicast_socket(), (host, port))
