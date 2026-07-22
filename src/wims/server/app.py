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
import os
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
from wims.interlock.arbiter import OverlapDetector, TxArbiter  # noqa: E402
from wims.udp.controller import TxController  # noqa: E402
from wims.udp.activity import ActivityMap  # noqa: E402
from wims.engine import scoring as S  # noqa: E402
from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso, id_from_contactdelete  # noqa: E402
from wims.server.state import (  # noqa: E402
    fleet_to_dict, interlock_to_dict, roster_to_dict, activity_to_dict,
    decodes_to_dict, n1mm_sync_to_dict, agents_to_dict, tx_to_dict)

STATIC = Path(__file__).resolve().parent / "static"


class LiveFleet:
    """Thread-safe wrapper: the ingest thread writes, SSE handlers read.

    Also runs the §3.4 `OverlapDetector` as a passive safety net: every observed
    Status transmit-state feeds it, so the console can show — and historically
    audit — whether two instances in one resource group ever transmit at once.
    `grouping` selects the resource-group scheme until §3.14 profiles supply the
    real shared-resource map: "instance" (each its own group, overlap structurally
    impossible), "band", or "host"."""

    def __init__(self, grouping: str = "instance", condition: str = "open",
                 tx_controller: "TxController | None" = None,
                 enable_cq_freetext: bool = False):
        self._tracker = FleetTracker()
        self._lock = threading.Lock()
        self._grouping = grouping
        self._overlap = OverlapDetector(group_of=self.group_of)
        # --- TX control (plan §3.2 / §3.4 / §4.5 / §2.12) ---------------------
        # `_tx` actuates Reply/Halt to WSJT-X; None => read-only console (--no-tx).
        # No global arm/disarm: human initiation is the roster click itself
        # (GridTracker2-style). `_arbiter` enforces ≤1 TX per resource group.
        self._tx = tx_controller
        self._enable_cq = bool(enable_cq_freetext)
        self._arbiter = TxArbiter(group_of=self.group_of)
        self._tx_prev: dict[str, bool] = {}        # per-instance last transmitting (edge)
        self._last_tx_action: dict | None = None   # last work/halt for the UI
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
        self._seed: dict | None = None             # seed meta (count, source, contest…)
        self._last_resync: dict | None = None      # last operator (or API) DXLOG reconcile
        # Contest log discovery — operators pick by human label, not ContestNR CLI.
        self._seed_db_dir: str | None = None
        self._seed_db_hint: str | None = None      # optional preferred .s3db path
        self._active_contest: dict | None = None   # ContestInfo.to_dict() currently loaded
        self._contest_catalog: list = []           # all discovered contests for UI
        # Seat agents (config audit heartbeats) — agent_id -> last report.
        self._agents: dict[str, dict] = {}
        self._agent_prune_after = 300.0            # drop silent agents after 5 min

    def configure_log_discovery(self, *, databases_dir: str | None = None,
                                db_path: str | None = None) -> None:
        """Where to look for N1MM .s3db files (no IPs required — local paths only)."""
        self._seed_db_dir = databases_dir
        self._seed_db_hint = db_path

    def refresh_contest_catalog(self) -> list:
        """Re-scan disk for multi-contest .s3db files. Returns contest dicts for UI."""
        from wims.integrations.n1mm import logdb
        disc = logdb.discover(self._seed_db_dir, self._seed_db_hint)
        with self._lock:
            self._contest_catalog = disc["contests"]
        return disc["contests"]

    def seed_from_db(self, db_path: str, *, contest_nr: int | None = None,
                     contest_name: str | None = None) -> int:
        """Pull one N1MM contest log into the log copy (§3.6). Read-only.

        When the .s3db holds multiple contests (June + Sept VHF…), pass contest_nr
        (preferred) so only that ContestInstance's DXLOG rows load.
        """
        from wims.integrations.n1mm import logdb
        qsos = logdb.read_dxlog(db_path, contest_nr=contest_nr,
                                contest_name=contest_name)
        contests = logdb.list_contests(db_path)
        active = None
        for c in contests:
            if contest_nr is not None and c.contest_nr == contest_nr:
                active = c.to_dict()
                break
            if contest_name and c.contest_name == contest_name:
                active = c.to_dict()
                break
        if active is None and contests:
            # Record what we loaded even if filter was by name only.
            active = {
                "contest_nr": contest_nr,
                "contest_name": contest_name,
                "qso_count": len(qsos),
                "db_path": db_path,
                "db_label": Path(db_path).name,
                "label": contest_name or f"ContestNR {contest_nr}",
            }
        with self._lock:
            self._log.reconcile(qsos)
            self._seed = {
                "count": len(qsos),
                "source": Path(db_path).name,
                "db_path": db_path,
                "contest_nr": contest_nr,
                "contest_name": (active or {}).get("contest_name") or contest_name,
                "label": (active or {}).get("label"),
            }
            self._active_contest = active
            self._seed_db_hint = db_path
        return len(qsos)

    def auto_seed(self) -> dict:
        """Discover contests and seed the recommended one (latest with QSOs).

        Returns a small status dict for startup logging / API. Never raises on
        empty discovery — log copy stays empty and UI offers a picker.
        """
        from wims.integrations.n1mm import logdb
        disc = logdb.discover(self._seed_db_dir, self._seed_db_hint)
        with self._lock:
            self._contest_catalog = disc["contests"]
        rec = disc.get("recommended")
        if not rec:
            return {"ok": False, "reason": "no_contests_with_qsos",
                    "contests": disc["contests"]}
        n = self.seed_from_db(rec["db_path"], contest_nr=rec["contest_nr"])
        return {"ok": True, "seeded": n, "contest": rec,
                "contests": disc["contests"]}

    def select_contest(self, *, db_path: str, contest_nr: int) -> dict:
        """Operator picked a contest in the Status UI — reload log copy from DXLOG."""
        n = self.seed_from_db(db_path, contest_nr=int(contest_nr))
        self.refresh_contest_catalog()
        with self._lock:
            active = self._active_contest
        return {"ok": True, "seeded": n, "contest": active}

    def resync_log(self, *, now: float | None = None) -> dict:
        """Operator-triggered re-read of the active contest's DXLOG → reconcile.

        UDP contactinfo/delete/replace keeps the log copy live; this is the
        safety net when events were missed (WIMS down, Contacts broadcast off,
        remote DB replaced). Re-opens the same ``.s3db`` + ContestNR already
        loaded, upserts by ID, and deletes rows no longer in N1MM.

        Does **not** drive N1MM peer "Resync" — if multi-op seats disagree,
        resync N1MM peers first so the file is authoritative, then call this.
        """
        from wims.integrations.n1mm import logdb
        now = time.time() if now is None else now
        with self._lock:
            active = dict(self._active_contest) if self._active_contest else {}
            seed = dict(self._seed) if self._seed else {}
        db_path = active.get("db_path") or seed.get("db_path")
        contest_nr = active.get("contest_nr")
        if contest_nr is None:
            contest_nr = seed.get("contest_nr")
        contest_name = active.get("contest_name") or seed.get("contest_name")
        label = active.get("label") or seed.get("label") or contest_name
        if not db_path:
            return {
                "ok": False,
                "error": "no_active_log",
                "hint": "Pick a contest log under Setup first.",
            }
        if not Path(db_path).is_file():
            return {
                "ok": False,
                "error": "db_not_found",
                "db_path": db_path,
                "hint": "Copy the N1MM .s3db onto this host (seed dir), then Rescan.",
            }
        try:
            nr = int(contest_nr) if contest_nr is not None else None
        except (TypeError, ValueError):
            nr = None
        try:
            qsos = logdb.read_dxlog(
                db_path,
                contest_nr=nr,
                contest_name=contest_name if nr is None else None,
            )
        except Exception as e:
            return {"ok": False, "error": str(e), "db_path": db_path}

        with self._lock:
            summary = self._log.reconcile(qsos)
            self._seed = {
                "count": summary["total"],
                "source": Path(db_path).name,
                "db_path": db_path,
                "contest_nr": nr,
                "contest_name": contest_name,
                "label": label,
            }
            if self._active_contest is not None:
                self._active_contest = {
                    **self._active_contest,
                    "qso_count": len(qsos),
                    "db_path": db_path,
                }
            last = {
                "ts": now,
                "upserted": summary["upserted"],
                "deleted": summary["deleted"],
                "total": summary["total"],
                "source": Path(db_path).name,
                "db_path": db_path,
                "contest_nr": nr,
                "contest_name": contest_name,
                "label": label,
            }
            self._last_resync = last
            active_out = self._active_contest
        try:
            self.refresh_contest_catalog()
        except Exception:
            pass
        return {"ok": True, "summary": last, "contest": active_out,
                "qso_count": last["total"]}

    def accept_agent_report(self, body: dict, *, now: float | None = None) -> dict:
        """Ingest a seat agent report (POST /api/agents/report). Local-first agent
        already validated configs on the station PC; this stores the snapshot for
        the wrangler Status/Setup board."""
        if not isinstance(body, dict):
            return {"ok": False, "error": "body must be a JSON object"}
        agent_id = (body.get("agent_id") or "").strip()
        if not agent_id:
            return {"ok": False, "error": "agent_id required"}
        ts = now if now is not None else time.time()
        # Prefer agent clock if plausible; else server receive time.
        try:
            agent_ts = float(body.get("ts") or ts)
        except (TypeError, ValueError):
            agent_ts = ts
        if abs(agent_ts - ts) > 600:
            agent_ts = ts
        stored = dict(body)
        stored["agent_id"] = agent_id
        stored["ts"] = agent_ts
        stored["received_at"] = ts
        with self._lock:
            self._agents[agent_id] = stored
        summary = (stored.get("summary") or {})
        return {
            "ok": True,
            "agent_id": agent_id,
            "severity": summary.get("severity"),
            "message": summary.get("message"),
        }

    def list_agents(self, now: float | None = None) -> list:
        now = time.time() if now is None else now
        with self._lock:
            self._prune_agents(now)
            return agents_to_dict(self._agents, now)

    def _prune_agents(self, now: float) -> None:
        dead = [aid for aid, r in self._agents.items()
                if now - float(r.get("ts") or 0) > self._agent_prune_after]
        for aid in dead:
            del self._agents[aid]

    # --- TX control actions (plan §3.2 / §4.5 / §2.12) ----------------------- #

    def work_station(self, row_id: str) -> dict:
        """Answer the station in roster row `row_id` — send Reply to its instance.

        Human initiation is the roster click (GridTracker2-style); no separate arm
        switch. Arbiter-gated (refuses if another instance in the same resource
        group holds TX). The actual `sendto` runs outside the lock so a slow
        socket never stalls the ingest thread."""
        if self._tx is None:
            return {"ok": False, "error": "tx_disabled"}
        with self._lock:
            entry = self._roster.entry_for(row_id)
            if entry is None:
                return {"ok": False, "error": "unknown_row"}
            decode = entry.decode
            inst = getattr(decode, "id", None) or "?"
            if not self._arbiter.request(inst):
                holder = self._arbiter.holder(self._arbiter.group_of(inst))
                return {"ok": False, "error": "group_busy", "holder": holder}
            call = (getattr(decode, "dx_call", "") or "").upper()
            msg_text = getattr(decode, "message", "") or ""
        try:
            self._tx.reply(inst, decode)
        except OSError as e:
            with self._lock:
                self._arbiter.release(inst)
            return {"ok": False, "error": f"send_failed: {e}"}
        with self._lock:
            self._last_tx_action = {"action": "work", "instance": inst,
                                    "call": call, "message": msg_text, "ts": time.time()}
        return {"ok": True, "sent": "reply", "instance": inst,
                "call": call, "message": msg_text}

    def halt(self, instance: str | None = None) -> dict:
        """Stop transmitting — the panic button. Halts one instance or every live
        one, and releases the arbiter so the group frees immediately."""
        if self._tx is None:
            return {"ok": False, "error": "tx_disabled"}
        with self._lock:
            targets = [instance] if instance else [n.id for n in self._tracker.nodes.values()]
        halted = []
        for inst in targets:
            try:
                self._tx.halt(inst)
                halted.append(inst)
            except OSError:
                pass
        with self._lock:
            for inst in halted:
                self._arbiter.release(inst)
            self._last_tx_action = {"action": "halt", "instances": halted, "ts": time.time()}
        return {"ok": True, "halted": halted}

    def call_cq(self, *, mycall: str | None = None, grid: str | None = None) -> dict:
        """Call CQ. WSJT-X's UDP API has **no native Call CQ** — only Reply to an
        existing decode. The only UDP route is a one-shot FreeText that WSJT-X will
        not auto-sequence, so it is gated behind `--enable-cq-freetext` and remains
        unimplemented pending the live spike (plan P3). Default: instruct the operator
        to call CQ in WSJT-X directly; WIMS does the (clean) answering."""
        if not self._enable_cq:
            return {"ok": False, "error": "cq_not_supported_yet",
                    "detail": "WSJT-X UDP has no Call CQ; call CQ in WSJT-X directly. "
                              "Experimental FreeText CQ is gated behind --enable-cq-freetext."}
        return {"ok": False, "error": "cq_freetext_not_implemented",
                "detail": "Experimental FreeText CQ path pending live WSJT-X verification (P3)."}

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
            mid = getattr(msg, "id", None) or "?"
            # Empty decode-activity tile as soon as the instance is heard (Heartbeat/
            # Status), not only after the first Decode — quiet bands still get a frame.
            self._maps.setdefault(mid, ActivityMap(mid))
            if isinstance(msg, M.Status):
                self._overlap.observe(mid, msg.transmitting, now)
                # Free the arbiter grant on the TX→RX edge so the next Work isn't
                # blocked. Driven by WSJT-X's own Status (not N1MM) — a solo tester
                # may not run N1MM at all.
                if self._tx_prev.get(mid, False) and not msg.transmitting:
                    self._arbiter.release(mid)
                self._tx_prev[mid] = bool(msg.transmitting)
            elif isinstance(msg, M.Decode):
                node = self._tracker.nodes.get(mid)
                self._roster.observe_decode(
                    msg, (node.band if node else None) or "?", now,
                    dial_hz=(node.dial_hz if node else 0),
                    de_grid=(node.de_grid if node else None))
                self._maps[mid].add(msg)
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
            # Live log maintenance: N1MM Contacts broadcasts cover add / edit / delete.
            # Edit = contactdelete + contactreplace (same ID). Delete alone removes the
            # row so roster needed/dupe flips back without waiting for DXLOG resync.
            try:
                low = xml_text.lower()
                if "<contactdelete" in low:
                    qid = id_from_contactdelete(xml_text)
                    if qid:
                        self._log.delete(qid)
                elif "<contactinfo" in low or "<contactreplace" in low:
                    q = LoggedQso.from_contactinfo(xml_text)
                    if not q.id:
                        return
                    # If operator selected a contest, ignore live QSOs from other logs
                    # (same multi-contest .s3db problem over the wire).
                    active = self._active_contest
                    if active:
                        want_name = (active.get("contest_name") or "").strip().upper()
                        got_name = (q.contest or "").strip().upper()
                        if want_name and got_name and want_name != got_name:
                            return
                    self._log.upsert(q)
                    self._last_qso = {"call": q.call, "band": q.band, "ts": now}
            except Exception:
                pass

    def snapshot(self, now) -> dict:
        with self._lock:
            # Drop instances that stopped sending (killed WSJT-X / moved host).
            for mid in self._tracker.prune(now):
                self._maps.pop(mid, None)
            d = fleet_to_dict(self._tracker, now,
                              wsjt_pkts=self.wsjt_pkts, n1mm_pkts=self.n1mm_pkts)
            tx_ids = {n.id for n in self._tracker.nodes.values() if n.transmitting}
            d["interlock"] = interlock_to_dict(
                self._overlap, self.group_of, self._grouping,
                list(self._tracker.nodes), tx_ids, now)
            ctx = S.Context(weights=S.weights_for(self._condition), condition=self._condition)
            rows, not_needed = self._roster.ranked(now, ctx)
            d["roster"] = roster_to_dict(rows, not_needed, now,
                                         condition=self._condition,
                                         strategy=self._roster.strategy.name)
            # One activity tile per live instance (including empty / no decodes).
            live_ids = set(self._tracker.nodes)
            d["activity"] = [activity_to_dict(self._maps[mid], now=now)
                             for mid in sorted(self._maps)
                             if mid in live_ids]
            d["decodes"] = decodes_to_dict(self._decodes, now)
            d["n1mm_sync"] = n1mm_sync_to_dict(
                now, n1mm_pkts=self.n1mm_pkts, last_n1mm=self._last_n1mm,
                qso_count=self._log.count(), last_qso=self._last_qso, seed=self._seed,
                active_contest=self._active_contest,
                contests=self._contest_catalog,
                last_resync=self._last_resync)
            self._prune_agents(now)
            d["agents"] = agents_to_dict(self._agents, now)
            d["tx"] = tx_to_dict(
                enabled=self._tx is not None,
                controller_dest=(self._tx.dest if self._tx else None),
                holders=self._arbiter.holders(),
                enable_cq=self._enable_cq,
                last_action=self._last_tx_action)
            return d


def ingest_loop(live: LiveFleet, s_wsjt: socket.socket, s_n1mm: socket.socket | None):
    socks = [s for s in (s_wsjt, s_n1mm) if s is not None]
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

        def _send_json(self, code: int, obj: dict):
            self._send(code, "application/json",
                       json.dumps(obj).encode("utf-8"))

        # path -> static file (two pages share one SSE feed; see static/wims.js).
        PAGES = {"/": "ops.html", "/index.html": "ops.html", "/ops": "ops.html",
                 "/status": "status.html", "/setup": "setup.html"}
        TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css",
                 ".js": "text/javascript", ".json": "application/json"}

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in self.PAGES:
                self._serve_static(self.PAGES[path])
            elif path == "/healthz":
                # Rich healthz for zero-memory discovery (agent HTTP subnet probe).
                # Legacy clients only need "ok": true.
                host_hdr = (self.headers.get("Host") or "").strip()
                if host_hdr:
                    base = f"http://{host_hdr}"
                else:
                    base = f"http://127.0.0.1:{self.server.server_address[1]}"
                body = {
                    "ok": True,
                    "role": "wims-site-server",
                    "kind": "wims-server",
                    "hostname": socket.gethostname(),
                    "console_base": base,
                    "http_port": self.server.server_address[1],
                    "urls": {
                        "operate": f"{base}/",
                        "status": f"{base}/status",
                        "setup": f"{base}/setup",
                        "healthz": f"{base}/healthz",
                    },
                }
                self._send_json(200, body)
            elif path == "/events":
                self._stream_events()
            elif path == "/api/contests":
                # Fresh disk scan so a newly copied .s3db appears without restart.
                contests = live.refresh_contest_catalog()
                snap = live.snapshot(time.time())
                ns = snap.get("n1mm_sync") or {}
                self._send_json(200, {
                    "contests": contests,
                    "active_contest": ns.get("active_contest"),
                    "qso_count": ns.get("qso_count"),
                })
            elif path == "/api/agents":
                self._send_json(200, {"agents": live.list_agents()})
            elif path.lstrip("/") in {"wims.css", "wims.js"}:
                self._serve_static(path.lstrip("/"))
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid JSON"})
                return
            if path == "/api/contests/select":
                # Operator picked a human-listed contest (Status UI). No cryptic CLI.
                db_path = body.get("db_path")
                contest_nr = body.get("contest_nr")
                if not db_path or contest_nr is None:
                    self._send_json(400, {"ok": False,
                                          "error": "need db_path and contest_nr"})
                    return
                if not Path(db_path).is_file():
                    self._send_json(400, {"ok": False, "error": "db_path not found"})
                    return
                try:
                    result = live.select_contest(db_path=db_path,
                                                 contest_nr=int(contest_nr))
                    self._send_json(200, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/contests/rescan":
                try:
                    contests = live.refresh_contest_catalog()
                    self._send_json(200, {"ok": True, "contests": contests})
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/log/resync":
                # Operator safety net: re-read active contest DXLOG → reconcile by ID.
                try:
                    result = live.resync_log()
                    code = 200 if result.get("ok") else 400
                    self._send_json(code, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/agents/report":
                try:
                    result = live.accept_agent_report(body)
                    code = 200 if result.get("ok") else 400
                    self._send_json(code, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/tx/work":
                # Roster click → Reply (GT2-style; no global arm switch).
                row_id = body.get("row_id")
                if not row_id:
                    self._send_json(400, {"ok": False, "error": "need row_id"})
                    return
                try:
                    result = live.work_station(row_id)
                    code = (200 if result.get("ok")
                            else 409 if result.get("error") == "group_busy"
                            else 400)
                    self._send_json(code, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/tx/halt":
                # Panic stop — always available on Operate.
                try:
                    result = live.halt(body.get("instance"))
                    self._send_json(200 if result.get("ok") else 400, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/tx/cq":
                result = live.call_cq(mycall=body.get("mycall"), grid=body.get("grid"))
                self._send_json(200 if result.get("ok") else 501, result)
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
    from wims.discovery import presence as P

    ap = argparse.ArgumentParser(description="WIMS server (ingest + console).")
    ap.add_argument("--http-port", type=int, default=8787)
    ap.add_argument("--iface", default="0.0.0.0", help="multicast/bind interface (127.0.0.1 for local emulator)")
    ap.add_argument("--group", default="224.0.0.73", help="WSJT-X multicast group")
    ap.add_argument("--port", type=int, default=2237, help="WSJT-X UDP port")
    ap.add_argument("--n1mm-port", type=int, default=12060)
    ap.add_argument("--n1mm-group", default=None,
                    help="multicast group for N1MM External Broadcast XML "
                         "(e.g. 224.0.0.73 — same group as WSJT-X is fine; different port). "
                         "Omit for classic unicast/directed-broadcast to this host:12060")
    ap.add_argument("--refresh", type=float, default=1.0, help="SSE push interval (s)")
    ap.add_argument("--group-by", choices=("instance", "band", "host"), default="instance",
                    help="interlock resource-group scheme until §3.14 profiles wire the real "
                         "shared-resource map (instance = overlap impossible by construction)")
    ap.add_argument("--condition", choices=("open", "marginal", "dead"), default="open",
                    help="band condition -> roster scoring weight set (§3.5)")
    ap.add_argument("--tx-host", default=None,
                    help="send WSJT-X control (Reply/Halt) to this unicast host, e.g. "
                         "127.0.0.1 for solo single-PC. Default: the --group multicast, "
                         "matching ingest (works for multicast-loopback on one PC).")
    ap.add_argument("--tx-port", type=int, default=None,
                    help="WSJT-X control destination port (default: --port, 2237)")
    ap.add_argument("--no-tx", action="store_true",
                    help="disable the TX control path entirely (read-only console)")
    ap.add_argument("--enable-cq-freetext", action="store_true",
                    help="EXPERIMENTAL: allow Call CQ via one-shot WSJT-X FreeText "
                         "(no auto-sequence; pending live verify). Off by default.")
    ap.add_argument("--seed-db", default=None,
                    help="N1MM contest .s3db to seed the log copy from (read-only); "
                         "if omitted, auto-find in --seed-db-dir")
    ap.add_argument("--seed-db-dir",
                    default=str(Path.home() / "Documents" / "N1MM Logger+" / "Databases"),
                    help="dir to auto-find the contest .s3db (default: standard N1MM path)")
    ap.add_argument("--no-seed", action="store_true",
                    help="do not seed from any N1MM .s3db at startup")
    ap.add_argument("--presence-group", default=P.DEFAULT_GROUP,
                    help=f"site-server presence multicast group (default {P.DEFAULT_GROUP})")
    ap.add_argument("--presence-port", type=int, default=P.DEFAULT_PORT,
                    help=f"site-server presence UDP port (default {P.DEFAULT_PORT}; "
                         f"HTTP console stays on --http-port)")
    ap.add_argument("--no-presence", action="store_true",
                    help="do not announce or listen for other WIMS site servers")
    ap.add_argument("--force-server", action="store_true",
                    help="start even if another site server is announcing (lab only; loud)")
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
    if args.n1mm_group:
        try:
            if not ipaddress.IPv4Address(args.n1mm_group).is_multicast:
                ap.error(f"invalid --n1mm-group {args.n1mm_group!r}: not a multicast address "
                         f"(e.g. 224.0.0.73)")
        except ipaddress.AddressValueError:
            ap.error(f"invalid --n1mm-group {args.n1mm_group!r}: not a valid IPv4 address")

    # --- Plane E: single site-server presence (refuse dual-primary) ---------- #
    instance_id = P.new_instance_id()
    announcer = None
    if not args.no_presence:
        peers = P.listen_for_peers(
            iface=args.iface,
            group=args.presence_group,
            port=args.presence_port,
            duration_s=P.STARTUP_LISTEN_S,
            exclude_instance_id=instance_id,
        )
        if peers and not args.force_server:
            print(P.format_conflict_message(peers, self_host=socket.gethostname()),
                  file=sys.stderr)
            sys.exit(2)
        if peers and args.force_server:
            print("WARNING: --force-server: another WIMS site server is announcing; "
                  "starting anyway (lab only).", file=sys.stderr)
            for p in peers:
                print(f"  peer {p.get('hostname')} {p.get('console_base')}",
                      file=sys.stderr)

    # TX controller: unicast to --tx-host when given (solo single-PC WSJT-X on
    # 127.0.0.1), else the same multicast group we ingest (works loopback on one PC).
    tx_controller = None
    if not args.no_tx:
        tx_port = args.tx_port or args.port
        if args.tx_host:
            tx_controller = TxController.for_unicast(args.tx_host, tx_port)
        else:
            tx_controller = TxController.for_group(args.group, tx_port, iface=args.iface)

    live = LiveFleet(grouping=args.group_by, condition=args.condition,
                     tx_controller=tx_controller,
                     enable_cq_freetext=args.enable_cq_freetext)
    live.configure_log_discovery(databases_dir=args.seed_db_dir,
                                 db_path=args.seed_db)

    if not args.no_seed:
        # Auto: scan .s3db files, list contests (June + Sept…), pick latest with QSOs.
        # Operator can change selection on Status — no ContestNR CLI required.
        try:
            result = live.auto_seed()
            if result.get("ok"):
                c = result["contest"]
                print(f"  seeded {result['seeded']} QSOs from {c.get('db_label')} · "
                      f"{c.get('label')}  (log copy → roster dupe/mult)")
                others = [x for x in result.get("contests") or []
                          if not x.get("recommended") and x.get("qso_count", 0) > 0]
                if others:
                    print(f"  ({len(others)} other contest log(s) in file(s) — "
                          f"pick on http://localhost:{args.http_port}/setup)")
            else:
                ncat = len(result.get("contests") or [])
                print(f"  (no contest with QSOs to seed; catalog has {ncat} entry(ies); "
                      f"copy N1MM .s3db into seed dir or use Setup picker)")
        except Exception as e:
            print(f"  (seed skipped: {e})")
    else:
        live.refresh_contest_catalog()
    # Open the ingest sockets here (not inside the thread) so a bind failure is
    # reported on the main path and the bound addresses are confirmed deterministically.
    s_wsjt = open_socket(args.iface, args.port, args.group)
    s_n1mm = None
    if args.n1mm_port:
        # N1MM External Broadcast XML is usually unicast/directed to host:12060, but
        # multi-host fleets can multicast it (e.g. 224.0.0.73:12060 — same group as
        # WSJT-X, different port). Multicast needs a real interface for IGMP join:
        # --iface 127.0.0.1 only receives loopback multicasts, not LAN traffic from a VM.
        try:
            if args.n1mm_group:
                s_n1mm = open_socket(args.iface, args.n1mm_port, args.n1mm_group)
            else:
                # Unicast/broadcast: bind all interfaces so a LAN N1MM host is not
                # dropped when --iface is loopback for the WSJT-X emulator path.
                s_n1mm = open_socket("0.0.0.0", args.n1mm_port, None)
        except OSError as e:
            print(f"  WARNING: N1MM listener could not bind :{args.n1mm_port} ({e}); "
                  f"N1MM ingest disabled")
    threading.Thread(target=ingest_loop, daemon=True,
                     args=(live, s_wsjt, s_n1mm)).start()

    httpd = ThreadingHTTPServer(("0.0.0.0", args.http_port), make_handler(live, args.refresh))
    console_ip = P._primary_lan_ip(args.iface)
    print(f"WIMS server: http://localhost:{args.http_port}/       (Operate)")
    print(f"             http://{console_ip}:{args.http_port}/     (LAN console)")
    print(f"             http://localhost:{args.http_port}/status  (live health)")
    print(f"             http://localhost:{args.http_port}/setup   (config / contest log)")
    print(f"  ingesting WSJT-X {args.group}:{args.port} on {args.iface}")
    if tx_controller is not None:
        _txd = tx_controller.dest
        print(f"  TX control -> {_txd[0]}:{_txd[1]}  (roster click = Work; Halt always on) "
              f"{'· CQ-freetext ON' if args.enable_cq_freetext else ''}")
    else:
        print("  TX control disabled (--no-tx; read-only console)")
    if s_n1mm is not None:
        if args.n1mm_group:
            print(f"  N1MM XML listening on {args.n1mm_group}:{args.n1mm_port} "
                  f"(multicast join via {args.iface})")
            if args.iface in ("127.0.0.1", "0.0.0.0"):
                print("  NOTE: for LAN N1MM multicast set --iface to this host's LAN IP "
                      f"(e.g. the address on the bridged subnet), not {args.iface}")
        else:
            print(f"  N1MM XML listening on 0.0.0.0:{args.n1mm_port} "
                  f"(unicast/broadcast; use --n1mm-group for multicast)")

    if not args.no_presence:
        def _on_conflict(peers):
            print("\n" + P.format_conflict_message(peers), file=sys.stderr)
            print("Demoting: another site server appeared on the LAN. Exiting.",
                  file=sys.stderr)
            # Hard exit from daemon thread — dual primary is worse than a drop.
            os._exit(2)

        announcer = P.PresenceAnnouncer(
            iface=args.iface,
            http_port=args.http_port,
            instance_id=instance_id,
            group=args.presence_group,
            port=args.presence_port,
            on_conflict=_on_conflict,
        )
        announcer.start()
        n_paths = len(P.announce_destinations(
            group=args.presence_group, port=args.presence_port, iface=args.iface))
        print(f"  presence announce {args.presence_group}:{args.presence_port} "
              f"+ broadcast ~1 Hz via {console_ip} "
              f"({n_paths} send paths; plane E zero-memory discovery)")
        if args.iface in ("0.0.0.0", "127.0.0.1"):
            print(f"  NOTE: prefer --iface {console_ip} (contest LAN) so radio UDP "
                  f"joins the right NIC (presence already multi-homed)")
    else:
        print("  presence announce disabled (--no-presence)")

    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        if announcer is not None:
            announcer.stop()


if __name__ == "__main__":
    main()