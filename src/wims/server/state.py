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

"""Server state -> JSON — the durable console API contract (plan §3.12).

This is the stable boundary between the WIMS server and any operator console. It
is deliberately a plain dict/JSON shape with no framework or rendering assumptions,
so the frontend can be rewritten (plain HTML today, anything later) while this
contract — and everything behind it — stays put. Keep it additive and versioned.
"""

from __future__ import annotations

from wims.engine.geo import (
    bearing as _bearing, distance_km as _distance_km, base_call as _base_call,
    delta_az as _delta_az,
)

API_VERSION = 1


def _instance(n, now: float) -> dict:
    # id_collision uses a recent-host window so a desktop→VM move of the same
    # rig-name does not sticky-flag ⚠ id after the old source goes silent.
    collide = (n.id_collision_at(now) if hasattr(n, "id_collision_at")
               else n.id_collision)
    recent = sorted(n.hosts_recent(now)) if hasattr(n, "hosts_recent") else sorted(n.hosts)
    ctrl = getattr(n, "control_addr", None)
    return {
        "id": n.id,
        "host": n.host,
        "hosts": recent,   # live sources (debug / multi-host collision UI)
        # Ephemeral MessageClient port for Reply/Halt (ip:port from last recvfrom)
        "control": (None if not ctrl else {"host": ctrl[0], "port": int(ctrl[1])}),
        "band": n.band,
        "mode": n.mode,
        "dial_hz": n.dial_hz,
        "de_call": getattr(n, "de_call", None),
        "dx_call": getattr(n, "dx_call", None),
        "tx_enabled": bool(getattr(n, "tx_enabled", False)),
        "state": "TX" if n.transmitting else ("DEC" if n.decoding else "RX"),
        "transmitting": n.transmitting,
        "decodes_per_period": round(n.decodes_per_period(now), 1),
        "last_decode_age": None if n.last_decode is None else round(now - n.last_decode, 1),
        "heartbeat_age": None if n.last_heartbeat is None else round(now - n.last_heartbeat, 1),
        "health": n.health(now),
        "quiet": n.is_quiet(now),
        "id_collision": collide,
        "version": n.version,
    }


def _logger(lg, now: float) -> dict:
    aliases = sorted(getattr(lg, "aliases", None) or [])
    return {
        "id": lg.id,
        "kind": lg.kind,
        "host": lg.host,
        "hosts": sorted(getattr(lg, "hosts", None) or []),
        "aliases": aliases,  # NetBIOS / merged prior ids (one PC, one logger)
        "mycall": lg.mycall,
        "qso_count": lg.qso_count,
        "last_call": lg.last_call,
        "last_band": lg.last_band,
        "last_seen_age": None if lg.last_seen is None else round(now - lg.last_seen, 1),
        "last_qso_age": None if lg.last_qso is None else round(now - lg.last_qso, 1),
    }


def interlock_to_dict(detector, group_of, grouping: str,
                      node_ids, transmitting_ids, now: float) -> dict:
    """Snapshot the interlock / overlap state (plan §3.4 / §2.1) — the
    safety-critical headline: who is observed transmitting, grouped by shared
    resource, plus any overlap (>1 TX in a group) detected now or historically.

    `detector` is the live `OverlapDetector` (its `violations` list is the audit
    trail of every overlap ever observed). `group_of(id) -> group` maps each
    instance to its resource group; `grouping` is the human label for that scheme
    ("instance" / "band" / "host"). Overlap is impossible under "instance"
    grouping by construction — it becomes meaningful once instances genuinely
    share a transmitter/antenna/PA (from §3.14 profiles, not yet wired)."""
    tx = set(transmitting_ids)
    groups: dict[str, dict] = {}
    for nid in node_ids:
        g = group_of(nid)
        e = groups.setdefault(g, {"group": g, "instances": [], "transmitting": []})
        e["instances"].append(nid)
        if nid in tx:
            e["transmitting"].append(nid)

    glist = []
    overlap_now = False
    for g in sorted(groups):
        e = groups[g]
        e["instances"].sort()
        e["transmitting"].sort()
        e["overlap"] = len(e["transmitting"]) > 1
        overlap_now = overlap_now or e["overlap"]
        glist.append(e)

    last = detector.violations[-1] if detector.violations else None
    return {
        "grouping": grouping,
        "groups": glist,
        "tx_now": sorted(tx),
        "overlap_now": overlap_now,
        "violation_count": len(detector.violations),
        "last_violation": None if last is None else {
            "group": last.group,
            "instances": list(last.instances),
            "age": round(now - last.at, 1),
        },
    }


def roster_to_dict(scored_rows, not_needed: int, now: float,
                   *, condition: str, strategy: str,
                   nodes: dict | None = None,
                   rotators=None) -> dict:
    """Snapshot the GridTracker-style call roster (plan §3.5 / §2.2) for the console.

    Columns include **Az DX** (`az`), **Az ant** / **Δaz** when a rotator maps to the
    row's instance, **distance_km**, **is_calling_us**, **is_armed**. `rotators` is a
    `RotatorRegistry` (optional).
    """
    cands = []
    for sc, e in scored_rows:
        c = sc.candidate
        d = e.decode
        freq_hz = (e.dial_hz + d.delta_frequency) if e.dial_hz else None
        dist = _distance_km(e.de_grid, c.grid)
        az_dx = _bearing(e.de_grid, c.grid)
        node = (nodes or {}).get(c.instance_id) if nodes is not None else None
        de = getattr(node, "de_call", None) if node else None
        to = getattr(d, "to_call", None)
        # Calling us: exchange addressed to our call (not CQ). Base-call match.
        is_calling_us = bool(
            de and to and str(to).upper() not in ("CQ", "QRZ", "DE")
            and _base_call(to) == _base_call(de)
        )
        # Armed: WSJT-X Enable Tx with DX Call set to this row's station.
        is_armed = bool(
            node and getattr(node, "tx_enabled", False)
            and getattr(node, "dx_call", None)
            and _base_call(node.dx_call) == _base_call(c.call)
        )
        az_ant = None
        rotator_moving = False
        rotator_id = None
        if rotators is not None:
            rst = rotators.for_instance(c.instance_id)
            if rst is not None and rst.az is not None:
                az_ant = round(float(rst.az))
                rotator_moving = bool(rst.moving)
                rotator_id = rst.id
        daz = _delta_az(az_ant, az_dx)
        cands.append({
            "id": f"{c.instance_id}|{c.call}|{c.grid or ''}",  # stable row id → click-to-work
            "call": c.call,
            "to_call": d.to_call,                  # "calling" column
            "grid": c.grid,
            "band": c.band,
            "mode": d.mode,
            "instance": c.instance_id,
            "operator_call": None,                 # §3.14 profile stub (band manager)
            "snr": c.snr,
            "freq_hz": freq_hz,
            "az": None if az_dx is None else round(az_dx),           # Az DX
            "az_ant": az_ant,                                         # live antenna
            "delta_az": None if daz is None else round(daz),
            "rotator_moving": rotator_moving,
            "rotator_id": rotator_id,
            "distance_km": None if dist is None else round(dist, 1),
            "score": round(sc.total, 1),
            "is_needed": not c.is_dupe,
            "is_cq": c.is_cq,
            "is_dupe": c.is_dupe,
            "is_new_mult": c.is_new_mult,
            "is_rover": c.is_rover,
            "is_calling_us": is_calling_us,
            "is_armed": is_armed,
            "ts": e.last_seen,                     # epoch (Age shown in UI; UTC column dropped)
            "age": round(now - e.last_seen, 1),
            "factors": [{"name": f.name, "contribution": round(f.contribution, 1),
                         "detail": f.detail} for f in sc.factors],
        })
    return {
        "condition": condition,
        "strategy": strategy,
        "count": len(cands),
        "needed": sum(1 for x in cands if x["is_needed"]),
        "not_needed": not_needed,
        "candidates": cands,
    }


def rotators_to_dict(registry, now: float) -> list:
    """Status / Operate `rotators` block (plan §2.10)."""
    if registry is None:
        return []
    registry.refresh_health(now)
    out = []
    for st in sorted(registry.all(), key=lambda s: s.id):
        age = None if not st.ts else round(now - st.ts, 1)
        out.append({
            "id": st.id,
            "label": st.label or st.id,
            "az": None if st.az is None else round(float(st.az)),
            "el": None if st.el is None else round(float(st.el)),
            "target_az": None if st.target_az is None else round(float(st.target_az)),
            "moving": bool(st.moving),
            "health": st.health,
            "link_ok": bool(st.link_ok),
            "instances": list(st.instances or []),
            "source": st.source,
            "agent_id": st.agent_id,
            "soft_min": st.soft_min,
            "soft_max": st.soft_max,
            "age": age,
        })
    return out


def tx_to_dict(*, enabled: bool, controller_dest, holders: dict,
               enable_cq: bool, last_action=None) -> dict:
    """TX-control state for the Operate console (plan §3.2 / §4.5 / §2.12).

      * `enabled`   -> a TX controller is wired (False under --no-tx = read-only),
      * `can_tx`    -> same as enabled (roster click may Work; no global arm switch),
      * `controller`-> where Reply/Halt are sent (host, port),
      * `holders`   -> resource-group -> instance currently granted TX (arbiter),
      * `cq_enabled`-> experimental FreeText Call-CQ path (default off; see P3),
      * `last_action`-> last work/halt for a one-line UI status.

    Human initiation is the roster line click (GridTracker2-style), not a separate
    Enable/Disable TX master switch."""
    return {
        "enabled": bool(enabled),
        "can_tx": bool(enabled),
        "controller": (None if not controller_dest
                       else {"host": controller_dest[0], "port": controller_dest[1]}),
        "holders": dict(holders or {}),
        "cq_enabled": bool(enable_cq),
        "last_action": last_action,
    }


def activity_to_dict(amap, now: float | None = None) -> dict:
    """Snapshot one instance's decode-activity map (plan §2.5) — the df × cycle × SNR
    heatmap that confirms decodes are flowing without any screen capture. Cells carry
    raw best-SNR (or null = nothing decoded there); the console colors them.

    Pass `now` so empty periods fill in and the strip scrolls like WSJT-X even when
    no Decode UDP arrives.
    """
    rows = []
    for bucket, snrs in amap.recent_rows(now):
        secs = (bucket * amap.period_s) % 86400
        rows.append({
            "cycle": bucket,
            "label": f"{secs // 3600 % 24:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}",
            "snr": list(snrs),
        })
    return {
        "instance": amap.instance_id,
        "count": amap.count,
        "period_s": amap.period_s,
        "freq_max": amap.freq_max,
        "n_bins": amap.n_bins,
        "rows": rows,
    }


def decodes_to_dict(buffer, now: float, limit: int = 120) -> list:
    """Recent decodes across the whole fleet, newest first (plan §2.2 decode log).

    `buffer` is an iterable of stored decode dicts (ts/instance/snr/df/message/is_cq);
    we project them and ship the epoch `ts` so the console formats the clock."""
    items = list(buffer)[-limit:]
    items.reverse()
    return [{
        "ts": e["ts"],
        "instance": e["instance"],
        "snr": e["snr"],
        "df": e["df"],
        "message": e["message"],
        "is_cq": e["is_cq"],
    } for e in items]


def n1mm_sync_to_dict(now: float, *, n1mm_pkts: int, last_n1mm: float | None,
                      qso_count: int, last_qso: dict | None,
                      seed: dict | None = None, stale_after: float = 180.0,
                      active_contest: dict | None = None,
                      contests: list | None = None,
                      last_resync: dict | None = None) -> dict:
    """N1MM feed + log-copy freshness (plan §2.2 / §3.6).

    N1MM has **no heartbeat** — it only broadcasts on activity (logged QSO, spot,
    lookup) — so 'no recent packet' means quiet, not necessarily broken; the console
    wording reflects that. `qso_count`/`last_qso` describe WIMS's own log copy that
    feeds the roster's dupe/mult; `seed` records the startup `.s3db` read (count +
    source file) so the operator can see the existing log was pulled in even before
    any live broadcast.

    `last_resync` is the operator (or API) DXLOG re-read + reconcile summary — the
    safety net when UDP events were missed.

    `contests` / `active_contest` support multi-log .s3db files (June + Sept VHF…):
    the Status page lists human labels; no ContestNR knowledge required.
    """
    feed_age = None if last_n1mm is None else round(now - last_n1mm, 1)
    if last_n1mm is None:
        status = "none"                       # no N1MM datagram ever seen
    elif feed_age <= stale_after:
        status = "active"
    else:
        status = "idle"                       # seen before, quiet now (not a fault)
    resync = None
    if last_resync:
        ts = last_resync.get("ts")
        resync = {
            "age": None if ts is None else round(now - float(ts), 1),
            "upserted": last_resync.get("upserted"),
            "deleted": last_resync.get("deleted"),
            "total": last_resync.get("total"),
            "source": last_resync.get("source"),
            "label": last_resync.get("label") or last_resync.get("contest_name"),
        }
    return {
        "status": status,
        "feed_age": feed_age,
        "packets": n1mm_pkts,
        "qso_count": qso_count,
        "seed": seed,
        "active_contest": active_contest,
        "contests": contests or [],
        "last_resync": resync,
        "last_qso": None if not last_qso else {
            "call": last_qso["call"],
            "band": last_qso["band"],
            "age": round(now - last_qso["ts"], 1),
        },
    }


def fleet_to_dict(tracker, now: float, *, wsjt_pkts: int = 0, n1mm_pkts: int = 0) -> dict:
    """Snapshot the fleet (instances + loggers) as the console API payload."""
    instances = sorted(tracker.nodes.values(), key=lambda x: (x.band or "~", x.id))
    loggers = sorted(tracker.loggers.values(), key=lambda x: x.id)
    return {
        "api": API_VERSION,
        "now": now,
        "rx": {"wsjtx": wsjt_pkts, "n1mm": n1mm_pkts},
        "instances": [_instance(n, now) for n in instances],
        "loggers": [_logger(lg, now) for lg in loggers],
    }


def agents_to_dict(agents: dict, now: float, *, stale_after: float = 90.0,
                   dead_after: float = 180.0) -> list:
    """Seat agent reports for Status/Setup (plan sec 3.3 / 3.15 / networking sec 12).

    `agents` maps agent_id -> last accepted report dict (must include `ts`).
    Pruning of dead agents is done by the server store; this only projects age/health.
    """
    out = []
    for aid in sorted(agents):
        r = agents[aid]
        ts = r.get("ts")
        age_s = None if ts is None else round(now - float(ts), 1)
        if age_s is None:
            health = "UNKNOWN"
        elif age_s <= stale_after:
            health = "ALIVE"
        elif age_s <= dead_after:
            health = "STALE"
        else:
            health = "DEAD"
        summary = r.get("summary") or {}
        host = r.get("host") or {}
        wx = r.get("wsjtx") or {}
        apps = r.get("apps") or {}
        out.append({
            "agent_id": r.get("agent_id") or aid,
            "seat_id": r.get("seat_id"),
            "age": age_s,
            "health": health,
            "severity": summary.get("severity") or "unknown",
            "message": summary.get("message") or "",
            "hostname": host.get("hostname"),
            "lan_ips": host.get("lan_ips") or [],
            "os": host.get("os"),
            "wsjtx_configs": len(wx.get("configs") or []),
            "wsjtx_errors": wx.get("error_count") or 0,
            "wsjtx_warns": wx.get("warn_count") or 0,
            "wsjtx_running": apps.get("wsjtx_running"),
            "n1mm_running": apps.get("n1mm_running"),
            "n1mm_found": (r.get("n1mm") or {}).get("found"),
            "mode": r.get("mode"),
            # Full nested report for Setup drill-down (configs + issues).
            "report": r,
        })
    return out
