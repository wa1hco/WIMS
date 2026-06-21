"""Server state -> JSON — the durable console API contract (plan §3.12).

This is the stable boundary between the WIMS server and any operator console. It
is deliberately a plain dict/JSON shape with no framework or rendering assumptions,
so the frontend can be rewritten (plain HTML today, anything later) while this
contract — and everything behind it — stays put. Keep it additive and versioned.
"""

from __future__ import annotations

API_VERSION = 1


def _instance(n, now: float) -> dict:
    return {
        "id": n.id,
        "host": n.host,
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
        "id_collision": n.id_collision,
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


def roster_to_dict(scored_pairs, excluded: int, now: float,
                   *, condition: str, strategy: str) -> dict:
    """Snapshot the ranked call roster (plan §3.5 / §2.2) for the console.

    `scored_pairs` is `[(ScoredCandidate, last_seen), ...]` best-first (from
    `RosterBuilder.ranked`). Each candidate ships its **per-factor breakdown** so the
    operator sees exactly why a station ranks where it does — the explainability is the
    point. `excluded` is how many retained candidates were suppressed (dupe / not
    reachable) and are not shown."""
    cands = []
    for sc, last_seen in scored_pairs:
        c = sc.candidate
        cands.append({
            "call": c.call,
            "grid": c.grid,
            "band": c.band,
            "instance": c.instance_id,
            "snr": c.snr,
            "score": round(sc.total, 1),
            "is_new_mult": c.is_new_mult,
            "is_rover": c.is_rover,
            "age": round(now - last_seen, 1),
            "factors": [{"name": f.name, "contribution": round(f.contribution, 1),
                         "detail": f.detail} for f in sc.factors],
        })
    return {
        "condition": condition,
        "strategy": strategy,
        "count": len(cands),
        "excluded": excluded,
        "candidates": cands,
    }


def activity_to_dict(amap) -> dict:
    """Snapshot one instance's decode-activity map (plan §2.5) — the df × cycle × SNR
    heatmap that confirms decodes are flowing without any screen capture. Cells carry
    raw best-SNR (or null = nothing decoded there); the console colors them."""
    rows = []
    for bucket, snrs in amap.recent_rows():
        secs = bucket * amap.period_s
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
                      seed: dict | None = None, stale_after: float = 180.0) -> dict:
    """N1MM feed + log-copy freshness (plan §2.2 / §3.6).

    N1MM has **no heartbeat** — it only broadcasts on activity (logged QSO, spot,
    lookup) — so 'no recent packet' means quiet, not necessarily broken; the console
    wording reflects that. `qso_count`/`last_qso` describe WIMS's own log copy that
    feeds the roster's dupe/mult; `seed` records the startup `.s3db` read (count +
    source file) so the operator can see the existing log was pulled in even before
    any live broadcast."""
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
