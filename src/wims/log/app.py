# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Log helper: fleet mcast Logged QSO -> local N1MM, with optional Tk status UI.

Band filter follows live N1MM RadioInfo (wait/drop until heard). See
docs/decisions/2026-08-29-n1mm-live-band.md.

  python -m wims.log
  python -m wims.log --no-gui
  python -m wims.log --expect-band 6m   # optional mismatch warn only
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

from wims.core.bands import band_label
from wims.helper_ui import HelperStatusModel, HelperStatusWindow
from wims.log import GROUP, PORT
from wims.log.check import run_checks
from wims.log.radioinfo import band_from_radioinfo_xml
from wims.udp import messages as M
from wims.udp.sink import open_socket

_ADIF_BAND = re.compile(r"<BAND:(\d+)>([^<]+)", re.I)
_ADIF_FREQ = re.compile(r"<FREQ:(\d+)>([^<]+)", re.I)
_ADIF_CALL = re.compile(r"<CALL:(\d+)>([^<]+)", re.I)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HELPER_LOG = _REPO_ROOT / "scratch" / "log-helper.log"
DEFAULT_RADIO_PORT = 12060


def adif_band(adif: str) -> str | None:
    m = _ADIF_BAND.search(adif or "")
    if m:
        key = m.group(2).strip().lower()
        aliases = {
            "6m": "6m", "50": "6m", "2m": "2m", "144": "2m",
            "1.25m": "1.25m", "222": "1.25m", "70cm": "70cm",
            "432": "70cm", "33cm": "33cm", "902": "33cm",
            "23cm": "23cm", "1296": "23cm",
        }
        return aliases.get(key)
    m = _ADIF_FREQ.search(adif or "")
    if m:
        try:
            mhz = float(m.group(2).strip())
        except ValueError:
            return None
        return band_label(int(mhz * 1_000_000))
    return None


def wrap_adif(adif: str) -> bytes:
    text = (adif or "").strip()
    if "<eor>" not in text.lower():
        text += " <eor>"
    return text.encode("ascii", "replace")


def qso_to_adif(msg: M.QSOLogged) -> str:
    mhz = (msg.tx_frequency or 0) / 1e6
    band = band_label(msg.tx_frequency or 0)
    parts = [
        f"<CALL:{len(msg.dx_call or '')}>{msg.dx_call or ''}",
        f"<GRIDSQUARE:{len(msg.dx_grid or '')}>{msg.dx_grid or ''}",
        f"<MODE:{len(msg.mode or '')}>{msg.mode or ''}",
        f"<FREQ:{len(f'{mhz:.6f}')}>{mhz:.6f}",
        f"<BAND:{len(band)}>{band}",
        f"<STATION_CALLSIGN:{len(msg.my_call or '')}>{msg.my_call or ''}",
        f"<MY_GRIDSQUARE:{len(msg.my_grid or '')}>{msg.my_grid or ''}",
        f"<RST_SENT:{len(msg.report_sent or '')}>{msg.report_sent or ''}",
        f"<RST_RCVD:{len(msg.report_received or '')}>{msg.report_received or ''}",
    ]
    return "".join(parts) + " <eor>"


class LogState:
    """Thread-safe snapshot for the status UI / console."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.host = socket.gethostname()
        self.live_band: str | None = None
        self.expect_band: str | None = None
        self.radio_port = DEFAULT_RADIO_PORT
        self.radio_error: str | None = None
        self.last_radio_at: float | None = None
        self.group = GROUP
        self.mcast_port = PORT
        self.delivery = "127.0.0.1:2333"
        self.dry_run = False
        self.joined = False
        self.join_error: str | None = None
        self.n_fwd = 0
        self.n_drop = 0
        self.n_wait = 0
        self.last_fwd: str | None = None
        self.last_error: str | None = None
        self.running = False
        self.check_lines: list[str] = []
        self.check_severity = "busy"
        self.site_url = (os.environ.get("WIMS_SERVER") or "").rstrip("/") or None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "host": self.host,
                "live_band": self.live_band,
                "expect_band": self.expect_band,
                "radio_port": self.radio_port,
                "radio_error": self.radio_error,
                "last_radio_at": self.last_radio_at,
                "group": self.group,
                "mcast_port": self.mcast_port,
                "delivery": self.delivery,
                "dry_run": self.dry_run,
                "joined": self.joined,
                "join_error": self.join_error,
                "n_fwd": self.n_fwd,
                "n_drop": self.n_drop,
                "n_wait": self.n_wait,
                "last_fwd": self.last_fwd,
                "last_error": self.last_error,
                "running": self.running,
                "check_lines": list(self.check_lines),
                "check_severity": self.check_severity,
                "site_url": self.site_url,
            }

    def set_live_band(self, band: str) -> bool:
        """Update filter band; return True if it changed."""
        with self._lock:
            self.last_radio_at = time.time()
            if self.live_band == band:
                return False
            prev = self.live_band
            self.live_band = band
        _log_line(
            f"log-helper: N1MM band -> {band}"
            + (f" (was {prev})" if prev else " (first RadioInfo)")
        )
        return True


def _log_line(text: str) -> None:
    line = text if text.endswith("\n") else text + "\n"
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass
    try:
        _HELPER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _HELPER_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def rescan(state: LogState) -> None:
    snap = state.snapshot()
    nhost, _, nport = snap["delivery"].partition(":")
    host = nhost or "127.0.0.1"
    udp_port = int(nport or "2333")
    if snap["joined"]:
        joined: bool | None = True
    elif snap["join_error"]:
        joined = False
    else:
        joined = None
    rep = run_checks(
        live_band=snap["live_band"],
        expect_band=snap["expect_band"],
        radio_port=snap["radio_port"],
        group=snap["group"],
        mcast_port=snap["mcast_port"],
        delivery_host=host,
        delivery_udp_port=udp_port,
        joined=joined,
        dry_run=snap["dry_run"],
    )
    if snap["join_error"]:
        from wims.log.check import CheckItem
        rep.items = [
            it if it.id != "mcast" else CheckItem(
                "mcast", "error",
                f"Multicast join failed: {snap['join_error']}",
            )
            for it in rep.items
        ]
    if snap["radio_error"]:
        from wims.log.check import CheckItem
        rep.items.insert(0, CheckItem(
            "radio", "error",
            f"RadioInfo listen failed on :{snap['radio_port']}: {snap['radio_error']}",
        ))
    with state._lock:
        state.check_lines = rep.lines()
        state.check_severity = rep.severity


def _status_model(state: LogState) -> HelperStatusModel:
    s = state.snapshot()
    band = s["live_band"]
    title = f"WIMS log helper — {band or 'waiting'}"
    if s["join_error"] or s["radio_error"]:
        level, banner = "err", "Log helper needs attention"
    elif not band:
        level, banner = "warn", "Waiting for N1MM band (RadioInfo)"
    elif s["check_severity"] == "error":
        level, banner = "err", f"Log helper needs attention — {band}"
    elif s["check_severity"] == "warn":
        level, banner = "warn", f"Log helper running — check warnings — {band}"
    else:
        level, banner = "ok", f"Log helper running — {band}"

    age = ""
    if s["last_radio_at"]:
        age = f"  (RadioInfo {int(time.time() - s['last_radio_at'])}s ago)"
    status = [
        f"Host: {s['host']}",
        f"N1MM band filter: {band or '(waiting)'}{age}",
        f"Forwarded: {s['n_fwd']}   Other-band drops: {s['n_drop']}   "
        f"Waiting drops: {s['n_wait']}",
        f"Last FWD: {s['last_fwd'] or '(none yet)'}",
    ]
    if s["expect_band"]:
        status.append(f"Expected (optional): {s['expect_band']}")
    if s["last_error"]:
        status.append(f"Last error: {s['last_error']}")

    inter = [
        f"RadioInfo listen: 127.0.0.1:{s['radio_port']}  "
        + ("OK" if not s["radio_error"] else "FAILED"),
        f"Multicast: {s['group']}:{s['mcast_port']}  "
        + ("JOINED" if s["joined"] else ("FAILED" if s["join_error"] else "...")),
        f"Delivery: {'DRY-RUN' if s['dry_run'] else s['delivery']} (UDP today)",
        "N1MM WSJT UDP reader on this PC must be OFF.",
    ]
    if s["radio_error"]:
        inter.append(f"Radio listen error: {s['radio_error']}")
    if s["join_error"]:
        inter.append(f"Join error: {s['join_error']}")

    return HelperStatusModel(
        title=title,
        banner_level=level,
        banner_text=banner,
        status_lines=status,
        interconnect_lines=inter,
        check_lines=s["check_lines"] or ["(press Rescan)"],
        site_url=s["site_url"],
    )


def _open_radio_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Prefer loopback — N1MM Radio broadcast default is 127.0.0.1:12060.
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.5)
    return sock


def _radio_loop(state: LogState, stop: threading.Event) -> None:
    try:
        sock = _open_radio_socket(state.radio_port)
    except OSError as e:
        with state._lock:
            state.radio_error = str(e)
        _log_line(f"log-helper: RadioInfo listen failed: {e}")
        rescan(state)
        return
    _log_line(
        f"log-helper: listening for N1MM RadioInfo on 127.0.0.1:{state.radio_port}"
    )
    while not stop.is_set():
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError as e:
            with state._lock:
                state.last_error = f"RadioInfo recv: {e}"
            break
        text = data.decode("utf-8", "replace")
        band, _meta = band_from_radioinfo_xml(text)
        if not band or band == "?":
            continue
        if state.set_live_band(band):
            rescan(state)
    try:
        sock.close()
    except OSError:
        pass


def _forward_loop(state: LogState, args: argparse.Namespace, stop: threading.Event) -> None:
    nhost, _, nport = args.n1mm.partition(":")
    n1mm = (nhost or "127.0.0.1", int(nport or "2333"))
    try:
        sock = open_socket(args.iface, args.port, args.group)
    except OSError as e:
        with state._lock:
            state.join_error = str(e)
            state.joined = False
            state.running = False
        _log_line(f"log-helper: join failed: {e}")
        rescan(state)
        return

    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with state._lock:
        state.joined = True
        state.join_error = None
        state.running = True
    rescan(state)
    dest = "DRY-RUN" if args.dry_run else f"-> {args.n1mm}"
    _log_line(
        f"log-helper: host={state.host}  join {args.group}:{args.port}  {dest}"
    )
    _log_line("          Filter band comes from N1MM RadioInfo (waiting until heard).")
    _log_line("          N1MM WSJT UDP reader must be OFF on this PC (no 2237).")

    seen: set[tuple] = set()
    sock.settimeout(0.5)
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError as e:
            with state._lock:
                state.last_error = str(e)
            break
        msg = M.parse(data)
        if msg is None:
            continue
        adif = None
        call = None
        qband = None
        if isinstance(msg, M.LoggedADIF) and msg.adif:
            adif = msg.adif
            qband = adif_band(adif)
            m = _ADIF_CALL.search(adif)
            call = m.group(2) if m else msg.id
        elif isinstance(msg, M.QSOLogged):
            qband = band_label(msg.tx_frequency or 0)
            call = msg.dx_call
            adif = qso_to_adif(msg)
        else:
            continue

        pin = state.snapshot()["live_band"]
        if not pin:
            with state._lock:
                state.n_wait += 1
            _log_line(
                f"{time.strftime('%H:%M:%S')}  WAIT {msg.id} {call} "
                f"band={qband} (no N1MM band yet)  from {addr[0]}"
            )
            continue
        if qband != pin:
            with state._lock:
                state.n_drop += 1
            _log_line(
                f"{time.strftime('%H:%M:%S')}  DROP {msg.id} {call} "
                f"band={qband} (want {pin})  from {addr[0]}"
            )
            continue
        key = (msg.id, call, qband)
        if key in seen:
            continue
        seen.add(key)
        payload = wrap_adif(adif or "")
        with state._lock:
            state.n_fwd += 1
            state.last_fwd = (
                f"{time.strftime('%H:%M:%S')} {call} {qband} ({len(payload)} B)"
            )
            n_fwd, n_drop = state.n_fwd, state.n_drop
        _log_line(
            f"{time.strftime('%H:%M:%S')}  FWD  {msg.id} {call} {qband}  "
            f"{len(payload)} B  ({n_fwd} fwd / {n_drop} drop)"
        )
        if not args.dry_run:
            try:
                out.sendto(payload, n1mm)
            except OSError as e:
                with state._lock:
                    state.last_error = f"send failed: {e}"
                _log_line(f"log-helper: send failed: {e}")
    with state._lock:
        state.running = False
    try:
        sock.close()
    except OSError:
        pass
    try:
        out.close()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--group", default=GROUP)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--iface", default="0.0.0.0",
                    help="LAN iface to join multicast (default: auto)")
    ap.add_argument(
        "--band", "--expect-band", dest="expect_band", default=None,
        help="optional expected band for mismatch warn only (filter follows N1MM)",
    )
    ap.add_argument("--radio-port", type=int, default=DEFAULT_RADIO_PORT,
                    help="UDP port for N1MM RadioInfo (default 12060)")
    ap.add_argument("--n1mm", default="127.0.0.1:2333")
    ap.add_argument("--dry-run", action="store_true",
                    help="print matching QSOs, do not send to N1MM")
    ap.add_argument("--gui", dest="gui", action="store_true", default=True,
                    help="show compact Tk status window (default)")
    ap.add_argument("--no-gui", dest="gui", action="store_false",
                    help="console only (lab / headless)")
    args = ap.parse_args(argv)

    expect = (args.expect_band or os.environ.get("WIMS_BAND") or "").strip() or None

    state = LogState()
    state.expect_band = expect
    state.radio_port = args.radio_port
    state.group = args.group
    state.mcast_port = args.port
    state.delivery = args.n1mm
    state.dry_run = args.dry_run
    rescan(state)

    stop = threading.Event()
    radio_thread = threading.Thread(
        target=_radio_loop, args=(state, stop), daemon=True,
    )
    fwd_thread = threading.Thread(
        target=_forward_loop, args=(state, args, stop), daemon=True,
    )
    radio_thread.start()
    fwd_thread.start()

    if args.gui:
        try:
            win = HelperStatusWindow(
                refresh=lambda: _status_model(state),
                on_rescan=lambda: rescan(state),
                on_quit=lambda: stop.set(),
            )
            win.run()
        except Exception as e:
            _log_line(f"log-helper: GUI unavailable ({e}); continuing console-only")
            args.gui = False

    if not args.gui:
        try:
            while fwd_thread.is_alive() or radio_thread.is_alive():
                fwd_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            stop.set()
            _log_line("log-helper: quit")
            return 0

    stop.set()
    fwd_thread.join(timeout=2.0)
    radio_thread.join(timeout=1.0)
    snap = state.snapshot()
    if snap.get("join_error") or snap.get("radio_error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
