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

"""Passive fleet discovery + health + expected-vs-actual (plan §3.15 / §2.5).

WIMS already joins the WSJT-X multicast, so it can enumerate the whole fleet for
free: which instances are alive, on what band, last decode, plus health and
config problems - the cross-vehicle visibility that currently lives only in chat
(see Deployment context). Feed it parsed messages with a timestamp + source IP;
ask it for a status table or a diff against the expected fleet.

Time is injected (``now``) so it is testable and replayable.
"""

from __future__ import annotations

import ipaddress
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Allow running directly as a script (python src/wims/discovery/fleet.py).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wims.core.bands import band_label, band_label_mhz  # noqa: E402
from wims.udp import messages as M  # noqa: E402

PULSE = 15  # WSJT-X heartbeat period (s); health thresholds are multiples of it.

# After this long with no UDP, drop the node from the fleet table (and UI).
# STALE at 2*PULSE, DEAD at 4*PULSE; prune a bit after DEAD so the operator
# still sees "DEAD" briefly when someone kills WSJT-X.
DEFAULT_PRUNE_AFTER = 8 * PULSE   # 120 s

# N1MM external-broadcast root tags we treat as presence-bearing (lowercased).
_N1MM_ROOTS = {"contactinfo", "radioinfo", "appinfo", "dynamicresults",
               "spot", "lookupinfo", "contactdelete", "contactreplace"}


@dataclass
class NodeState:
    """Live state of one WSJT-X instance, keyed by its UDP id."""

    id: str
    # source IP -> last time a datagram arrived from that IP (for collision + host)
    host_seen: dict[str, float] = field(default_factory=dict)
    # Per-host band from Status — two VMs with the same UDP id must not look like QSY.
    band_by_host: dict[str, str] = field(default_factory=dict)
    last_status_host: str | None = None
    # Last UDP *source* (ip, port) from recvfrom — MessageClient binds an
    # ephemeral port and only receives Reply/Halt there (not on UDP Server port).
    control_addr: tuple[str, int] | None = None
    version: str | None = None
    band: str | None = None
    mode: str | None = None
    dial_hz: int = 0
    de_grid: str | None = None      # this instance's own grid (Status.de_grid) — az reference
    de_call: str | None = None      # our call on this instance (Status.de_call) — calling-us
    dx_call: str | None = None      # WSJT-X DX Call box (Status.dx_call)
    tx_enabled: bool = False        # Enable Tx (armed for dx_call even if not keying)
    transmitting: bool = False
    decoding: bool = False
    config_name: str | None = None
    last_heartbeat: float | None = None
    last_status: float | None = None
    last_decode: float | None = None
    decode_count: int = 0
    decode_times: list[float] = field(default_factory=list)
    first_seen: float = 0.0

    def note_host(self, src_ip: str | None, now: float,
                  src_port: int | None = None) -> None:
        if src_ip:
            self.host_seen[src_ip] = now
            if src_port is not None and int(src_port) > 0:
                self.control_addr = (src_ip, int(src_port))

    def hosts_recent(self, now: float, window: float = 4 * PULSE) -> set[str]:
        """IPs that still look live for this id (drops stale sources so a move
        desktop→VM does not sticky-flag id_collision forever)."""
        return {ip for ip, t in self.host_seen.items() if now - t <= window}

    def decodes_per_period(self, now: float, window: float = 60.0, pulse: int = PULSE) -> float:
        """Average decodes per TX/RX period over the last `window` seconds — the
        band-activity number that means something on an occasional glance (a
        cumulative total does not)."""
        recent = sum(1 for t in self.decode_times if t > now - window)
        return recent / max(1.0, window / pulse)

    def last_seen(self) -> float | None:
        ts = [t for t in (self.last_heartbeat, self.last_status, self.last_decode)
              if t is not None]
        return max(ts) if ts else None

    def health(self, now: float, pulse: int = PULSE) -> str:
        ls = self.last_seen()
        if ls is None:
            return "UNKNOWN"
        age = now - ls
        if age <= 2 * pulse:
            return "ALIVE"
        if age <= 4 * pulse:
            return "STALE"
        return "DEAD"

    def is_quiet(self, now: float, quiet_after: int = 4 * PULSE) -> bool:
        """Alive but not decoding - band dead, wrong freq, or RX problem."""
        if self.health(now) != "ALIVE":
            return False
        if self.last_decode is None:
            return True
        return (now - self.last_decode) > quiet_after

    @property
    def hosts(self) -> set[str]:
        """All source IPs ever seen (tests / debug). Prefer hosts_recent(now)."""
        return set(self.host_seen)

    @property
    def host(self) -> str | None:
        """Most recently heard source IP for this id."""
        if not self.host_seen:
            return None
        return max(self.host_seen.items(), key=lambda kv: kv[1])[0]

    def id_collision_at(self, now: float, window: float = 4 * PULSE) -> bool:
        # Same WSJT-X id from >1 *currently live* host = ambiguous control/logging.
        return len(self.hosts_recent(now, window)) > 1

    @property
    def id_collision(self) -> bool:
        """Backward-compatible: any multi-host history (prefer id_collision_at(now))."""
        return len(self.host_seen) > 1


@dataclass
class LoggerNode:
    """An N1MM instance seen on the network, identified by station name. Presence is
    established by ANY N1MM broadcast — `<RadioInfo>`/`<AppInfo>` beacons arrive
    periodically (no QSO needed), so `last_seen` is real liveness usable for setup
    verification; `last_qso` (from `<contactinfo>`) is specifically the last logged QSO.

    One physical PC often emits both ``StationName`` and Windows ``NetBiosName``;
    we merge those aliases by source IP so the console shows one logger per host.
    """

    id: str                      # preferred: N1MM StationName
    kind: str = "N1MM"
    hosts: set[str] = field(default_factory=set)
    host_seen: dict[str, float] = field(default_factory=dict)  # IP -> last packet
    aliases: set[str] = field(default_factory=set)  # NetBIOS / prior ids merged here
    last_seen: float | None = None   # any N1MM broadcast (presence / liveness)
    last_qso: float | None = None    # last <contactinfo> (a logged QSO)
    qso_count: int = 0
    last_call: str | None = None
    last_band: str | None = None
    mycall: str | None = None        # the station's own call (RadioInfo/contactinfo)
    first_seen: float = 0.0

    @property
    def host(self) -> str | None:
        """Most recently heard source IP."""
        if self.host_seen:
            return max(self.host_seen.items(), key=lambda kv: kv[1])[0]
        return sorted(self.hosts)[0] if self.hosts else None


@dataclass
class ExpectedInstance:
    """One declared instance in the expected fleet (a slice of the §3.14 profile)."""

    id: str
    band: str | None = None
    host: str | None = None
    vehicle: str | None = None


@dataclass
class Discrepancy:
    kind: str     # missing | dead | unexpected | band-mismatch | id-collision | quiet
    severity: str  # "error" | "warn"
    detail: str


class FleetTracker:
    def __init__(self, pulse: int = PULSE):
        self.pulse = pulse
        self.nodes: dict[str, NodeState] = {}
        self.loggers: dict[str, LoggerNode] = {}

    @staticmethod
    def _is_ip_like(s: str) -> bool:
        try:
            ipaddress.ip_address(s)
            return True
        except ValueError:
            return False

    def _absorb_logger(self, keep: "LoggerNode", other: "LoggerNode") -> None:
        """Fold `other` into `keep` (same physical host / process)."""
        if keep is other:
            return
        keep.hosts |= other.hosts
        keep.host_seen.update(other.host_seen)
        keep.aliases.add(other.id)
        keep.aliases |= set(other.aliases or [])
        if other.mycall and not keep.mycall:
            keep.mycall = other.mycall
        if other.last_seen is not None and (
                keep.last_seen is None or other.last_seen >= keep.last_seen):
            keep.last_seen = other.last_seen
        # Prefer the richer QSO stats (don't sum — that double-counts after re-merge).
        if other.last_qso is not None and (
                keep.last_qso is None or other.last_qso >= keep.last_qso):
            keep.last_qso = other.last_qso
            keep.last_call = other.last_call or keep.last_call
            keep.last_band = other.last_band or keep.last_band
        keep.qso_count = max(keep.qso_count, other.qso_count)
        if other.first_seen and (
                not keep.first_seen or other.first_seen < keep.first_seen):
            keep.first_seen = other.first_seen

    def consolidate_loggers(self) -> None:
        """Collapse multiple logger rows that share a source IP into one.

        Handles StationName vs NetBIOS vs bare-IP keys for the same N1MM PC.
        Preferred id: StationName-like (not an IP address).
        """
        # ip -> set of logger ids claiming that host
        by_ip: dict[str, set[str]] = {}
        for lid, lg in self.loggers.items():
            ips = set(lg.hosts) | set(lg.host_seen)
            if self._is_ip_like(lid):
                ips.add(lid)
            for ip in ips:
                by_ip.setdefault(ip, set()).add(lid)

        for ip, lids in by_ip.items():
            present = [self.loggers[i] for i in lids if i in self.loggers]
            if len(present) < 2:
                continue
            # Prefer non-IP id; among those, prefer the one with StationName style
            # (already preferred when created) then oldest first_seen.
            present.sort(key=lambda lg: (
                1 if self._is_ip_like(lg.id) else 0,
                lg.first_seen or 0.0,
                lg.id,
            ))
            keep = present[0]
            for other in present[1:]:
                if other.id not in self.loggers:
                    continue
                self._absorb_logger(keep, other)
                del self.loggers[other.id]
            # Ensure keep is keyed by keep.id
            if keep.id not in self.loggers:
                self.loggers[keep.id] = keep

    def _logger_for_n1mm(self, *, station: str, netbios: str, src_ip: str | None,
                         now: float, app: str) -> "LoggerNode":
        """Resolve one LoggerNode for this packet — merge StationName / NetBIOS / IP."""
        preferred = station or netbios or (src_ip or "?")
        # Prefer an existing logger on this host over creating preferred-as-IP.
        node = None
        if preferred in self.loggers:
            node = self.loggers[preferred]
        if node is None and src_ip:
            for lid, lg in list(self.loggers.items()):
                if src_ip in lg.hosts or src_ip in lg.host_seen or lid == src_ip:
                    node = lg
                    break
        if node is None:
            node = LoggerNode(id=preferred, kind=(app or "N1MM"), first_seen=now)
            self.loggers[preferred] = node
        # Upgrade key from IP/NetBIOS → StationName when we learn it.
        if station and node.id != station:
            old = node.id
            if old in self.loggers:
                del self.loggers[old]
            node.aliases.add(old)
            node.id = station
            self.loggers[station] = node
        if netbios and netbios != node.id:
            node.aliases.add(netbios)
        if preferred != node.id:
            node.aliases.add(preferred)
        return node

    def observe_n1mm_xml(self, xml_text: str, now: float, src_ip: str | None = None) -> None:
        """Register an N1MM instance from ANY of its broadcasts. `<contactinfo>` is a
        logged QSO; `<RadioInfo>`/`<AppInfo>`/... are periodic presence beacons that
        let WIMS confirm the N1MM link during setup **without logging a contact**
        (the operator's point — see §3.3 setup validation)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return
        f = {c.tag.lower(): (c.text or "").strip() for c in root}
        tag = root.tag.lower()
        if tag not in _N1MM_ROOTS and not f.get("app"):
            return                       # not an N1MM datagram we recognize
        station = f.get("stationname") or ""
        # NetBiosName / ComputerName = Windows hostname (often differs from StationName).
        netbios = f.get("netbiosname") or f.get("computername") or ""
        node = self._logger_for_n1mm(
            station=station, netbios=netbios, src_ip=src_ip, now=now,
            app=f.get("app") or "N1MM")
        if src_ip:
            node.hosts.add(src_ip)
            node.host_seen[src_ip] = now
        node.last_seen = now             # presence from any broadcast
        if f.get("app"):
            node.kind = f["app"]
        if f.get("mycall"):
            node.mycall = f["mycall"].upper()
        if tag == "contactinfo":         # ...and a logged QSO specifically
            node.last_qso = now
            node.qso_count += 1
            node.last_call = f.get("call") or None
            try:
                node.last_band = band_label_mhz(float(f.get("band")))
            except (TypeError, ValueError):
                node.last_band = None
        # Collapse StationName / NetBIOS / bare-IP rows for this host.
        self.consolidate_loggers()

    def prune_loggers(self, now: float, after: float = DEFAULT_PRUNE_AFTER) -> list[str]:
        """Drop N1MM loggers silent longer than `after` seconds."""
        self.consolidate_loggers()
        dead = []
        for lid, lg in list(self.loggers.items()):
            if lg.last_seen is None or (now - lg.last_seen) > after:
                dead.append(lid)
                del self.loggers[lid]
        return dead

    def observe(self, msg, now: float, src_ip: str | None = None,
                src_port: int | None = None) -> None:
        if not isinstance(msg, M.WsjtxMessage):
            return
        mid = msg.id or "?"
        n = self.nodes.get(mid)
        if n is None:
            n = NodeState(id=mid, first_seen=now)
            self.nodes[mid] = n
        n.note_host(src_ip, now, src_port=src_port)
        if isinstance(msg, M.Heartbeat):
            n.last_heartbeat = now
            if msg.version:
                n.version = msg.version
        elif isinstance(msg, M.Status):
            n.last_status = now
            n.dial_hz = msg.dial_frequency
            bl = band_label(msg.dial_frequency)
            n.band = bl
            if src_ip:
                n.band_by_host[src_ip] = bl
                n.last_status_host = src_ip
            n.mode = msg.mode
            if msg.de_grid:
                n.de_grid = msg.de_grid.upper()
            if msg.de_call:
                n.de_call = msg.de_call.upper()
            # Empty DX Call clears armed highlight when operator clears the box.
            n.dx_call = (msg.dx_call or "").upper() or None
            n.tx_enabled = bool(msg.tx_enabled)
            n.transmitting = msg.transmitting
            n.decoding = msg.decoding
            n.config_name = msg.config_name
        elif isinstance(msg, M.Decode):
            n.last_decode = now
            n.decode_count += 1
            n.decode_times.append(now)
            if n.decode_times[0] < now - 120.0:  # keep ~2 min of history
                n.decode_times = [t for t in n.decode_times if t >= now - 120.0]

    def prune(self, now: float, after: float = DEFAULT_PRUNE_AFTER) -> list[str]:
        """Drop WSJT-X nodes silent longer than `after` seconds. Returns removed ids.

        Without this the Status table accumulates every instance ever heard in the
        process lifetime (killed desktop WSJT-X stays listed as DEAD forever).
        """
        dead = []
        for mid, n in list(self.nodes.items()):
            ls = n.last_seen()
            if ls is None or (now - ls) > after:
                dead.append(mid)
                del self.nodes[mid]
        return dead

    # -- expected vs actual ------------------------------------------------- #

    def diff_expected(self, expected: list[ExpectedInstance], now: float) -> list[Discrepancy]:
        out: list[Discrepancy] = []
        by_id = {e.id: e for e in expected}
        for e in expected:
            n = self.nodes.get(e.id)
            if n is None:
                where = f"{e.vehicle or '?'}/{e.band or '?'}"
                out.append(Discrepancy("missing", "error", f"{e.id} ({where}) not seen on the wire"))
                continue
            h = n.health(now)
            if h in ("STALE", "DEAD"):
                age = int(now - (n.last_seen() or now))
                out.append(Discrepancy("dead", "error", f"{e.id} {h} - last seen {age}s ago"))
            elif n.is_quiet(now):
                out.append(Discrepancy("quiet", "warn", f"{e.id} alive but no decodes ({e.band or n.band}) - band dead or RX issue?"))
            if e.band and n.band and e.band != n.band:
                out.append(Discrepancy("band-mismatch", "warn", f"{e.id} expected {e.band}, observed {n.band}"))
        for mid, n in self.nodes.items():
            if mid not in by_id:
                out.append(Discrepancy("unexpected", "warn", f"{mid} on {n.host} not in expected fleet"))
            live_hosts = sorted(n.hosts_recent(now))
            if len(live_hosts) > 1:
                out.append(Discrepancy("id-collision", "error",
                                       f"id '{mid}' seen from multiple hosts {live_hosts} - instances need unique WSJT-X ids"))
        return out

    # -- rendering ---------------------------------------------------------- #

    def render(self, now: float, expected: list[ExpectedInstance] | None = None) -> str:
        rows = [f"{'ID':<14} {'HOST':<15} {'BAND':<5} {'MODE':<5} {'FREQ':<11} "
                f"{'ST':<4} {'DEC/p':>6} {'LASTDEC':>7} {'HB':>5} HEALTH"]
        for n in sorted(self.nodes.values(), key=lambda x: (x.band or "~", x.id)):
            st = "TX" if n.transmitting else ("DEC" if n.decoding else "RX")
            lastdec = f"{int(now - n.last_decode)}s" if n.last_decode else "-"
            hb = f"{int(now - n.last_heartbeat)}s" if n.last_heartbeat else "-"
            freq = f"{n.dial_hz / 1e6:.6f}" if n.dial_hz else "-"
            health = n.health(now) + ("/QUIET" if n.is_quiet(now) else "")
            rows.append(f"{n.id:<14} {n.host or '-':<15} {n.band or '-':<5} "
                        f"{n.mode or '-':<5} {freq:<11} {st:<4} "
                        f"{n.decodes_per_period(now):>6.1f} {lastdec:>7} {hb:>5} {health}")
        out = ["FLEET - " + (f"{len(self.nodes)} instance(s)")]
        out += rows
        if self.loggers:
            out.append("")
            out.append(f"LOGGERS - {len(self.loggers)} (presence = last QSO; N1MM has no heartbeat)")
            for lg in sorted(self.loggers.values(), key=lambda x: x.id):
                age = f"{int(now - lg.last_qso)}s ago" if lg.last_qso else "-"
                last = f"{lg.last_call or '-'} {lg.last_band or ''}".strip()
                out.append(f"  {lg.kind} @ {lg.id:<18} {lg.host or '-':<15} "
                           f"{lg.qso_count:>3} QSOs  last: {last} ({age})")
        if expected is not None:
            issues = self.diff_expected(expected, now)
            out.append("")
            if not issues:
                out.append("EXPECTED vs ACTUAL: all expected instances present and healthy.")
            else:
                out.append(f"EXPECTED vs ACTUAL - {len(issues)} issue(s):")
                for d in issues:
                    mark = "!!" if d.severity == "error" else " ~"
                    out.append(f"  {mark} [{d.kind}] {d.detail}")
        return "\n".join(out)


def _main() -> None:
    import argparse
    import select
    import socket as _socket
    import time

    from wims.udp.sink import open_socket

    ap = argparse.ArgumentParser(description="Live WSJT-X + N1MM fleet discovery & health.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=2237, help="WSJT-X UDP port")
    ap.add_argument("--multicast", default=None, help="WSJT-X multicast group")
    ap.add_argument("--n1mm-port", type=int, default=12060, help="N1MM broadcast port (0 to disable)")
    ap.add_argument("--n1mm-group", default=None,
                    help="N1MM multicast group (e.g. 224.0.0.73); omit for unicast/broadcast")
    ap.add_argument("--refresh", type=float, default=3.0)
    args = ap.parse_args()

    s_wsjt = open_socket(args.host, args.port, args.multicast)
    socks = [s_wsjt]
    s_n1mm = None
    if args.n1mm_port:
        try:
            s_n1mm = open_socket(args.host, args.n1mm_port, args.n1mm_group)
            socks.append(s_n1mm)
        except OSError as e:
            print(f"(N1MM port {args.n1mm_port} unavailable: {e} - WSJT-X only)")

    tracker = FleetTracker()
    last = 0.0
    wsjt_pkts = n1mm_pkts = 0
    listen = f"WSJT-X {args.multicast or args.host}:{args.port}"
    if s_n1mm:
        n1mm_where = (f"{args.n1mm_group}:{args.n1mm_port}" if args.n1mm_group
                      else f":{args.n1mm_port}")
        listen += f" + N1MM {n1mm_where}"
    print("WIMS fleet view - Ctrl-C to stop\n")
    try:
        while True:
            ready, _, _ = select.select(socks, [], [], 1.0)
            now = time.time()
            for s in ready:
                try:
                    data, addr = s.recvfrom(65535)
                except _socket.error:
                    continue
                if s is s_wsjt:
                    wsjt_pkts += 1
                    msg = M.parse(data)
                    if msg is not None:
                        tracker.observe(msg, now, src_ip=addr[0], src_port=addr[1])
                else:
                    n1mm_pkts += 1
                    tracker.observe_n1mm_xml(data.decode("utf-8", "replace"), now, src_ip=addr[0])
            if now - last >= args.refresh:  # always redraw so an empty fleet still shows life
                last = now
                clock = time.strftime("%H:%M:%S", time.localtime(now))
                print("\033[2J\033[H", end="")
                print(f"WIMS fleet view  {clock}  | listening {listen}"
                      f"  | rx {wsjt_pkts} WSJT-X / {n1mm_pkts} N1MM pkts\n")
                if not tracker.nodes and not tracker.loggers:
                    print("  waiting for traffic...")
                    if wsjt_pkts == 0:
                        print("  no WSJT-X UDP yet - is WSJT-X running and set to this multicast group/port?")
                else:
                    print(tracker.render(now))
    except KeyboardInterrupt:
        print(f"\nstopped - {len(tracker.nodes)} instance(s), {len(tracker.loggers)} logger(s)")


if __name__ == "__main__":
    _main()
