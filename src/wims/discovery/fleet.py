"""Passive fleet discovery + health + expected-vs-actual (plan §3.15 / §2.5).

WIMS already joins the WSJT-X multicast, so it can enumerate the whole fleet for
free: which instances are alive, on what band, last decode, plus health and
config problems - the cross-vehicle visibility that currently lives only in chat
(see Deployment context). Feed it parsed messages with a timestamp + source IP;
ask it for a status table or a diff against the expected fleet.

Time is injected (``now``) so it is testable and replayable.
"""

from __future__ import annotations

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

# N1MM external-broadcast root tags we treat as presence-bearing (lowercased).
_N1MM_ROOTS = {"contactinfo", "radioinfo", "appinfo", "dynamicresults",
               "spot", "lookupinfo", "contactdelete", "contactreplace"}


@dataclass
class NodeState:
    """Live state of one WSJT-X instance, keyed by its UDP id."""

    id: str
    hosts: set[str] = field(default_factory=set)   # source IPs seen for this id
    version: str | None = None
    band: str | None = None
    mode: str | None = None
    dial_hz: int = 0
    transmitting: bool = False
    decoding: bool = False
    config_name: str | None = None
    last_heartbeat: float | None = None
    last_status: float | None = None
    last_decode: float | None = None
    decode_count: int = 0
    decode_times: list[float] = field(default_factory=list)
    first_seen: float = 0.0

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
    def host(self) -> str | None:
        return sorted(self.hosts)[0] if self.hosts else None

    @property
    def id_collision(self) -> bool:
        # Same WSJT-X id from >1 host = two instances WIMS/N1MM can't tell apart.
        return len(self.hosts) > 1


@dataclass
class LoggerNode:
    """An N1MM instance seen on the network, identified by station name. Presence is
    established by ANY N1MM broadcast — `<RadioInfo>`/`<AppInfo>` beacons arrive
    periodically (no QSO needed), so `last_seen` is real liveness usable for setup
    verification; `last_qso` (from `<contactinfo>`) is specifically the last logged QSO.
    """

    id: str                      # N1MM StationName / NetBiosName
    kind: str = "N1MM"
    hosts: set[str] = field(default_factory=set)
    last_seen: float | None = None   # any N1MM broadcast (presence / liveness)
    last_qso: float | None = None    # last <contactinfo> (a logged QSO)
    qso_count: int = 0
    last_call: str | None = None
    last_band: str | None = None
    mycall: str | None = None        # the station's own call (RadioInfo/contactinfo)
    first_seen: float = 0.0

    @property
    def host(self) -> str | None:
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
        name = f.get("stationname") or f.get("netbiosname") or src_ip or "?"
        node = self.loggers.get(name)
        if node is None:
            node = LoggerNode(id=name, kind=(f.get("app") or "N1MM"), first_seen=now)
            self.loggers[name] = node
        if src_ip:
            node.hosts.add(src_ip)
        node.last_seen = now             # presence from any broadcast
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

    def observe(self, msg, now: float, src_ip: str | None = None) -> None:
        if not isinstance(msg, M.WsjtxMessage):
            return
        mid = msg.id or "?"
        n = self.nodes.get(mid)
        if n is None:
            n = NodeState(id=mid, first_seen=now)
            self.nodes[mid] = n
        if src_ip:
            n.hosts.add(src_ip)
        if isinstance(msg, M.Heartbeat):
            n.last_heartbeat = now
            if msg.version:
                n.version = msg.version
        elif isinstance(msg, M.Status):
            n.last_status = now
            n.dial_hz = msg.dial_frequency
            n.band = band_label(msg.dial_frequency)
            n.mode = msg.mode
            n.transmitting = msg.transmitting
            n.decoding = msg.decoding
            n.config_name = msg.config_name
        elif isinstance(msg, M.Decode):
            n.last_decode = now
            n.decode_count += 1
            n.decode_times.append(now)
            if n.decode_times[0] < now - 120.0:  # keep ~2 min of history
                n.decode_times = [t for t in n.decode_times if t >= now - 120.0]

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
            if n.id_collision:
                out.append(Discrepancy("id-collision", "error",
                                       f"id '{mid}' seen from multiple hosts {sorted(n.hosts)} - instances need unique WSJT-X ids"))
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
    ap.add_argument("--refresh", type=float, default=3.0)
    args = ap.parse_args()

    s_wsjt = open_socket(args.host, args.port, args.multicast)
    socks = [s_wsjt]
    s_n1mm = None
    if args.n1mm_port:
        try:
            s_n1mm = open_socket(args.host, args.n1mm_port, None)
            socks.append(s_n1mm)
        except OSError as e:
            print(f"(N1MM port {args.n1mm_port} unavailable: {e} - WSJT-X only)")

    tracker = FleetTracker()
    last = 0.0
    wsjt_pkts = n1mm_pkts = 0
    listen = f"WSJT-X {args.multicast or args.host}:{args.port}"
    if s_n1mm:
        listen += f" + N1MM :{args.n1mm_port}"
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
                        tracker.observe(msg, now, src_ip=addr[0])
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
