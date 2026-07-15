"""Server state -> JSON — the durable console API contract (plan §3.12).

This is the stable boundary between the WIMS server and any operator console. It
is deliberately a plain dict/JSON shape with no framework or rendering assumptions,
so the frontend can be rewritten (plain HTML today, anything later) while this
contract — and everything behind it — stays put. Keep it additive and versioned.
"""

from __future__ import annotations

from wims.engine.geo import bearing as _bearing

API_VERSION = 1


def _instance(n, now: float) -> dict:
    # id_collision uses a recent-host window so a desktop→VM move of the same
    # rig-name does not sticky-flag ⚠ id after the old source goes silent.
    collide = (n.id_collision_at(now) if hasattr(n, "id_collision_at")
               else n.id_collision)
    recent = sorted(n.hosts_recent(now)) if hasattr(n, "hosts_recent") else sorted(n.hosts)
    return {
        "id": n.id,
        "host": n.host,
        "hosts": recent,   # live sources (debug / multi-host collision UI)
        "band": n.band,
        "mode": n.mode,
        "dial_hz": n.dial_hz,
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
    return {
        "id": lg.id,
        "kind": lg.kind,
        "host": lg.host,
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
                   *, condition: str, strategy: str) -> dict:
    """Snapshot the GridTracker-style call roster (plan §3.5 / §2.2) for the console.

    `scored_rows` is `[(ScoredCandidate, entry), ...]` from `RosterBuilder.ranked` —
    **every** retained station (needed and already-worked), each carrying its per-factor
    score breakdown (the explainability is the point) plus the fields for the console
    columns: `to_call` (who they're calling), RF `freq_hz` (instance dial + decode df),
    `az` (great-circle bearing from the instance's own grid to the DX grid — pointing),
    and `is_needed` (not a dupe per the N1MM log copy) so the console can toggle needed /
    all and filter by band. `operator_call` (who manages that band) is stubbed until the
    §3.14 fleet profile is wired. `not_needed` counts already-worked (dupe) rows."""
    cands = []
    for sc, e in scored_rows:
        c = sc.candidate
        d = e.decode
        freq_hz = (e.dial_hz + d.delta_frequency) if e.dial_hz else None
        cands.append({
            "call": c.call,
            "to_call": d.to_call,                  # "calling" column
            "grid": c.grid,
            "band": c.band,
            "mode": d.mode,
            "instance": c.instance_id,
            "operator_call": None,                 # §3.14 profile stub (band manager)
            "snr": c.snr,
            "freq_hz": freq_hz,
            "az": None if (a := _bearing(e.de_grid, c.grid)) is None else round(a),
            "score": round(sc.total, 1),
            "is_needed": not c.is_dupe,
            "is_cq": c.is_cq,
            "is_dupe": c.is_dupe,
            "is_new_mult": c.is_new_mult,
            "is_rover": c.is_rover,
            "ts": e.last_seen,                     # epoch -> console formats UTC
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
                      contests: list | None = None) -> dict:
    """N1MM feed + log-copy freshness (plan §2.2 / §3.6).

    N1MM has **no heartbeat** — it only broadcasts on activity (logged QSO, spot,
    lookup) — so 'no recent packet' means quiet, not necessarily broken; the console
    wording reflects that. `qso_count`/`last_qso` describe WIMS's own log copy that
    feeds the roster's dupe/mult; `seed` records the startup `.s3db` read (count +
    source file) so the operator can see the existing log was pulled in even before
    any live broadcast.

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
    return {
        "status": status,
        "feed_age": feed_age,
        "packets": n1mm_pkts,
        "qso_count": qso_count,
        "seed": seed,
        "active_contest": active_contest,
        "contests": contests or [],
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
