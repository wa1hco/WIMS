"""WIMS server — ingest the fleet and serve the console (plan §4.5 / §3.12).

A single process that:
  * joins the WSJT-X multicast + the N1MM broadcast and maintains a live FleetTracker,
  * serves a static HTML dashboard, and
  * streams live state to the browser as JSON over Server-Sent Events (SSE).

Stdlib only — no framework, no build step. The browser ↔ server contract is the
JSON from `state.py` over `/events`; the rendering (static/dashboard.html) is the
only tool-specific, replaceable part.

Run (with the emulator on loopback, or real WSJT-X):
    python -m wims.server.app --iface 127.0.0.1
    # then open http://localhost:8787
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import select
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wims.udp import messages as M  # noqa: E402
from wims.udp.sink import open_socket  # noqa: E402
from wims.discovery.fleet import FleetTracker  # noqa: E402
from wims.interlock.arbiter import OverlapDetector  # noqa: E402
from wims.udp.activity import ActivityMap  # noqa: E402
from wims.engine import scoring as S  # noqa: E402
from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.server.state import (  # noqa: E402
    fleet_to_dict, interlock_to_dict, roster_to_dict, activity_to_dict,
    decodes_to_dict, n1mm_sync_to_dict)

STATIC = Path(__file__).resolve().parent / "static"


class LiveFleet:
    """Thread-safe wrapper: the ingest thread writes, SSE handlers read.

    Also runs the §3.4 `OverlapDetector` as a passive safety net: every observed
    Status transmit-state feeds it, so the console can show — and historically
    audit — whether two instances in one resource group ever transmit at once.
    `grouping` selects the resource-group scheme until §3.14 profiles supply the
    real shared-resource map: "instance" (each its own group, overlap structurally
    impossible), "band", or "host"."""

    def __init__(self, grouping: str = "instance", condition: str = "open"):
        self._tracker = FleetTracker()
        self._lock = threading.Lock()
        self._grouping = grouping
        self._overlap = OverlapDetector(group_of=self.group_of)
        # Live log copy (in-memory) feeds dupe/new-mult into the roster; kept current
        # from N1MM <contactinfo>. Empty at start => every grid reads as a new mult,
        # flipping to dupe/worked as QSOs are logged (plan §3.6).
        self._log = LogStore(":memory:")
        self._roster = RosterBuilder(log=self._log)
        self._maps: dict[str, ActivityMap] = {}    # per-instance decode-activity map
        self._decodes: deque = deque(maxlen=300)   # rolling fleet-wide decode log
        self._condition = condition
        self.wsjt_pkts = 0
        self.n1mm_pkts = 0
        self._last_n1mm: float | None = None       # last datagram on the N1MM port
        self._last_qso: dict | None = None         # last QSO folded into the log copy
        self._seed: dict | None = None             # {count, source} of the .s3db seed

    def seed_from_db(self, db_path: str) -> int:
        """Pull the existing N1MM contest log into the log copy at startup (§3.6) so
        dupe/mult are correct before any live broadcast. Read-only; WIMS never writes
        N1MM's DB. Returns the number of QSOs seeded."""
        from wims.integrations.n1mm import logdb
        qsos = logdb.read_dxlog(db_path)
        with self._lock:
            self._log.reconcile(qsos)
            self._seed = {"count": len(qsos), "source": Path(db_path).name}
        return len(qsos)

    def group_of(self, instance_id: str) -> str:
        """Map an instance to its resource group per the active scheme. Callers
        hold `self._lock` (ingest + snapshot both do)."""
        if self._grouping in ("band", "host"):
            n = self._tracker.nodes.get(instance_id)
            val = (n.band if self._grouping == "band" else n.host) if n else None
            return val or "?"
        return instance_id

    def observe_wsjtx(self, msg, now, src_ip):
        with self._lock:
            self.wsjt_pkts += 1
            self._tracker.observe(msg, now, src_ip=src_ip)
            if isinstance(msg, M.Status):
                self._overlap.observe(msg.id or "?", msg.transmitting, now)
            elif isinstance(msg, M.Decode):
                mid = msg.id or "?"
                node = self._tracker.nodes.get(mid)
                self._roster.observe_decode(msg, (node.band if node else None) or "?", now)
                self._maps.setdefault(mid, ActivityMap(mid)).add(msg)
                self._decodes.append({
                    "ts": now, "instance": mid, "snr": msg.snr,
                    "df": msg.delta_frequency, "message": msg.message or "",
                    "is_cq": msg.is_cq,
                })

    def observe_n1mm(self, xml_text, now, src_ip):
        with self._lock:
            self.n1mm_pkts += 1
            self._last_n1mm = now
            self._tracker.observe_n1mm_xml(xml_text, now, src_ip=src_ip)
            if "<contactinfo" in xml_text:        # a logged QSO -> update the log copy
                try:
                    q = LoggedQso.from_contactinfo(xml_text)
                    if q.id:
                        self._log.upsert(q)
                        self._last_qso = {"call": q.call, "band": q.band, "ts": now}
                except Exception:
                    pass

    def snapshot(self, now) -> dict:
        with self._lock:
            d = fleet_to_dict(self._tracker, now,
                              wsjt_pkts=self.wsjt_pkts, n1mm_pkts=self.n1mm_pkts)
            tx_ids = {n.id for n in self._tracker.nodes.values() if n.transmitting}
            d["interlock"] = interlock_to_dict(
                self._overlap, self.group_of, self._grouping,
                list(self._tracker.nodes), tx_ids, now)
            ctx = S.Context(weights=S.weights_for(self._condition), condition=self._condition)
            scored, excluded = self._roster.ranked(now, ctx)
            d["roster"] = roster_to_dict(scored, excluded, now,
                                         condition=self._condition,
                                         strategy=self._roster.strategy.name)
            d["activity"] = [activity_to_dict(self._maps[mid])
                             for mid in sorted(self._maps)]
            d["decodes"] = decodes_to_dict(self._decodes, now)
            d["n1mm_sync"] = n1mm_sync_to_dict(
                now, n1mm_pkts=self.n1mm_pkts, last_n1mm=self._last_n1mm,
                qso_count=self._log.count(), last_qso=self._last_qso, seed=self._seed)
            return d


def ingest_loop(live: LiveFleet, iface: str, group: str, port: int, n1mm_port: int):
    s_wsjt = open_socket(iface, port, group)
    socks = [s_wsjt]
    s_n1mm = None
    if n1mm_port:
        try:
            s_n1mm = open_socket(iface, n1mm_port, None)
            socks.append(s_n1mm)
        except OSError:
            pass
    while True:
        ready, _, _ = select.select(socks, [], [], 1.0)
        now = time.time()
        for s in ready:
            try:
                data, addr = s.recvfrom(65535)
            except OSError:
                continue
            if s is s_wsjt:
                msg = M.parse(data)
                if msg is not None:
                    live.observe_wsjtx(msg, now, addr[0])
            else:
                live.observe_n1mm(data.decode("utf-8", "replace"), now, addr[0])


def make_handler(live: LiveFleet, refresh: float):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):           # quiet
            pass

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # path -> static file (two pages share one SSE feed; see static/wims.js).
        PAGES = {"/": "ops.html", "/index.html": "ops.html", "/ops": "ops.html",
                 "/status": "status.html"}
        TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css",
                 ".js": "text/javascript", ".json": "application/json"}

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in self.PAGES:
                self._serve_static(self.PAGES[path])
            elif path == "/healthz":
                self._send(200, "application/json", b'{"ok":true}')
            elif path == "/events":
                self._stream_events()
            elif path.lstrip("/") in {"wims.css", "wims.js"}:
                self._serve_static(path.lstrip("/"))
            else:
                self._send(404, "text/plain", b"not found")

        def _serve_static(self, name: str):
            f = (STATIC / name).resolve()
            if not (f.is_file() and f.is_relative_to(STATIC.resolve())):
                self._send(404, "text/plain", b"not found")
                return
            ctype = self.TYPES.get(f.suffix, "application/octet-stream")
            self._send(200, ctype, f.read_bytes())

        def _stream_events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(live.snapshot(time.time()))
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(refresh)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return   # browser disconnected

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="WIMS server (ingest + console).")
    ap.add_argument("--http-port", type=int, default=8787)
    ap.add_argument("--iface", default="0.0.0.0", help="multicast/bind interface (127.0.0.1 for local emulator)")
    ap.add_argument("--group", default="224.0.0.73", help="WSJT-X multicast group")
    ap.add_argument("--port", type=int, default=2237, help="WSJT-X UDP port")
    ap.add_argument("--n1mm-port", type=int, default=12060)
    ap.add_argument("--refresh", type=float, default=1.0, help="SSE push interval (s)")
    ap.add_argument("--group-by", choices=("instance", "band", "host"), default="instance",
                    help="interlock resource-group scheme until §3.14 profiles wire the real "
                         "shared-resource map (instance = overlap impossible by construction)")
    ap.add_argument("--condition", choices=("open", "marginal", "dead"), default="open",
                    help="band condition -> roster scoring weight set (§3.5)")
    ap.add_argument("--seed-db", default=None,
                    help="N1MM contest .s3db to seed the log copy from (read-only); "
                         "if omitted, auto-find in --seed-db-dir")
    ap.add_argument("--seed-db-dir",
                    default=str(Path.home() / "Documents" / "N1MM Logger+" / "Databases"),
                    help="dir to auto-find the contest .s3db (default: standard N1MM path)")
    ap.add_argument("--no-seed", action="store_true",
                    help="do not seed from any N1MM .s3db at startup")
    args = ap.parse_args()

    # Validate network args up front: a malformed address otherwise only blows up
    # deep inside the ingest thread (inet_aton), which dies silently while the
    # server keeps serving empty state. Fail fast with a clear message instead.
    try:
        ipaddress.IPv4Address(args.iface)
    except ipaddress.AddressValueError:
        ap.error(f"invalid --iface {args.iface!r}: not a valid IPv4 address "
                 f"(e.g. 127.0.0.1 for the local emulator, or 0.0.0.0 for all interfaces)")
    try:
        if not ipaddress.IPv4Address(args.group).is_multicast:
            ap.error(f"invalid --group {args.group!r}: not a multicast address "
                     f"(WSJT-X default is 224.0.0.73)")
    except ipaddress.AddressValueError:
        ap.error(f"invalid --group {args.group!r}: not a valid IPv4 address "
                 f"(WSJT-X default is 224.0.0.73)")

    live = LiveFleet(grouping=args.group_by, condition=args.condition)

    if not args.no_seed:
        from wims.integrations.n1mm import logdb
        seed_path = args.seed_db or logdb.find_contest_db(args.seed_db_dir)
        if seed_path and Path(seed_path).is_file():
            try:
                n = live.seed_from_db(seed_path)
                print(f"  seeded {n} QSOs from {Path(seed_path).name} "
                      f"(log copy ready -> roster dupe/mult)")
            except Exception as e:
                print(f"  (seed skipped: {e})")
        else:
            print("  (no N1MM contest .s3db found to seed; log copy starts empty)")
    threading.Thread(target=ingest_loop, daemon=True,
                     args=(live, args.iface, args.group, args.port, args.n1mm_port)).start()

    httpd = ThreadingHTTPServer(("0.0.0.0", args.http_port), make_handler(live, args.refresh))
    print(f"WIMS server: http://localhost:{args.http_port}/  (Operate)   "
          f"http://localhost:{args.http_port}/status  (System status)")
    print(f"  ingesting {args.group}:{args.port} + N1MM :{args.n1mm_port} on {args.iface}")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
