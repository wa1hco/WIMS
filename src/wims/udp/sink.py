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

"""Raw UDP capture sink for WSJT-X (and N1MM) datagrams — plan §1.1 / §3.1.

Receive-only: this never transmits and never touches the running
WSJT-X -> GridTracker -> N1MM chain. It binds a UDP port (optionally joining a
multicast group), writes every datagram to a timestamped JSONL capture file under
captures/, and prints a one-line summary per packet. WSJT-X datagrams are peeked
just far enough to label the message type, as proof the parser spec is right.

Run (from the repo root):
    python src/wims/udp/sink.py --port 2237
    python src/wims/udp/sink.py --port 2237 --multicast 239.255.0.0

Find the address/port in WSJT-X: Settings (F2) -> Reporting tab -> "UDP Server".
If that address is multicast (224.x-239.x) pass it via --multicast; if it is a
plain/loopback address WSJT-X is unicasting (likely to GridTracker, which relays
to N1MM) -- in that case prefer a passive Wireshark capture so you don't contend
for the port.

The capture file (captures/wsjtx-YYYYMMDD-HHMMSS.jsonl) doubles as parser test
fixtures and the test-bed replay library (§5.1).
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from datetime import datetime
from pathlib import Path

# WSJT-X NetworkMessage header: big-endian quint32 magic, schema, type.
WSJTX_MAGIC = 0xADBCCBDA

# Outbound message types we care about (NetworkMessage.hpp).
WSJTX_TYPES = {
    0: "Heartbeat",
    1: "Status",
    2: "Decode",
    3: "Clear",
    5: "QSOLogged",
    6: "Close",
    10: "WSPRDecode",
    12: "LoggedADIF",
}


def peek_wsjtx(data: bytes) -> dict | None:
    """Decode just the WSJT-X header (magic, schema, type, instance id)."""
    if len(data) < 12:
        return None
    magic, schema, mtype = struct.unpack_from(">III", data, 0)
    if magic != WSJTX_MAGIC:
        return None
    info: dict = {"schema": schema, "type": mtype, "type_name": WSJTX_TYPES.get(mtype, "?")}
    # The id is a QString: quint32 byte-length then UTF-8 (0xFFFFFFFF == null).
    off = 12
    if len(data) >= off + 4:
        (n,) = struct.unpack_from(">I", data, off)
        if n != 0xFFFFFFFF and off + 4 + n <= len(data):
            info["id"] = data[off + 4 : off + 4 + n].decode("utf-8", "replace")
    return info


def _join_iface_ips(host: str) -> list[str]:
    """Iface addresses for IP_ADD_MEMBERSHIP, primary first.

    Join every LAN IP (plus 0.0.0.0). A single-NIC join is why DHCP/link
    flap or the 'wrong' primary silently drops WSJT-X multicast.
    """
    ips: list[str] = []
    if host and host not in ("0.0.0.0", "::", ""):
        try:
            import ipaddress
            ip = ipaddress.ip_address(host.split("%", 1)[0])
            if ip.version == 4 and not ip.is_unspecified:
                ips.append(str(ip))
        except ValueError:
            pass
    try:
        from wims.discovery.presence import _primary_lan_ip, list_lan_ipv4s
        primary = _primary_lan_ip(host or "0.0.0.0")
        if primary and primary not in ips:
            ips.append(primary)
        for ip in list_lan_ipv4s():
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if "0.0.0.0" not in ips:
        ips.append("0.0.0.0")
    return ips or ["0.0.0.0"]


def _join_iface_ip(host: str) -> str:
    """Interface address for IP_ADD_MEMBERSHIP. ``0.0.0.0`` is not a valid join
    iface on Linux — pick the primary contest LAN IP so VMs on the same /24 are heard.
    """
    return _join_iface_ips(host)[0]


def _mreq(group: str, if_addr: str) -> bytes:
    return struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(if_addr))


def join_multicast(sock: socket.socket, group: str, host: str = "0.0.0.0") -> list[str]:
    """Join ``group`` on every usable iface. Returns ifaces that succeeded."""
    joined: list[str] = []
    for if_addr in _join_iface_ips(host):
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            _mreq(group, if_addr))
            joined.append(if_addr)
        except OSError:
            continue
    return joined


def rejoin_multicast(sock: socket.socket, group: str, host: str = "0.0.0.0") -> list[str]:
    """Refresh IGMP membership: DROP then ADD on each iface.

    Unsolicited re-join is what a switch with IGMP snooping (no querier)
    needs after it pruned the group. ADD-only fails with 'already a member'.
    """
    joined: list[str] = []
    drop = getattr(socket, "IP_DROP_MEMBERSHIP", None)
    for if_addr in _join_iface_ips(host):
        try:
            mreq = _mreq(group, if_addr)
        except OSError:
            # inet_aton EINVAL (22) if if_addr is IPv6 / junk.
            continue
        if drop is not None:
            try:
                sock.setsockopt(socket.IPPROTO_IP, drop, mreq)
            except OSError:
                pass
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            joined.append(if_addr)
        except OSError:
            continue
    return joined


def open_socket(host: str, port: int, multicast: str | None) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_host = multicast if multicast else host
    # On Windows a multicast member binds the group address (or "") to receive it.
    sock.bind(("" if multicast else bind_host, port))
    if multicast:
        joined = join_multicast(sock, multicast, host)
        if not joined:
            sock.close()
            raise OSError(f"IP_ADD_MEMBERSHIP {multicast} failed on all interfaces")
    return sock


def main() -> None:
    ap = argparse.ArgumentParser(description="Raw UDP capture sink for WSJT-X/N1MM datagrams.")
    ap.add_argument("--host", default="0.0.0.0", help="local interface to bind / multicast (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=2237, help="UDP port (WSJT-X default 2237)")
    ap.add_argument("--multicast", default=None, help="multicast group to join, if WSJT-X is multicasting")
    ap.add_argument("--out", default="captures", help="output directory (default captures/)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"wsjtx-{stamp}.jsonl"

    sock = open_socket(args.host, args.port, args.multicast)
    where = f"{args.multicast} (multicast)" if args.multicast else args.host
    print(f"listening on {where}:{args.port}  ->  {out_path}")
    print("Ctrl-C to stop.\n")

    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                ts = time.time()
                rec = {
                    "ts": ts,
                    "src_ip": addr[0],
                    "src_port": addr[1],
                    "len": len(data),
                    "hex": data.hex(),
                }
                wsjtx = peek_wsjtx(data)
                if wsjtx:
                    rec["wsjtx"] = wsjtx
                f.write(json.dumps(rec) + "\n")
                f.flush()
                count += 1
                label = (
                    f"{wsjtx['type_name']}({wsjtx['type']}) id={wsjtx.get('id', '?')}"
                    if wsjtx
                    else "non-WSJT-X"
                )
                print(f"[{count:5d}] {addr[0]}:{addr[1]:<5d} {len(data):4d}B  {label}")
        except KeyboardInterrupt:
            print(f"\nstopped — {count} datagrams written to {out_path}")


if __name__ == "__main__":
    main()
