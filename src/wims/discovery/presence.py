"""WIMS site-server presence beacon (plane E) — plan networking §3 / MVP.

One site server announces on a well-known multicast address ~1 Hz so:
  * a second server can refuse to start (or demote) with a diagnostic message,
  * seat agents can discover the console URL and show clickable links
    (zero-memory operator path via local agent UI :8790).

Default: group 224.0.0.73 port 8788 UDP (8787 remains TCP HTTP only).
"""

from __future__ import annotations

import json
import os
import random
import select
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

# Well-known defaults (document in wims_networking.md).
DEFAULT_GROUP = "224.0.0.73"
DEFAULT_PORT = 8788
DEFAULT_TTL = 3
KIND = "wims-server"
SCHEMA = 1

# Consider a peer "live" if we heard it within this window.
LIVE_AGE_S = 3.0
# Startup listen window before becoming primary.
STARTUP_LISTEN_S = 2.0
# How often the primary sends.
ANNOUNCE_INTERVAL_S = 1.0


def _primary_lan_ip(iface: str) -> str:
    """Pick a unicast URL host from --iface (not 0.0.0.0 / multicast)."""
    if iface and iface not in ("0.0.0.0", "127.0.0.1", "::"):
        try:
            # Reject multicast / weird
            parts = iface.split(".")
            if len(parts) == 4 and not iface.startswith("224."):
                return iface
        except Exception:
            pass
    # Best-effort outbound interface IP (no packet sent).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        finally:
            s.close()
    except OSError:
        pass
    return "127.0.0.1"


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def build_beacon(
    *,
    instance_id: str,
    http_port: int,
    iface: str,
    hostname: str | None = None,
    started_ts: float | None = None,
    seq: int = 0,
    version: str = "",
    lan_ip: str | None = None,
) -> dict:
    """Build the JSON object sent as UTF-8 UDP (not the wire bytes)."""
    host = lan_ip or _primary_lan_ip(iface)
    base = f"http://{host}:{int(http_port)}"
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "instance_id": instance_id,
        "hostname": hostname or _hostname(),
        "lan_ips": [host],
        "http_port": int(http_port),
        "console_base": base,
        "urls": {
            "operate": f"{base}/",
            "status": f"{base}/status",
            "setup": f"{base}/setup",
            "healthz": f"{base}/healthz",
        },
        "started_ts": float(started_ts if started_ts is not None else time.time()),
        "seq": int(seq),
        "version": version or "",
    }


def encode_beacon(beacon: dict) -> bytes:
    return json.dumps(beacon, separators=(",", ":")).encode("utf-8")


def decode_beacon(data: bytes) -> dict | None:
    """Parse a presence datagram; return dict or None if not our kind."""
    try:
        text = data.decode("utf-8")
        # Allow optional trailing junk / multiple JSON lines — take first object.
        obj = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") != KIND:
        return None
    if not obj.get("instance_id"):
        return None
    if not obj.get("console_base") and not obj.get("http_port"):
        return None
    # Normalize URLs if only console_base present.
    base = (obj.get("console_base") or "").rstrip("/")
    if base and not obj.get("urls"):
        obj["urls"] = {
            "operate": f"{base}/",
            "status": f"{base}/status",
            "setup": f"{base}/setup",
            "healthz": f"{base}/healthz",
        }
    return obj


def open_listen_socket(
    iface: str,
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
) -> socket.socket:
    """UDP socket joined to the presence multicast group."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    # Windows: bind "" ; some stacks prefer 0.0.0.0 explicitly.
    try:
        sock.bind(("", int(port)))
    except OSError:
        sock.bind(("0.0.0.0", int(port)))
    # Join group on the given interface (0.0.0.0 = default).
    if_addr = iface if iface and iface != "0.0.0.0" else "0.0.0.0"
    joined = False
    for candidate in (if_addr, "0.0.0.0"):
        try:
            mreq = struct.pack(
                "4s4s", socket.inet_aton(group), socket.inet_aton(candidate))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            joined = True
            break
        except OSError:
            continue
    if not joined:
        # Still return socket — unicast inject / same-host loop may work.
        pass
    sock.setblocking(False)
    return sock


def open_send_socket(
    iface: str,
    ttl: int = DEFAULT_TTL,
) -> socket.socket:
    """UDP socket for sending beacons (multicast TTL + optional outbound iface)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
    # Hear our own (and same-host) announces — needed for dual-server detect on one PC.
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    except OSError:
        pass
    if iface and iface not in ("0.0.0.0",):
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(iface),
            )
        except OSError:
            pass
    return sock


def listen_for_peers(
    *,
    iface: str,
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    duration_s: float = STARTUP_LISTEN_S,
    exclude_instance_id: str | None = None,
    now: Callable[[], float] | None = None,
) -> list[dict]:
    """Block up to duration_s collecting distinct live peer beacons.

    Returns list of beacon dicts (latest per instance_id), excluding self.
    """
    clock = now or time.time
    sock = open_listen_socket(iface, group, port)
    by_id: dict[str, dict] = {}
    deadline = clock() + max(0.1, duration_s)
    try:
        while clock() < deadline:
            remaining = max(0.0, deadline - clock())
            ready, _, _ = select.select([sock], [], [], min(0.25, remaining))
            if not ready:
                continue
            try:
                data, _addr = sock.recvfrom(65535)
            except OSError:
                continue
            b = decode_beacon(data)
            if not b:
                continue
            iid = b["instance_id"]
            if exclude_instance_id and iid == exclude_instance_id:
                continue
            b["_heard_at"] = clock()
            by_id[iid] = b
    finally:
        sock.close()
    return list(by_id.values())


def format_conflict_message(peers: list[dict], *, self_host: str = "") -> str:
    """Plain-language diagnostic when another site server is already primary."""
    lines = [
        "Another WIMS site server is already running on this LAN.",
        "This process will NOT start a second site server.",
        "",
    ]
    for p in peers:
        base = p.get("console_base") or ""
        host = p.get("hostname") or "?"
        iid = (p.get("instance_id") or "")[:12]
        lines.append(f"  peer: {host}  {base}  (id {iid}…)")
        urls = p.get("urls") or {}
        if urls.get("status"):
            lines.append(f"        Status: {urls['status']}")
    lines += [
        "",
        "Open the peer URL above, or stop that WIMS process if THIS machine",
        "should be the primary site server, then restart here.",
    ]
    if self_host:
        lines.append(f"(this host: {self_host})")
    return "\n".join(lines)


def discover_site_server(
    *,
    iface: str = "0.0.0.0",
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    duration_s: float = STARTUP_LISTEN_S,
) -> dict | None:
    """Agent helper: listen briefly; return newest peer beacon or None."""
    peers = listen_for_peers(
        iface=iface, group=group, port=port, duration_s=duration_s)
    if not peers:
        return None
    # Prefer most recently heard.
    peers.sort(key=lambda p: p.get("_heard_at") or 0.0, reverse=True)
    return peers[0]


@dataclass
class PresenceAnnouncer:
    """Background 1 Hz announce + continuous peer watch for demotion.

    Call ``start()`` after becoming primary. ``stop()`` ends the thread.
    If a *different* live peer is heard, ``on_conflict`` is invoked once and
    announcing stops (MVP demote).
    """

    iface: str
    http_port: int
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    group: str = DEFAULT_GROUP
    port: int = DEFAULT_PORT
    ttl: int = DEFAULT_TTL
    hostname: str | None = None
    version: str = ""
    interval_s: float = ANNOUNCE_INTERVAL_S
    on_conflict: Callable[[list[dict]], None] | None = None

    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _seq: int = field(default=0, repr=False)
    started_ts: float = field(default_factory=time.time)
    demoted: bool = False
    last_beacon: dict | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.demoted = False
        self._thread = threading.Thread(
            target=self._run, name="wims-presence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        # Small random jitter so two simultaneous starts are less likely both-primary.
        time.sleep(random.uniform(0.0, 0.35))
        send = open_send_socket(self.iface, self.ttl)
        listen = open_listen_socket(self.iface, self.group, self.port)
        try:
            while not self._stop.is_set():
                # Watch for other primaries.
                ready, _, _ = select.select([listen], [], [], 0.0)
                peers: dict[str, dict] = {}
                while ready:
                    try:
                        data, _ = listen.recvfrom(65535)
                    except OSError:
                        break
                    b = decode_beacon(data)
                    if b and b["instance_id"] != self.instance_id:
                        peers[b["instance_id"]] = b
                    ready, _, _ = select.select([listen], [], [], 0.0)
                if peers and not self.demoted:
                    self.demoted = True
                    if self.on_conflict:
                        try:
                            self.on_conflict(list(peers.values()))
                        except Exception:
                            pass
                    break

                self._seq += 1
                beacon = build_beacon(
                    instance_id=self.instance_id,
                    http_port=self.http_port,
                    iface=self.iface,
                    hostname=self.hostname,
                    started_ts=self.started_ts,
                    seq=self._seq,
                    version=self.version,
                )
                self.last_beacon = beacon
                try:
                    send.sendto(
                        encode_beacon(beacon),
                        (self.group, int(self.port)),
                    )
                except OSError:
                    pass
                # Sleep in slices so stop() is responsive.
                end = time.time() + self.interval_s
                while not self._stop.is_set() and time.time() < end:
                    time.sleep(0.05)
        finally:
            try:
                send.close()
            except OSError:
                pass
            try:
                listen.close()
            except OSError:
                pass


def new_instance_id() -> str:
    return uuid.uuid4().hex
