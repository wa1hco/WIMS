# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""N1MM agent: Broadcast + Log + optional KEY (one process on the logger PC).

  python -m wims.seat --log              # Broadcast + Log
  python -m wims.seat --key              # Broadcast + KEY
  python -m wims.seat --log --key        # all three (contest default)

Sections (status UI):
  BROADCAST — N1MM Broadcast Data (RadioInfo) on 127.0.0.1:12060 → site server
  LOG       — fleet digi Logged QSOs → local N1MM
  KEY       — CTS → same-band type-18 holds

Live band from Broadcast RadioInfo (fail closed until heard).
Not N1MM networking :12070.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from wims.agent_ui import AgentStatusModel, AgentStatusWindow
from wims.key.runtime import KeyRuntime, default_controller_id
from wims.log import GROUP, PORT
from wims.log.app import (
    DEFAULT_RADIO_GROUP,
    DEFAULT_RADIO_PORT,
    DEFAULT_TCP_PORT,
    LogState,
    _forward_loop,
    _log_line,
    _radio_loop,
    rescan,
)


def _seat_busy() -> str | None:
    """Return error text if another N1MM-seat/log/key agent is already running.

    Kind "seat" (the WSJT monitor, wims.agent --daemon) is deliberately NOT
    checked — it can coexist with this seat. The merged wims.seat process
    classifies as "n1mm_seat".
    """
    try:
        from wims.launcher.process_replace import other_agent_running
    except Exception:
        return None
    for kind in ("n1mm_seat", "log", "key"):
        other = other_agent_running(kind)  # type: ignore[arg-type]
        if other is not None:
            return (
                f"{kind} agent already running (pid {other.pid}).\n"
                f"  {other.cmdline}\n"
                f"  Stop it before starting the seat agent."
            )
    return None


def _status_model(log_state: LogState, key: KeyRuntime | None, *, do_log: bool, do_key: bool) -> AgentStatusModel:
    snap = log_state.snapshot()
    band = snap["live_band"]
    parts = []
    if do_log:
        parts.append("log")
    if do_key:
        parts.append("key")
    # Product name: N1MM agent — sections Broadcast / Log / KEY.
    title = f"WIMS N1MM agent · {band or '...'}"

    details: list[str] = []
    rows: list[tuple[str, str, str]] = []
    level = "ok"
    banner = f"Ready — {band}" if band else "Waiting for N1MM band"
    fix = ""

    radio_dest = (
        f"{snap.get('radio_group') or '0.0.0.0'}:"
        f"{snap.get('radio_port', DEFAULT_RADIO_PORT)}"
    )
    # —— Broadcast (N1MM Broadcast Data → agent; later → site server) ——
    if snap.get("radio_error"):
        level, banner = "err", "Cannot hear N1MM Broadcast Data"
        fix = (
            f"{snap['radio_error']} — N1MM Broadcast Data > Radio → "
            f"127.0.0.1:12060 (fleet default; not Tailscale)"
        )
        rows.append(("err", "BROADCAST", f"{snap['radio_error']} · want {radio_dest}"))
    elif not band:
        level, banner = "warn", "Waiting for N1MM Broadcast (Radio)"
        fix = (
            "N1MM Broadcast Data > Radio → 127.0.0.1:12060 "
            "(identical on every logger PC)"
        )
        rows.append(("warn", "BROADCAST", f"no RadioInfo yet · listen {radio_dest}"))
    else:
        bcast = snap.get("broadcast") or {}
        site = bcast.get("site_url") or snap.get("site_url") or "(no WIMS_SERVER)"
        n_bf = bcast.get("n_fwd", 0)
        n_be = bcast.get("n_err", 0)
        bcast_txt = (
            f"RadioInfo · band {band} · hear {radio_dest} · "
            f"→ site FWD {n_bf}" + (f" ERR {n_be}" if n_be else "")
        )
        rows.append(("ok" if n_be == 0 else "warn", "BROADCAST", bcast_txt))
        details.append(f"[OK] Broadcast hear {radio_dest}")
        details.append(f"Broadcast → {site}")
        if bcast.get("last_error"):
            details.append(f"[!] Broadcast fwd: {bcast['last_error']}")

    if do_log:
        counts = f"FWD {snap['n_fwd']} · DROP {snap['n_drop']} · WAIT {snap['n_wait']}"
        if snap.get("join_error"):
            level, banner = "err", "Log multicast join failed"
            fix = str(snap["join_error"])
            rows.append(("err", "LOG", f"multicast join failed — {snap['join_error']}"))
        elif not band:
            rows.append(("warn", "LOG", f"waiting for band · {counts}"))
        else:
            deliver = "DRY-RUN" if snap.get("dry_run") else f"→ N1MM TCP :{snap.get('tcp_port', DEFAULT_TCP_PORT)}"
            rows.append(("ok", "LOG", f"{band} · {counts} · {deliver}"))
        if snap.get("joined"):
            details.append(f"[OK] Log joined {snap['group']}:{snap['mcast_port']}")
        if snap.get("last_fwd"):
            details.append(f"Last FWD {snap['last_fwd']}")

    warn_note = ""
    if do_key and key is not None:
        ks = key.state.snapshot()
        n_tgt = len(ks["targets"])
        details.append(f"Controller {ks['controller_id']}")
        if ks.get("cts_error"):
            # Key half is down (red row), but the seat still logs — banner
            # stays about the seat/band and the remedy goes to the fix line.
            rows.append(("err", "KEY", f"{ks['cts_error']}"))
            if level == "ok":
                level = "warn"
                warn_note = ("key device missing"
                             if "no KEY device" in str(ks["cts_error"])
                             else "key device error")
                fix = (
                    f"Key: {ks['cts_error']} — set WIMS_KEY_DEVICE "
                    f"(COM port of the keyline interface; sim:up/sim:down for lab)"
                )
            details.append(f"[!] CTS {ks['cts_error']}")
        else:
            key_txt = (
                f"{'DOWN' if ks['keyed'] else 'up'} · "
                f"hold={'yes' if ks['holding'] else 'no'} · "
                f"device {key.device} · targets {n_tgt}"
            )
            if not band and not key.override:
                rows.append(("warn", "KEY", key_txt + " · fail-closed until band"))
            else:
                rows.append(("ok", "KEY", key_txt))
            details.append(f"[OK] KEY device {key.device or '(none)'}")
        if ks.get("discover_error"):
            details.append(f"[!] Discover {ks['discover_error']}")
        elif ks.get("discover_port"):
            details.append(f"[OK] Discover :{ks['discover_port']}")
        if n_tgt:
            shown = ", ".join(f"{h}:{p}" for h, p, _ in ks["targets"][:4])
            details.append(f"Targets: {shown}" + ("…" if n_tgt > 4 else ""))
        elif band and not key.override:
            details.append("[!] No same-band inhibit targets yet (need Status+type 17)")
        if ks.get("last_emit"):
            details.append(ks["last_emit"])

    # Band known and nothing fatal: banner names the N1MM agent + band.
    if band and level != "err":
        if level == "ok":
            banner = f"N1MM agent ready — {band}"
        else:
            banner = f"N1MM agent — {band} · {warn_note or 'warnings (see below)'}"

    return AgentStatusModel(
        title=title,
        banner_level=level,
        banner_text=banner,
        fix_text=fix or (details[0] if details else ""),
        status_rows=rows,
        fact_lines=[],
        detail_lines=details,
        hover_text="\n".join(details),
        site_url=snap.get("site_url"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--log", action="store_true", help="forward Logged QSO to local N1MM")
    ap.add_argument("--key", action="store_true",
                    help="CTS → type-18 holds for same-band digi seats")
    ap.add_argument("--group", default=GROUP)
    ap.add_argument("--port", type=int, default=PORT,
                    help="log-agent multicast port (default 2237; Key uses live-band port)")
    ap.add_argument("--iface", default="0.0.0.0")
    ap.add_argument("--band", "--expect-band", dest="expect_band", default=None)
    ap.add_argument("--radio-port", type=int, default=DEFAULT_RADIO_PORT)
    ap.add_argument("--radio-group", default=DEFAULT_RADIO_GROUP,
                    help="N1MM RadioInfo multicast group (default 224.0.0.73; "
                         "'' = unicast-only bind)")
    ap.add_argument("--n1mm", default="127.0.0.1:2333")
    ap.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--device", default=os.environ.get("WIMS_KEY_DEVICE", ""),
                    help="KEY/CTS device (or sim:up / sim:down); else WIMS_KEY_DEVICE")
    ap.add_argument("--controller-id", default="",
                    help="type-18 Controller ID (default hostname-key)")
    ap.add_argument("--station", default="",
                    help="badge text on holds (default controller id)")
    ap.add_argument("--targets", default="",
                    help="override discovery: host:port,host:port (or WIMS_KEY_TARGETS)")
    ap.add_argument("--gui", dest="gui", action="store_true", default=True)
    ap.add_argument("--no-gui", dest="gui", action="store_false")
    args = ap.parse_args(argv)

    do_log = bool(args.log)
    do_key = bool(args.key)
    if not do_log and not do_key:
        ap.error("specify --log and/or --key")

    busy = _seat_busy()
    if busy:
        print(f"ERROR: {busy}", file=sys.stderr, flush=True)
        return 2

    expect = (args.expect_band or os.environ.get("WIMS_BAND") or "").strip() or None
    state = LogState()
    state.expect_band = expect
    state.radio_port = args.radio_port
    state.radio_group = (args.radio_group or "").strip() or None
    state.radio_iface = (args.iface or "0.0.0.0").strip() or "0.0.0.0"
    state.group = args.group
    state.mcast_port = args.port
    state.delivery = args.n1mm
    state.tcp_port = args.tcp_port
    state.dry_run = args.dry_run
    from wims.log.broadcast_fwd import (
        BroadcastForwarder, default_agent_id, default_lan_ip,
    )
    state.broadcast_fwd = BroadcastForwarder(
        site_url=state.site_url,
        agent_id=default_agent_id(),
        lan_ip=default_lan_ip(),
    )
    rescan(state)

    stop = threading.Event()
    radio_thread = threading.Thread(
        target=_radio_loop, args=(state, stop), daemon=True, name="seat-radio",
    )
    radio_thread.start()

    fwd_thread = None
    if do_log:
        fwd_thread = threading.Thread(
            target=_forward_loop, args=(state, args, stop), daemon=True, name="seat-log",
        )
        fwd_thread.start()

    key_rt = None
    if do_key:
        device = (args.device or os.environ.get("WIMS_KEY_DEVICE") or "").strip()
        targets = (args.targets or os.environ.get("WIMS_KEY_TARGETS") or "").strip()
        cid = (args.controller_id or "").strip() or default_controller_id()
        station = (args.station or "").strip() or cid
        key_rt = KeyRuntime(
            device=device,
            controller_id=cid,
            station=station,
            group=args.group,
            iface=args.iface,
            target_override=targets or None,
            get_band=lambda: state.snapshot()["live_band"],
        )
        key_rt.start()
        _log_line(
            f"seat-agent: key on  controller={cid}  device={device or '(none)'}  "
            f"targets={'override ' + targets if targets else 'discover same-band'}"
        )

    _log_line(
        f"seat-agent: modes={'log ' if do_log else ''}{'key' if do_key else ''}  "
        f"RadioInfo {(state.radio_group + ':') if state.radio_group else ':'}{args.radio_port}"
    )

    if args.gui:
        try:
            win = AgentStatusWindow(
                refresh=lambda: _status_model(state, key_rt, do_log=do_log, do_key=do_key),
                on_rescan=lambda: rescan(state),
                on_quit=lambda: stop.set(),
            )
            win.run()
        except Exception as e:
            _log_line(f"seat-agent: GUI unavailable ({e}); console-only")
            args.gui = False

    if not args.gui:
        try:
            while not stop.is_set():
                if fwd_thread and not fwd_thread.is_alive() and do_log:
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop.set()
            _log_line("seat-agent: quit")

    stop.set()
    if key_rt is not None:
        key_rt.stop()
    if fwd_thread is not None:
        fwd_thread.join(timeout=2.0)
    radio_thread.join(timeout=1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
