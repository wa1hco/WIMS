# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSB/CW seat agent: shared N1MM live band + optional log forward + Key inhibit.

  python -m wims.seat --log              # log only (same as wims.log)
  python -m wims.seat --key              # Key only (CTS → same-band type-18)
  python -m wims.seat --log --key        # both (contest N1MM / SSB-CW PC)

Live band always comes from N1MM RadioInfo (fail closed until heard).
Key discovery: Status + InhibitStatus on the live band's multicast port.
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
    title = f"WIMS seat ({'+'.join(parts)}) · {band or '...'}"

    details: list[str] = []
    facts: list[str] = []
    level = "ok"
    banner = f"Ready — {band}" if band else "Waiting for N1MM band"
    fix = ""

    radio_dest = f"{snap.get('radio_group') or 'this host'}:{snap.get('radio_port', DEFAULT_RADIO_PORT)}"
    if snap.get("radio_error"):
        level, banner = "err", "Cannot hear N1MM RadioInfo"
        fix = str(snap["radio_error"])
    elif not band:
        level, banner = "warn", "Waiting for N1MM band"
        fix = f"Enable N1MM Broadcast Data → Radio to {radio_dest}"

    if do_log:
        facts.append(
            f"Log FWD {snap['n_fwd']}  DROP {snap['n_drop']}  WAIT {snap['n_wait']}"
        )
        if snap.get("join_error"):
            level, banner = "err", "Log multicast join failed"
            fix = str(snap["join_error"])
        elif snap.get("joined"):
            details.append(f"[OK] Log joined {snap['group']}:{snap['mcast_port']}")
        if snap.get("last_fwd"):
            details.append(f"Last FWD {snap['last_fwd']}")

    if do_key and key is not None:
        ks = key.state.snapshot()
        n_tgt = len(ks["targets"])
        facts.append(
            f"Key {'DOWN' if ks['keyed'] else 'up'}  "
            f"hold={'yes' if ks['holding'] else 'no'}  "
            f"targets {n_tgt}"
        )
        details.append(f"Controller {ks['controller_id']}")
        if ks.get("cts_error"):
            if level == "ok":
                level, banner = "warn", f"Key device: {ks['cts_error']}"
            details.append(f"[!] CTS {ks['cts_error']}")
        else:
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
        if not band and not key.override:
            details.append("Key fail-closed until live band known")

    if level == "ok" and band:
        if do_key and do_log:
            banner = f"Seat ready — {band}"
        elif do_key:
            banner = f"Key ready — {band}"
        else:
            banner = f"Log ready — {band}"

    return AgentStatusModel(
        title=title,
        banner_level=level,
        banner_text=banner,
        fix_text=fix or (details[0] if details else ""),
        fact_lines=facts[:4],
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
    state.group = args.group
    state.mcast_port = args.port
    state.delivery = args.n1mm
    state.tcp_port = args.tcp_port
    state.dry_run = args.dry_run
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
