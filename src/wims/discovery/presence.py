"""WIMS site-server presence (plane E) — zero-memory discovery.

Goals:
  * Operators never type the site server IP.
  * Second site server refuses / demotes when another primary is live.
  * Works when pure multicast fails (Windows VMs, multi-homed hosts).

Announce paths (all ~1 Hz, same JSON body):
  1. Multicast 224.0.0.73:8788 on **every** non-loopback IPv4 NIC
  2. Limited broadcast 255.255.255.255:8788
  3. Subnet directed broadcast (e.g. 192.168.1.255:8788) per NIC

Discover cascade (agent):
  1. UDP listen (multicast join per NIC + broadcast) ~2–3 s
  2. HTTP probe local /24s for TCP :8787 ``/healthz`` with role=wims-site-server

8787 = TCP console only. 8788 = UDP presence only.
"""

from __future__ import annotations

import ipaddress
import json
import random
import select
import socket
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Well-known defaults (wims_networking.md §3.1).
DEFAULT_GROUP = "224.0.0.73"
DEFAULT_PORT = 8788
DEFAULT_HTTP_PORT = 8787
DEFAULT_TTL = 3
KIND = "wims-server"
ROLE = "wims-site-server"
SCHEMA = 1

LIVE_AGE_S = 3.0
STARTUP_LISTEN_S = 2.5
ANNOUNCE_INTERVAL_S = 1.0
HTTP_PROBE_TIMEOUT_S = 0.2
HTTP_PROBE_WORKERS = 64


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def list_lan_ipv4s() -> list[str]:
    """Non-loopback, non-link-local IPv4 addresses on this host."""
    found: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if _usable_lan_ip(ip):
                found.add(ip)
    except OSError:
        pass
    # UDP trick — primary outbound
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if _usable_lan_ip(ip):
                found.add(ip)
        finally:
            s.close()
    except OSError:
        pass
    # Enumerate by connecting to each remote... not available stdlib-wide.
    # On Linux, parse /proc or use netifaces — avoid deps: try common getaddrinfo.
    try:
        # Force resolution of all addresses bound by connecting dummy per iface
        # via hostname -I style: socket.getaddrinfo with AI_ADDRCONFIG
        for info in socket.getaddrinfo(None, 0, socket.AF_INET, socket.SOCK_DGRAM):
            ip = info[4][0]
            if _usable_lan_ip(ip):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def _usable_lan_ip(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return False
    if a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified:
        return False
    # Skip obvious CGNAT/tailscale-only if we have better? Keep Tailscale — remote
    # agents might use it; HTTP probe can find site on LAN separately.
    return True


def _primary_lan_ip(iface: str) -> str:
    """Pick preferred unicast URL host from --iface or best LAN IP."""
    if iface and iface not in ("0.0.0.0", "127.0.0.1", "::"):
        if _usable_lan_ip(iface):
            return iface
    ips = list_lan_ipv4s()
    # Prefer RFC1918 common contest LAN over Tailscale (100.x) / virbr
    def score(ip: str) -> tuple:
        a = ipaddress.IPv4Address(ip)
        # Prefer 192.168.x, then 10.x, then 172.16-31, then other
        priv = a.is_private
        ts = ip.startswith("100.")
        vir = ip.startswith("192.168.122.") or ip.startswith("192.168.123.")
        return (0 if priv and not ts and not vir else 1, ts, vir, ip)

    if ips:
        return sorted(ips, key=score)[0]
    return "127.0.0.1"


def _subnet_broadcast(ip: str, prefix: int = 24) -> str | None:
    try:
        net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        return str(net.broadcast_address)
    except ValueError:
        return None


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
    lan_ips: list[str] | None = None,
) -> dict:
    """Build the JSON object sent as UTF-8 UDP (not the wire bytes)."""
    host = lan_ip or _primary_lan_ip(iface)
    ips = list(lan_ips or list_lan_ipv4s() or [host])
    if host not in ips:
        ips = [host] + ips
    base = f"http://{host}:{int(http_port)}"
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "role": ROLE,
        "instance_id": instance_id,
        "hostname": hostname or _hostname(),
        "lan_ips": ips,
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
        obj = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") != KIND and obj.get("role") != ROLE:
        return None
    if not obj.get("instance_id") and obj.get("kind") == KIND:
        return None
    # HTTP whoami may lack instance_id — still useful for agent links.
    if not obj.get("console_base") and not obj.get("http_port"):
        return None
    base = (obj.get("console_base") or "").rstrip("/")
    if base and not obj.get("urls"):
        obj["urls"] = {
            "operate": f"{base}/",
            "status": f"{base}/status",
            "setup": f"{base}/setup",
            "healthz": f"{base}/healthz",
        }
    if not obj.get("kind"):
        obj["kind"] = KIND
    return obj


def open_listen_socket(
    iface: str = "0.0.0.0",
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
) -> socket.socket:
    """UDP socket: receive broadcast + multicast (join on all LAN IPs)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    try:
        sock.bind(("", int(port)))
    except OSError:
        sock.bind(("0.0.0.0", int(port)))

    join_ips = list_lan_ipv4s()
    if iface and iface not in ("0.0.0.0",) and _usable_lan_ip(iface):
        join_ips = [iface] + [i for i in join_ips if i != iface]
    join_ips = join_ips or ["0.0.0.0"]
    for if_addr in join_ips + ["0.0.0.0"]:
        try:
            mreq = struct.pack(
                "4s4s", socket.inet_aton(group), socket.inet_aton(if_addr))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            continue
    sock.setblocking(False)
    return sock


def open_send_socket(
    iface: str,
    ttl: int = DEFAULT_TTL,
    *,
    multicast_if: str | None = None,
) -> socket.socket:
    """UDP socket for sending beacons (multicast TTL + outbound iface)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    out_if = multicast_if or iface
    if not out_if or out_if in ("0.0.0.0",):
        out_if = _primary_lan_ip(iface or "0.0.0.0")
    if out_if and out_if not in ("0.0.0.0",):
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(out_if),
            )
        except OSError:
            pass
        try:
            sock.bind((out_if, 0))
        except OSError:
            pass
    return sock


def announce_destinations(
    *,
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    iface: str = "0.0.0.0",
) -> list[tuple[str, int, str | None]]:
    """List of (host, port, multicast_if_or_None) to send each beacon to."""
    dests: list[tuple[str, int, str | None]] = []
    seen: set[tuple[str, int, str | None]] = set()

    def add(host: str, p: int, mif: str | None):
        key = (host, p, mif)
        if key not in seen:
            seen.add(key)
            dests.append(key)

    ips = list_lan_ipv4s()
    if iface and _usable_lan_ip(iface) and iface not in ips:
        ips = [iface] + ips
    if not ips:
        ips = [_primary_lan_ip(iface)]

    # Multicast once per NIC (sets MULTICAST_IF to that NIC).
    for ip in ips:
        add(group, port, ip)
    # Global limited broadcast (often reaches Windows VMs when mcast does not).
    add("255.255.255.255", port, ips[0] if ips else None)
    # Directed subnet broadcast per NIC (/24 assumption for contest LAN).
    for ip in ips:
        bcast = _subnet_broadcast(ip, 24)
        if bcast:
            add(bcast, port, ip)
    return dests


def send_beacon_all(
    beacon: dict,
    *,
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    iface: str = "0.0.0.0",
    ttl: int = DEFAULT_TTL,
) -> int:
    """Send beacon on all announce paths. Returns number of successful sends."""
    payload = encode_beacon(beacon)
    ok = 0
    # Group destinations by multicast_if so we open few sockets.
    by_if: dict[str | None, list[tuple[str, int]]] = {}
    for host, p, mif in announce_destinations(group=group, port=port, iface=iface):
        by_if.setdefault(mif, []).append((host, p))
    for mif, hosts in by_if.items():
        try:
            sock = open_send_socket(iface, ttl, multicast_if=mif)
        except OSError:
            continue
        try:
            for host, p in hosts:
                try:
                    sock.sendto(payload, (host, p))
                    ok += 1
                except OSError:
                    continue
        finally:
            sock.close()
    return ok


def listen_for_peers(
    *,
    iface: str = "0.0.0.0",
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    duration_s: float = STARTUP_LISTEN_S,
    exclude_instance_id: str | None = None,
    now: Callable[[], float] | None = None,
) -> list[dict]:
    """Block up to duration_s collecting distinct live peer beacons."""
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
            iid = b.get("instance_id") or b.get("console_base") or "?"
            if exclude_instance_id and b.get("instance_id") == exclude_instance_id:
                continue
            b["_heard_at"] = clock()
            b["_via"] = "udp"
            by_id[str(iid)] = b
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
        via = p.get("_via") or "udp"
        lines.append(f"  peer: {host}  {base}  (id {iid}… via {via})")
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


def _http_probe_one(ip: str, http_port: int, timeout: float) -> dict | None:
    url = f"http://{ip}:{http_port}/healthz"
    try:
        req = Request(url, headers={"User-Agent": "wims-agent-discover/1"})
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(4096)
        obj = json.loads(raw.decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or not obj.get("ok"):
        return None
    # Accept new role field or legacy {"ok":true} only if host serves WIMS pages —
    # prefer role when present.
    role = obj.get("role")
    if role and role != ROLE:
        return None
    if not role and "console_base" not in obj and "urls" not in obj:
        # Legacy healthz: treat as site server if we got ok from :8787
        base = f"http://{ip}:{http_port}"
        obj = {
            "ok": True,
            "role": ROLE,
            "kind": KIND,
            "console_base": base,
            "http_port": http_port,
            "hostname": ip,
            "instance_id": f"http-{ip}",
            "urls": {
                "operate": f"{base}/",
                "status": f"{base}/status",
                "setup": f"{base}/setup",
                "healthz": f"{base}/healthz",
            },
        }
    else:
        # Normalize Host-relative console_base from server
        if not obj.get("console_base"):
            obj["console_base"] = f"http://{ip}:{http_port}"
        if not obj.get("instance_id"):
            obj["instance_id"] = f"http-{ip}"
        if not obj.get("kind"):
            obj["kind"] = KIND
        if not obj.get("urls"):
            base = obj["console_base"].rstrip("/")
            obj["urls"] = {
                "operate": f"{base}/",
                "status": f"{base}/status",
                "setup": f"{base}/setup",
                "healthz": f"{base}/healthz",
            }
    obj["_via"] = "http"
    obj["_heard_at"] = time.time()
    return decode_beacon(encode_beacon(obj)) or obj


def _probe_ip_list(
    ips: list[str],
    http_port: int,
    timeout: float,
) -> dict | None:
    if not ips:
        return None
    with ThreadPoolExecutor(max_workers=HTTP_PROBE_WORKERS) as pool:
        futs = {
            pool.submit(_http_probe_one, ip, http_port, timeout): ip
            for ip in ips
        }
        for fut in as_completed(futs):
            try:
                res = fut.result()
            except Exception:
                continue
            if res:
                return res
    return None


def http_discover_site_server(
    *,
    http_port: int = DEFAULT_HTTP_PORT,
    timeout: float = HTTP_PROBE_TIMEOUT_S,
    extra_ips: list[str] | None = None,
) -> dict | None:
    """Scan local /24s (and extra hints) for a WIMS site server on TCP :http_port.

    Two phases: likely hosts first (.1/.119/…), then full /24. Skips Tailscale
    100.x and libvirt default nets for the full scan (still try preferred only).
    """
    preferred: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()

    def add(ip: str, bucket: list[str], *, allow_loopback: bool = False):
        if ip in seen:
            return
        if allow_loopback and ip.startswith("127."):
            seen.add(ip)
            bucket.append(ip)
            return
        if _usable_lan_ip(ip):
            seen.add(ip)
            bucket.append(ip)

    for tip in extra_ips or []:
        add(tip, preferred, allow_loopback=True)

    for ip in list_lan_ipv4s():
        try:
            net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        except ValueError:
            continue
        base = int(net.network_address)
        for last in (1, 119, 100, 10, 2, 50, 20, 30, 200, 254):
            cand = str(ipaddress.IPv4Address(base + last))
            if ipaddress.IPv4Address(cand) in net:
                add(cand, preferred)
        # Full /24 only on "contest-like" private nets (not Tailscale / typical virbr).
        full = (
            ip.startswith("192.168.")
            or ip.startswith("10.")
            or ip.startswith("172.")
        ) and not (
            ip.startswith("192.168.122.")
            or ip.startswith("192.168.123.")
            or ip.startswith("100.")
        )
        if full:
            for host in net.hosts():
                add(str(host), rest)

    found = _probe_ip_list(preferred, http_port, timeout)
    if found:
        return found
    return _probe_ip_list(rest, http_port, timeout)


def discover_site_server(
    *,
    iface: str = "0.0.0.0",
    group: str = DEFAULT_GROUP,
    port: int = DEFAULT_PORT,
    duration_s: float = STARTUP_LISTEN_S,
    http_port: int = DEFAULT_HTTP_PORT,
    http_fallback: bool = True,
) -> dict | None:
    """Agent discovery cascade: UDP presence, then HTTP subnet probe."""
    peers = listen_for_peers(
        iface=iface, group=group, port=port, duration_s=duration_s)
    if peers:
        peers.sort(key=lambda p: p.get("_heard_at") or 0.0, reverse=True)
        return peers[0]
    if not http_fallback:
        return None
    return http_discover_site_server(http_port=http_port)


def new_instance_id() -> str:
    return uuid.uuid4().hex


@dataclass
class PresenceAnnouncer:
    """Background ~1 Hz multi-path announce + continuous peer watch."""

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
    last_send_ok: int = 0

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
        time.sleep(random.uniform(0.0, 0.35))
        lan_ip = _primary_lan_ip(self.iface)
        lan_ips = list_lan_ipv4s() or [lan_ip]
        listen = open_listen_socket(self.iface, self.group, self.port)
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([listen], [], [], 0.0)
                peers: dict[str, dict] = {}
                while ready:
                    try:
                        data, _ = listen.recvfrom(65535)
                    except OSError:
                        break
                    b = decode_beacon(data)
                    if b and b.get("instance_id") != self.instance_id:
                        peers[b.get("instance_id") or id(b)] = b
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
                    lan_ip=lan_ip,
                    lan_ips=lan_ips,
                )
                self.last_beacon = beacon
                self.last_send_ok = send_beacon_all(
                    beacon,
                    group=self.group,
                    port=self.port,
                    iface=self.iface,
                    ttl=self.ttl,
                )
                end = time.time() + self.interval_s
                while not self._stop.is_set() and time.time() < end:
                    time.sleep(0.05)
        finally:
            try:
                listen.close()
            except OSError:
                pass
