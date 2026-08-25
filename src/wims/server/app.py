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

# Client went away mid-request (browser refresh, agent kill, firewall). Not a server bug.
_CLIENT_GONE = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wims.udp import messages as M  # noqa: E402
from wims.udp.sink import open_socket  # noqa: E402
from wims.discovery.fleet import FleetTracker  # noqa: E402
from wims.interlock.arbiter import OverlapDetector, TxArbiter  # noqa: E402
from wims.udp.controller import TxController  # noqa: E402
from wims.udp.gt_bridge import (  # noqa: E402
    DEFAULT_GT_BRIDGE_PORT, DEFAULT_GT_FORWARD_PORT, GridTrackerBridge,
    is_loopback_host, parse_host_port)
from wims.integrations.rotator import RotatorRegistry  # noqa: E402
from wims.udp.activity import ActivityMap  # noqa: E402
from wims.engine import scoring as S  # noqa: E402
from wims.engine.roster import RosterBuilder  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402
from wims.state import last_log as last_log_pref  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso, id_from_contactdelete  # noqa: E402
from wims.server.state import (  # noqa: E402
    fleet_to_dict, interlock_to_dict, roster_to_dict, activity_to_dict,
    decodes_to_dict, n1mm_sync_to_dict, agents_to_dict, tx_to_dict,
    rotators_to_dict)

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
        self._seed_scan_dirs: list[str] = []       # last multi-path scan roots (UserDir etc.)
        self._active_contest: dict | None = None   # ContestInfo.to_dict() currently loaded
        self._contest_catalog: list = []           # all discovered contests for UI
        # Seat agents (config audit heartbeats) — agent_id -> last report.
        self._agents: dict[str, dict] = {}
        self._agent_prune_after = 300.0            # drop silent agents after 5 min
        # Rotators (plan §2.10 / §3.8) — sim and/or agent-reported status.
        self._rotators = RotatorRegistry()
        self._last_rot_action: dict | None = None
        # Rate-limit id-collision warnings (two VMs same --rig-name / UDP id).
        self._id_collision_warn_ts: dict[str, float] = {}
        # Experimental GridTracker merge bridge (see --gt-forward).
        self._gt_bridge: GridTrackerBridge | None = None

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
            self._seed_scan_dirs = list(disc.get("scan_dirs") or [])
        return disc["contests"]

    def seed_scan_dirs(self) -> list[str]:
        """Folders last scanned for N1MM .s3db (empty until first discover)."""
        with self._lock:
            return list(self._seed_scan_dirs)

    def seed_from_db(self, db_path: str, *, contest_nr: int | None = None,
                     contest_name: str | None = None,
                     remember: bool = False,
                     selection: str | None = None) -> int:
        """Pull one N1MM contest log into the log copy (§3.6). Read-only.

        When the .s3db holds multiple contests (June + Sept VHF…), pass contest_nr
        (preferred) so only that ContestInstance's DXLOG rows load.

        ``remember=True`` persists this choice for the next server start on this
        host (Setup picker / explicit ``--seed-db``). Auto heuristic picks do not
        remember, so a casual DX log chosen once is not overwritten by June VHF.
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
        if active is not None:
            # Always stamp the path we actually opened (list_contests may omit it).
            active = {**active, "db_path": db_path,
                      "db_label": active.get("db_label") or Path(db_path).name}
        sel = selection or ("manual" if remember else "auto")
        with self._lock:
            self._log.reconcile(qsos)
            self._seed = {
                "count": len(qsos),
                "source": Path(db_path).name,
                "db_path": db_path,
                "contest_nr": contest_nr if contest_nr is not None
                              else (active or {}).get("contest_nr"),
                "contest_name": (active or {}).get("contest_name") or contest_name,
                "label": (active or {}).get("label"),
                "selection": sel,
            }
            self._active_contest = active
            self._seed_db_hint = db_path
        if remember and active is not None:
            last_log_pref.save({
                "db_path": db_path,
                "contest_nr": active.get("contest_nr"),
                "contest_name": active.get("contest_name"),
                "db_label": active.get("db_label") or Path(db_path).name,
                "label": active.get("label"),
            })
        return len(qsos)

    def auto_seed(self) -> dict:
        """Discover contests; prefer last operator choice, else latest with QSOs.

        Returns a small status dict for startup logging / API. Never raises on
        empty discovery — log copy stays empty and UI offers a picker.

        Selection order:
          1. Host-local last log (Setup pick / prior ``--seed-db``) if still present
          2. ``pick_contest`` heuristic (latest real StartDate with QSOs)
        """
        from wims.integrations.n1mm import logdb
        disc = logdb.discover(self._seed_db_dir, self._seed_db_hint)
        with self._lock:
            self._contest_catalog = disc["contests"]
            self._seed_scan_dirs = list(disc.get("scan_dirs") or [])
        contests = disc["contests"]
        scan_dirs = disc.get("scan_dirs") or []

        pref = last_log_pref.load()
        if pref and last_log_pref.is_db_usable(pref.get("db_path") or ""):
            match = last_log_pref.match_in_catalog(pref, contests)
            if match is None and last_log_pref.is_db_usable(pref["db_path"]):
                # File exists but catalog filter missed it — seed directly.
                try:
                    n = self.seed_from_db(
                        pref["db_path"],
                        contest_nr=(int(pref["contest_nr"])
                                    if pref.get("contest_nr") is not None
                                    else None),
                        contest_name=pref.get("contest_name"),
                        remember=False,
                        selection="remembered",
                    )
                    with self._lock:
                        active = self._active_contest
                    return {"ok": True, "seeded": n, "contest": active or pref,
                            "source": "remembered",
                            "contests": contests, "scan_dirs": scan_dirs}
                except Exception:
                    match = None
            if match is not None:
                n = self.seed_from_db(
                    match["db_path"],
                    contest_nr=match.get("contest_nr"),
                    remember=False,
                    selection="remembered",
                )
                return {"ok": True, "seeded": n, "contest": match,
                        "source": "remembered",
                        "contests": contests, "scan_dirs": scan_dirs}

        rec = disc.get("recommended")
        if not rec:
            return {"ok": False, "reason": "no_contests_with_qsos",
                    "contests": contests, "scan_dirs": scan_dirs,
                    "source": "auto"}
        n = self.seed_from_db(rec["db_path"], contest_nr=rec["contest_nr"],
                              remember=False, selection="auto")
        return {"ok": True, "seeded": n, "contest": rec, "source": "auto",
                "contests": contests, "scan_dirs": scan_dirs}

    def select_contest(self, *, db_path: str, contest_nr: int) -> dict:
        """Operator picked a contest in Setup — reload log copy and remember it."""
        n = self.seed_from_db(db_path, contest_nr=int(contest_nr),
                              remember=True, selection="manual")
        self.refresh_contest_catalog()
        with self._lock:
            active = self._active_contest
        return {"ok": True, "seeded": n, "contest": active,
                "remembered": True}

    def seed_explicit_db(self, db_path: str) -> dict:
        """CLI ``--seed-db``: load best contest in that file and remember it.

        Unlike auto-discover, other .s3db files (e.g. N2OY June) do not compete.
        """
        from wims.integrations.n1mm import logdb
        path = str(Path(db_path).expanduser())
        if not Path(path).is_file():
            return {"ok": False, "reason": "db_not_found", "db_path": path}
        try:
            contests = logdb.list_contests(path)
        except Exception as e:
            return {"ok": False, "reason": str(e), "db_path": path}
        # Catalog still useful for Setup; include full discovery roots.
        try:
            self.refresh_contest_catalog()
        except Exception:
            with self._lock:
                self._contest_catalog = [c.to_dict() for c in contests]
        pick = logdb.pick_contest(contests)
        if pick is None:
            # Empty contests: still try whole-file seed if DXLOG has rows.
            n = self.seed_from_db(path, remember=True, selection="cli")
            if n == 0:
                return {"ok": False, "reason": "no_contests_with_qsos",
                        "db_path": path, "contests": [c.to_dict() for c in contests]}
            with self._lock:
                active = self._active_contest
            return {"ok": True, "seeded": n, "contest": active, "source": "cli",
                    "contests": [c.to_dict() for c in contests]}
        n = self.seed_from_db(path, contest_nr=pick.contest_nr,
                              remember=True, selection="cli")
        return {"ok": True, "seeded": n, "contest": pick.to_dict(),
                "source": "cli",
                "contests": [c.to_dict() for c in contests]}

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
            # Optional rotators[] on the agent report → live Az ant on roster.
            n_rot = self._rotators.ingest_report(
                stored.get("rotators"), agent_id=agent_id, now=ts)
        summary = (stored.get("summary") or {})
        return {
            "ok": True,
            "agent_id": agent_id,
            "severity": summary.get("severity"),
            "message": summary.get("message"),
            "rotators_ingested": n_rot,
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

    def _tx_dests_for(self, instance_id: str) -> list[tuple[str, int]]:
        """Where to send Reply/Halt for this WSJT-X id.

        **Primary:** unicast to the last ``recvfrom`` source ``(ip, port)`` for that
        instance. WSJT-X MessageClient binds an *ephemeral* port and only receives
        control there — **not** on the configured UDP Server port (e.g. 2237).
        Sending Reply to ``host:2237`` reaches the group/listener, not MessageClient.

        **Fallback:** host IP + configured TX port (if we never saw a source port).
        **Secondary:** configured default (multicast group or ``--tx-host``).
        """
        dests: list[tuple[str, int]] = []
        port = int(self._tx.dest[1]) if self._tx else 2237
        node = self._tracker.nodes.get(instance_id)
        if node is not None:
            ctrl = getattr(node, "control_addr", None)
            if ctrl and ctrl[0] and int(ctrl[1]) > 0:
                dests.append((str(ctrl[0]), int(ctrl[1])))
            elif node.host_seen:
                ip = max(node.host_seen.items(), key=lambda kv: kv[1])[0]
                if ip:
                    dests.append((ip, port))
        if self._tx is not None:
            d = (str(self._tx.dest[0]), int(self._tx.dest[1]))
            if d not in dests:
                dests.append(d)
        return dests

    def work_station(self, row_id: str) -> dict:
        """Answer the station in roster row `row_id` — send Reply to its instance.

        Human initiation is the roster click (GridTracker2-style); no separate arm
        switch. Arbiter-gated (refuses if another instance in the same resource
        group holds TX). The actual `sendto` runs outside the lock so a slow
        socket never stalls the ingest thread.

        On success WIMS has only *sent* a WSJT-X Reply datagram — if DX Call / Enable
        Tx do not change in WSJT-X, the packet did not reach MessageClient (Accept UDP
        off, firewall, wrong dest, or decode too old in Band Activity).
        """
        if self._tx is None:
            return {"ok": False, "error": "tx_disabled",
                    "detail": "Server started with --no-tx (read-only). Restart without --no-tx."}
        with self._lock:
            entry = self._roster.entry_for(row_id)
            if entry is None:
                return {"ok": False, "error": "unknown_row",
                        "detail": "Row aged out or unknown — wait for a fresh decode, then Work again."}
            decode = entry.decode
            inst = getattr(decode, "id", None) or "?"
            node = self._tracker.nodes.get(inst)
            # Safety: never Reply a decode from another band/dial — WSJT-X would Enable
            # Tx on the *current* VFO and call the station on the wrong RF.
            cur_band = (node.band if node else None) or ""
            row_band = entry.band or ""
            if (cur_band and row_band and cur_band != "?" and row_band != "?"
                    and cur_band != row_band):
                return {
                    "ok": False, "error": "band_mismatch",
                    "band_row": row_band, "band_now": cur_band,
                    "detail": (
                        f"Row is {row_band} but {inst!r} is on {cur_band}. "
                        "Work only same-band lines (or QSY WSJT-X back first)."
                    ),
                }
            cur_dial = int(node.dial_hz) if node and node.dial_hz else 0
            row_dial = int(entry.dial_hz or 0)
            # ~3 kHz: same FT8 footprint; larger = instance dialed away within the band.
            if cur_dial and row_dial and abs(cur_dial - row_dial) > 3000:
                return {
                    "ok": False, "error": "dial_mismatch",
                    "dial_row": row_dial, "dial_now": cur_dial,
                    "detail": (
                        f"Decode was at dial {row_dial} Hz; instance is now {cur_dial} Hz. "
                        "Work a line heard on the current dial."
                    ),
                }
            if not self._arbiter.request(inst):
                holder = self._arbiter.holder(self._arbiter.group_of(inst))
                return {"ok": False, "error": "group_busy", "holder": holder,
                        "detail": f"Another instance holds TX in this group ({holder}). Halt first."}
            call = (getattr(decode, "dx_call", "") or "").upper()
            grid = (getattr(decode, "grid", "") or "") or ""
            msg_text = getattr(decode, "message", "") or ""
            df = int(getattr(decode, "delta_frequency", 0) or 0)
            schema = int(getattr(decode, "schema", None) or 2)
            # CQ / QRZ / 73 → Reply alone sets double-click + Enable Tx.
            # Mid-exchange lines need Configure to force DX Call/Grid fill, and
            # Hold Tx Freq (in WSJT-X) for Reply to Enable Tx (replyToCQ rules).
            auto_tx = M.reply_auto_tx_eligible(msg_text)
            dests = self._tx_dests_for(inst)
            age_hint = ""
            # Warn if decode may be older than WSJT-X keeps (Reply needs a live match).
            try:
                age_s = time.time() - float(entry.last_seen)
                if age_s > 90:
                    age_hint = (
                        f" Decode is {age_s:.0f}s old — WSJT-X may have dropped it; "
                        "Work a *fresh* line still on Band Activity."
                    )
            except Exception:
                pass
        sent_parts = ["reply"]
        try:
            self._tx.reply(inst, decode, dests=dests)
            if not auto_tx and call:
                # GT2 secondary path: Configure fills DX/grid + Gen Std Msgs without
                # inventing a synthetic CQ (design: no fake CQ over UDP).
                self._tx.configure(
                    inst, dx_call=call, dx_grid=grid,
                    rx_df=(df if df > 0 else None),
                    generate_messages=True, schema=schema, dests=dests,
                )
                sent_parts.append("configure")
        except OSError as e:
            with self._lock:
                self._arbiter.release(inst)
            print(f"TX Work FAIL {inst} {call} dests={dests}: {e}", flush=True)
            return {"ok": False, "error": f"send_failed: {e}",
                    "detail": f"UDP send to {dests} failed — check --tx-host/--iface and firewall."}
        dest_s = ", ".join(f"{h}:{p}" for h, p in dests)
        print(f"TX Work ok {inst!r} {call!r} msg={msg_text!r} "
              f"via={'+'.join(sent_parts)} → [{dest_s}]", flush=True)
        mid_hint = ""
        if not auto_tx:
            mid_hint = (
                " Non-CQ line: Configure filled DX Call/Grid + Gen Msgs; "
                "Enable Tx from Reply needs WSJT-X **Hold Tx Freq** checked "
                "(or Work a CQ/73 line)."
            )
        with self._lock:
            self._last_tx_action = {
                "action": "work", "instance": inst, "call": call,
                "message": msg_text, "dests": dests, "sent": sent_parts,
                "ts": time.time(),
            }
        return {
            "ok": True, "sent": "+".join(sent_parts), "instance": inst,
            "call": call, "message": msg_text, "dest": dests[0] if dests else None,
            "dests": dests, "auto_tx_eligible": auto_tx,
            "detail": (
                f"Work {call} on id={inst!r} via {'+'.join(sent_parts)} → [{dest_s}]."
                + mid_hint + age_hint
            ),
        }

    def halt(self, instance: str | None = None) -> dict:
        """Stop transmitting — the panic button. Halts one instance or every live
        one, and releases the arbiter so the group frees immediately."""
        if self._tx is None:
            return {"ok": False, "error": "tx_disabled"}
        with self._lock:
            targets = [instance] if instance else [n.id for n in self._tracker.nodes.values()]
            dest_map = {inst: self._tx_dests_for(inst) for inst in targets}
        halted = []
        for inst in targets:
            try:
                self._tx.halt(inst, dests=dest_map.get(inst))
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

    def observe_wsjtx(self, msg, now, src_ip, src_port=None):
        with self._lock:
            self.wsjt_pkts += 1
            mid = getattr(msg, "id", None) or "?"
            # Per-host band before Status — QSY only if *this* host changed band.
            old_band_here = None
            if isinstance(msg, M.Status) and src_ip:
                n_prev = self._tracker.nodes.get(mid)
                if n_prev is not None:
                    old_band_here = (n_prev.band_by_host or {}).get(src_ip)
            self._tracker.observe(msg, now, src_ip=src_ip, src_port=src_port)
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
                node = self._tracker.nodes.get(mid)
                new_band = node.band if node else None
                # Fill in rows that were heard before the first Status (band was "?").
                if new_band and new_band != "?":
                    self._roster.reband_unknown(mid, new_band)
                # Two hosts sharing one UDP id (default "WSJT-X" on both VMs) alternate
                # Status 6m/2m — that is NOT a QSY. Never drop roster for that case.
                multi = bool(node and node.id_collision_at(now))
                if multi:
                    last = self._id_collision_warn_ts.get(mid, 0.0)
                    if now - last > 60.0:
                        self._id_collision_warn_ts[mid] = now
                        hosts = sorted(node.hosts_recent(now)) if node else []
                        print(
                            f"roster: id {mid!r} from multiple hosts {hosts} — "
                            f"set unique WSJT-X --rig-name on each VM "
                            f"(not a band QSY; roster not cleared)",
                            flush=True,
                        )
                elif (old_band_here and old_band_here != "?"
                      and new_band and new_band != "?"
                      and old_band_here != new_band):
                    # Same host really QSYed.
                    n_drop = self._roster.drop_other_bands(mid, new_band)
                    print(f"roster: QSY {mid!r} from {src_ip} "
                          f"{old_band_here}→{new_band} "
                          f"dropped {n_drop} other-band row(s)", flush=True)
            elif isinstance(msg, M.Decode):
                node = self._tracker.nodes.get(mid)
                # Prefer this host's last known band when the same id is shared.
                band = "?"
                if node is not None:
                    if src_ip and (node.band_by_host or {}).get(src_ip):
                        band = node.band_by_host[src_ip]
                    elif node.band:
                        band = node.band
                self._roster.observe_decode(
                    msg, band, now,
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
            self._tracker.prune_loggers(now)
            d = fleet_to_dict(self._tracker, now,
                              wsjt_pkts=self.wsjt_pkts, n1mm_pkts=self.n1mm_pkts)
            tx_ids = {n.id for n in self._tracker.nodes.values() if n.transmitting}
            d["interlock"] = interlock_to_dict(
                self._overlap, self.group_of, self._grouping,
                list(self._tracker.nodes), tx_ids, now)
            ctx = S.Context(weights=S.weights_for(self._condition), condition=self._condition)
            rows, not_needed = self._roster.ranked(now, ctx)
            self._rotators.tick_sims(now)
            d["roster"] = roster_to_dict(rows, not_needed, now,
                                         condition=self._condition,
                                         strategy=self._roster.strategy.name,
                                         nodes=self._tracker.nodes,
                                         rotators=self._rotators)
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
                last_resync=self._last_resync,
                scan_dirs=self._seed_scan_dirs)
            self._prune_agents(now)
            d["agents"] = agents_to_dict(self._agents, now)
            d["tx"] = tx_to_dict(
                enabled=self._tx is not None,
                controller_dest=(self._tx.dest if self._tx else None),
                holders=self._arbiter.holders(),
                enable_cq=self._enable_cq,
                last_action=self._last_tx_action)
            d["rotators"] = rotators_to_dict(self._rotators, now)
            d["rotator_last_action"] = self._last_rot_action
            d["gt_bridge"] = (
                self._gt_bridge.status_dict() if self._gt_bridge is not None else None)
            return d

    def point_rotator(self, *, rotator_id: str | None = None,
                      instance: str | None = None,
                      az: float | None = None,
                      row_id: str | None = None) -> dict:
        """Human click-to-point: set rotator to az, or to roster row Az DX."""
        from wims.engine.geo import bearing
        with self._lock:
            rid = (rotator_id or "").strip() or None
            if row_id:
                entry = self._roster.entry_for(row_id)
                if entry is None:
                    return {"ok": False, "error": "unknown_row",
                            "detail": "Roster row gone — pick a fresh line."}
                inst = getattr(entry.decode, "id", None) or "?"
                grid = getattr(entry.decode, "grid", None)
                az_dx = bearing(entry.de_grid, grid)
                if az_dx is None:
                    return {"ok": False, "error": "no_bearing",
                            "detail": "Need de_grid + DX grid for Az DX."}
                az = az_dx
                if not rid:
                    rst = self._rotators.for_instance(inst)
                    rid = rst.id if rst else None
                    if not rid:
                        return {"ok": False, "error": "no_rotator",
                                "detail": f"No rotator mapped to instance {inst!r}."}
            elif instance and not rid:
                rst = self._rotators.for_instance(instance)
                rid = rst.id if rst else None
                if not rid:
                    return {"ok": False, "error": "no_rotator",
                            "detail": f"No rotator mapped to instance {instance!r}."}
            if rid is None:
                return {"ok": False, "error": "need_rotator",
                        "detail": "Provide rotator_id, instance, or row_id."}
            if az is None:
                return {"ok": False, "error": "need_az",
                        "detail": "Provide az degrees or a row_id with Az DX."}
            result = self._rotators.point(rid, float(az))
            if result.get("ok"):
                self._last_rot_action = {
                    "action": "point", "rotator": rid, "az": result.get("az"),
                    "ts": time.time(),
                }
            return result

    def stop_rotator(self, rotator_id: str | None = None) -> dict:
        with self._lock:
            result = self._rotators.stop(rotator_id)
            self._last_rot_action = {
                "action": "stop", "halted": result.get("halted"), "ts": time.time(),
            }
            return result


def ingest_loop(live: LiveFleet, wsjt_socks: list, s_n1mm: socket.socket | None,
                gt_bridge: GridTrackerBridge | None = None):
    """Ingest WSJT-X on band ports + optional N1MM + optional GridTracker bridge."""
    if not isinstance(wsjt_socks, (list, tuple)):
        wsjt_socks = [wsjt_socks]
    wsjt_set = {s for s in wsjt_socks if s is not None}
    socks = list(wsjt_set)
    if s_n1mm is not None:
        socks.append(s_n1mm)
    gt_sock = gt_bridge.sock if gt_bridge is not None else None
    if gt_sock is not None:
        socks.append(gt_sock)
    while True:
        ready, _, _ = select.select(socks, [], [], 1.0)
        now = time.time()
        for s in ready:
            try:
                data, addr = s.recvfrom(65535)
            except OSError:
                continue
            if gt_sock is not None and s is gt_sock:
                # GT Call Roster click (Reply/Halt/…) or other traffic to bridge port.
                gt_bridge.handle_gt_datagram(data, addr, now=now)
            elif s in wsjt_set:
                msg = M.parse(data)
                if msg is not None:
                    # addr[1] is MessageClient's ephemeral control port — required for Reply.
                    live.observe_wsjtx(msg, now, addr[0], addr[1])
                # Forward raw bytes even if parse failed (GT may still want them).
                if gt_bridge is not None and data:
                    gt_bridge.forward_wsjt(data, now=now)
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
                    "scan_dirs": live.seed_scan_dirs(),
                })
            elif path == "/api/agents":
                self._send_json(200, {"agents": live.list_agents()})
            elif path == "/api/gt-bridge":
                b = live._gt_bridge
                if b is None:
                    self._send_json(200, {"ok": False, "enabled": False,
                                          "detail": "start server with --gt-forward HOST:PORT"})
                else:
                    self._send_json(200, {"ok": True, "enabled": True, **b.status_dict()})
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
                    self._send_json(200, {
                        "ok": True,
                        "contests": contests,
                        "scan_dirs": live.seed_scan_dirs(),
                    })
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
            elif path == "/api/rotator/point":
                # Click-to-point: {row_id} or {rotator_id|instance, az}
                try:
                    result = live.point_rotator(
                        rotator_id=body.get("rotator_id") or body.get("id"),
                        instance=body.get("instance"),
                        az=body.get("az"),
                        row_id=body.get("row_id"),
                    )
                    code = 200 if result.get("ok") else 400
                    self._send_json(code, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
            elif path == "/api/rotator/stop":
                try:
                    result = live.stop_rotator(body.get("rotator_id") or body.get("id"))
                    self._send_json(200, result)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
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


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that does not dump a full traceback when the peer aborts."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_GONE) or (
            isinstance(exc, OSError)
            and getattr(exc, "winerror", None) in (10053, 10054, 10038)
        ):
            # WinError 10053 = aborted by host software; 10054 = reset by peer
            return
        # Real bugs: keep default logging behavior
        super().handle_error(request, client_address)


def main() -> None:
    from wims.discovery import presence as P

    ap = argparse.ArgumentParser(description="WIMS server (ingest + console).")
    # Fleet defaults: join all band streams (wims_networking §4.3). Port 2240 skipped —
    # reserved / often held by N1MM on Windows (networking §4.9). Solo uses 2237 only.
    # Escape hatch: --ports 2237 or --ports 2237,2238,...
    FLEET_WSJT_PORTS = "2237,2238,2239,2241,2242,2243"  # 50/144/222/432/902/1296; no 2240
    ap.add_argument("--http-port", type=int, default=8787)
    ap.add_argument("--iface", default="0.0.0.0",
                    help="multicast join interface (0.0.0.0 = auto contest LAN IP; "
                         "set explicitly only if the wrong NIC is chosen)")
    ap.add_argument("--group", default="224.0.0.73", help="WSJT-X multicast group")
    ap.add_argument("--port", type=int, default=2237,
                    help=argparse.SUPPRESS)  # legacy; prefer --ports
    ap.add_argument("--ports", default=FLEET_WSJT_PORTS,
                    help=f"WSJT-X band ports (default {FLEET_WSJT_PORTS} = "
                         "50→2237 … 1296→2243; 2240 unused). "
                         "Only change for lab; seats never need this.")
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
    ap.add_argument("--gt-forward", default=None, metavar="HOST:PORT",
                    help="EXPERIMENTAL: forward every WSJT-X UDP datagram to GridTracker "
                         f"at HOST:PORT (default port {DEFAULT_GT_FORWARD_PORT}). "
                         "Example: --gt-forward 127.0.0.1:22370  "
                         "(GT Receive UDP = that port). "
                         f"WIMS reverse-bind defaults to {DEFAULT_GT_BRIDGE_PORT} "
                         "(must differ from GT port on the same host)")
    ap.add_argument("--gt-bridge-port", type=int, default=DEFAULT_GT_BRIDGE_PORT,
                    help=f"local UDP port WIMS binds for GT Reply return path "
                         f"(default {DEFAULT_GT_BRIDGE_PORT}). On same host as GT, "
                         f"do NOT use the same port as --gt-forward")
    ap.add_argument("--no-gt-control", action="store_true",
                    help="with --gt-forward: do not relay GT→WSJT control (Reply/Halt); "
                         "forward decodes only")
    ap.add_argument("--enable-cq-freetext", action="store_true",
                    help="EXPERIMENTAL: allow Call CQ via one-shot WSJT-X FreeText "
                         "(no auto-sequence; pending live verify). Off by default.")
    ap.add_argument("--seed-db", default=None,
                    help="N1MM contest .s3db to seed from (read-only); loads the best "
                         "contest in THAT file only and remembers it for next start. "
                         "If omitted: last Setup pick, else auto-find latest contest")
    # Default prefers UserDir\\Databases / home\\Databases when present (many N1MM
    # installs); also_standard discovery still scans all known roots on Rescan.
    from wims.integrations.n1mm import logdb as _logdb_cli  # noqa: E402
    ap.add_argument("--seed-db-dir",
                    default=_logdb_cli.default_seed_db_dir(),
                    help="dir to auto-find contest .s3db files (default: first existing "
                         "UserDir/home/Documents N1MM Databases folder)")
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
    ap.add_argument("--sim-rotator", action="append", default=[], metavar="SPEC",
                    help="lab simulator: id[:az][:instance,...]  e.g. ROT-6M:45:WSJT-X "
                         "(repeatable). Enables Az ant / Δaz / click-to-point without K3NG.")
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
    # Lab rotators: --sim-rotator id[:az][:inst1,inst2]
    for spec in (args.sim_rotator or []):
        parts = str(spec).split(":")
        rid = (parts[0] or "SIM-ROT").strip()
        az0 = 0.0
        insts: list[str] = []
        if len(parts) >= 2 and parts[1].strip():
            try:
                az0 = float(parts[1])
            except ValueError:
                insts = [x.strip() for x in parts[1].split(",") if x.strip()]
        if len(parts) >= 3 and parts[2].strip():
            insts = [x.strip() for x in parts[2].split(",") if x.strip()]
        live._rotators.ensure_sim(rid, az=az0, instances=insts, label=rid)

    # Seed before opening sockets so the first browser load already has the log.
    # Operator-facing lines are printed after the console URL (below).
    seed_lines: list[str] = []
    if not args.no_seed:
        # Order: explicit --seed-db (that file only + remember) → last Setup pick
        # → auto latest contest. Operator can always change on Setup.
        try:
            if args.seed_db:
                result = live.seed_explicit_db(args.seed_db)
            else:
                result = live.auto_seed()
            if result.get("ok"):
                c = result.get("contest") or {}
                src = result.get("source") or "auto"
                # label() already includes QSO count (e.g. ARRLVHFJUN · date · N QSOs).
                how = {"remembered": "remembered", "cli": "from --seed-db",
                       "auto": "auto", "manual": "manual"}.get(src, src)
                seed_lines.append(
                    f"  Log: {c.get('db_label') or Path(c.get('db_path') or '').name}"
                    f" · {c.get('label') or c.get('contest_name')}"
                    f" ({how})"
                )
                others = [x for x in result.get("contests") or []
                          if x.get("qso_count", 0) > 0
                          and (x.get("db_path") != c.get("db_path")
                               or x.get("contest_nr") != c.get("contest_nr"))]
                if others and src != "cli":
                    seed_lines.append(
                        f"  Log: {len(others)} other contest(s) available — pick on Setup"
                    )
            else:
                seed_lines.append(
                    "  Log: no contest with QSOs found — add an N1MM .s3db or open Setup"
                )
                scanned = result.get("scan_dirs") or live.seed_scan_dirs()
                if scanned:
                    seed_lines.append("  Log scan: " + "; ".join(scanned[:4])
                                      + ("…" if len(scanned) > 4 else ""))
                if result.get("reason") == "db_not_found":
                    seed_lines.append(
                        f"  Log: --seed-db not found: {result.get('db_path')}"
                    )
        except Exception as e:
            seed_lines.append(f"  Log: seed skipped ({e})")
    else:
        live.refresh_contest_catalog()
    # Open the ingest sockets here (not inside the thread) so a bind failure is
    # reported on the main path and the bound addresses are confirmed deterministically.
    try:
        wsjt_ports = [int(p.strip()) for p in str(args.ports).split(",") if p.strip()]
    except ValueError:
        ap.error(f"invalid --ports {args.ports!r}: use comma-separated integers "
                 f"(e.g. 2237,2238)")
    if not wsjt_ports:
        # Legacy: bare --port with empty --ports edge case
        wsjt_ports = [int(args.port)]
    # Resolve 0.0.0.0 → contest LAN for IGMP join (else remote WSJT-X never arrives).
    mcast_iface = args.iface
    if mcast_iface in ("0.0.0.0", "::", ""):
        mcast_iface = P._primary_lan_ip("0.0.0.0") or "0.0.0.0"
    s_wsjt_list: list = []
    for p in wsjt_ports:
        try:
            s_wsjt_list.append(open_socket(mcast_iface, p, args.group))
        except OSError as e:
            print(f"  WARNING: WSJT-X UDP {args.group}:{p} bind failed ({e}); skipping",
                  file=sys.stderr)
    if not s_wsjt_list:
        ap.error("no WSJT-X UDP ports could be bound — check --ports / --iface")
    s_n1mm = None
    if args.n1mm_port:
        # N1MM External Broadcast XML is usually unicast/directed to host:12060, but
        # multi-host fleets can multicast it (e.g. 224.0.0.73:12060 — same group as
        # WSJT-X, different port). Multicast needs a real interface for IGMP join:
        # --iface 127.0.0.1 only receives loopback multicasts, not LAN traffic from a VM.
        try:
            if args.n1mm_group:
                # Prefer real LAN IP for IGMP when --iface is all-zeros.
                n1mm_iface = args.iface
                if n1mm_iface in ("0.0.0.0", "::", ""):
                    n1mm_iface = mcast_iface
                s_n1mm = open_socket(n1mm_iface, args.n1mm_port, args.n1mm_group)
            else:
                # Unicast/broadcast: bind all interfaces so a LAN N1MM host is not
                # dropped when --iface is loopback for the WSJT-X emulator path.
                s_n1mm = open_socket("0.0.0.0", args.n1mm_port, None)
        except OSError as e:
            print(f"  WARNING: N1MM listener :{args.n1mm_port} bind failed ({e}); "
                  f"N1MM ingest off", file=sys.stderr)

    gt_bridge: GridTrackerBridge | None = None
    if args.gt_forward:
        try:
            gt_host, gt_port = parse_host_port(args.gt_forward)
        except ValueError as e:
            ap.error(f"invalid --gt-forward {args.gt_forward!r}: {e}")
        bind_port = int(args.gt_bridge_port)
        # Same host + same port → packets loop into WIMS; GT starves (observed live).
        if gt_port == bind_port and (
                is_loopback_host(gt_host)
                or gt_host in ("0.0.0.0", "", P._primary_lan_ip(args.iface) or "")):
            ap.error(
                f"--gt-forward port {gt_port} equals --gt-bridge-port {bind_port} "
                f"on this host: WIMS and GridTracker cannot share one UDP port. "
                f"Use e.g. --gt-forward 127.0.0.1:{DEFAULT_GT_FORWARD_PORT} "
                f"--gt-bridge-port {DEFAULT_GT_BRIDGE_PORT} "
                f"(GT Receive={DEFAULT_GT_FORWARD_PORT}, WIMS reverse={DEFAULT_GT_BRIDGE_PORT})")
        try:
            gt_bridge = GridTrackerBridge(
                gt_host, gt_port,
                bind_host="0.0.0.0",
                bind_port=bind_port,
                control_enabled=not args.no_gt_control,
                control_addr_for=lambda mid: live._tx_dests_for(mid),
            )
            live._gt_bridge = gt_bridge
        except OSError as e:
            ap.error(f"GT bridge bind 0.0.0.0:{bind_port} failed: {e} "
                     f"(is another process using that port?)")

    threading.Thread(target=ingest_loop, daemon=True,
                     args=(live, s_wsjt_list, s_n1mm, gt_bridge)).start()

    httpd = _QuietThreadingHTTPServer(
        ("0.0.0.0", args.http_port), make_handler(live, args.refresh)
    )
    console_ip = P._primary_lan_ip(args.iface)
    # Operator banner: one URL (open this), log status, how to stop.
    # Bind/conflict warnings above go to stderr only when something is wrong.
    if console_ip and console_ip not in ("127.0.0.1", "0.0.0.0"):
        print(f"WIMS server  http://{console_ip}:{args.http_port}/")
    else:
        print(f"WIMS server  http://localhost:{args.http_port}/")
    for line in seed_lines:
        print(line)
    if gt_bridge is not None:
        print(f"  GridTracker bridge → {gt_bridge.gt_dest[0]}:{gt_bridge.gt_dest[1]}  "
              f"(reverse :{gt_bridge.bind_port}; "
              f"control {'ON' if gt_bridge.control_enabled else 'OFF'})")
        print(f"  GT stats: http://localhost:{args.http_port}/api/gt-bridge")

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