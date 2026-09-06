# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Log agent: fleet mcast Logged QSO -> local N1MM, with optional Tk status UI.

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
from datetime import date, datetime, timezone
from pathlib import Path

from wims.core.bands import band_label
from wims.agent_ui import AgentStatusModel, AgentStatusWindow
from wims.log import GROUP, PORT
from wims.log.check import run_checks
from wims.log.radioinfo import band_from_radioinfo_xml, radioinfo_ignore_reason
from wims.udp import messages as M
from wims.udp.sink import open_socket

_ADIF_BAND = re.compile(r"<BAND:(\d+)>([^<]+)", re.I)
_ADIF_FREQ = re.compile(r"<FREQ:(\d+)>([^<]+)", re.I)
_ADIF_CALL = re.compile(r"<CALL:(\d+)>([^<]+)", re.I)
_ADIF_HAS_DATE = re.compile(r"<QSO_DATE:", re.I)
_ADIF_HAS_TIME = re.compile(r"<TIME_ON:", re.I)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HELPER_LOG = _REPO_ROOT / "scratch" / "log-agent.log"
DEFAULT_RADIO_PORT = 12060
# Fleet N1MM Broadcast Data is 127.0.0.1:12060 (this PC only). Joining
# 224.0.0.73 hears every logger on the LAN and the live-band filter
# flip-flops. Lab override: --radio-group 224.0.0.73
DEFAULT_RADIO_GROUP: str | None = None
DEFAULT_TCP_PORT = 52001
# Packets of a *new* band required before the filter follows (after first lock).
_BAND_CONFIRM_PACKETS = 2


def adif_band(adif: str) -> str | None:
    m = _ADIF_BAND.search(adif or "")
    if m:
        key = m.group(2).strip().lower()
        aliases = {
            "6m": "6m", "50": "6m", "2m": "2m", "144": "2m",
            "1.25m": "1.25m", "222": "1.25m", "70cm": "70cm",
            "432": "70cm", "33cm": "33cm", "902": "33cm",
            "23cm": "23cm", "1296": "23cm",
            # HF (lab / accidental dial) — so filter DROPs are explainable.
            "160m": "160m", "80m": "80m", "40m": "40m", "30m": "30m",
            "20m": "20m", "17m": "17m", "15m": "15m", "12m": "12m", "10m": "10m",
        }
        label = aliases.get(key)
        if label:
            return label
        # Unknown BAND tag — fall through to FREQ.
    m = _ADIF_FREQ.search(adif or "")
    if m:
        try:
            mhz = float(m.group(2).strip())
        except ValueError:
            return None
        return band_label(int(mhz * 1_000_000))
    return None


def _qt_datetime_to_adif(dt: dict | None) -> tuple[str, str]:
    """Return (QSO_DATE yyyymmdd, TIME_ON hhmmss) from a parsed WSJT QDateTime."""
    if not dt:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    try:
        # Qt Julian day → proleptic Gregorian ordinal.
        d = date.fromordinal(int(dt["julian_day"]) - 1721425)
    except (ValueError, OverflowError, KeyError, TypeError):
        d = datetime.now(timezone.utc).date()
    msecs = int(dt.get("msecs") or 0)
    hh = (msecs // 3_600_000) % 24
    mm = (msecs // 60_000) % 60
    ss = (msecs // 1000) % 60
    return d.strftime("%Y%m%d"), f"{hh:02d}{mm:02d}{ss:02d}"


def _n1mm_band_token(label: str) -> str:
    """N1MM examples use 20M / 2M style; keep our lowercase labels uppercased."""
    return (label or "").strip().upper() or label


def ensure_adif_datetime(adif: str, dt: dict | None = None) -> str:
    """N1MM often ignores records without QSO_DATE / TIME_ON."""
    text = (adif or "").strip()
    extra = []
    if not _ADIF_HAS_DATE.search(text) or not _ADIF_HAS_TIME.search(text):
        qdate, qtime = _qt_datetime_to_adif(dt)
        if not _ADIF_HAS_DATE.search(text):
            extra.append(f"<QSO_DATE:{len(qdate)}>{qdate}")
        if not _ADIF_HAS_TIME.search(text):
            extra.append(f"<TIME_ON:{len(qtime)}>{qtime}")
    if not extra:
        return text
    if text.lower().endswith("<eor>"):
        return text[: -len("<eor>")].rstrip() + "".join(extra) + " <eor>"
    return text + "".join(extra) + " <eor>"


def wrap_adif(adif: str) -> bytes:
    """N1MM Secondary-UDP / JTDX-TCP ingest envelope (Sending Log Data).

    ``<command:3>Log <parameters:N>`` + ADIF + EOR. Raw ADIF alone is often ignored.
    """
    text = ensure_adif_datetime((adif or "").strip())
    if "<eor>" not in text.lower():
        text += " <eor>"
    raw = text.encode("ascii", "replace")
    return f"<command:3>Log <parameters:{len(raw)}>".encode("ascii") + raw


def _graceful_close(sock: socket.socket) -> None:
    """FIN then drain, then close — avoid a Windows RST.

    N1MM ``LoggingTCPListening`` treats an abortive close (WSAECONNABORTED)
    as a popup even after it has already inserted the QSO.
    """
    try:
        sock.shutdown(socket.SHUT_WR)
    except (OSError, AttributeError):
        pass
    try:
        sock.settimeout(0.3)
    except (OSError, AttributeError):
        pass
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
    except (OSError, TimeoutError, socket.timeout, AttributeError):
        pass
    try:
        sock.close()
    except (OSError, AttributeError):
        pass


class N1mmTcpClient:
    """Long-lived TCP client for N1MM JTDX/Others logging (:52001).

    JTDX keeps this socket open for the session. Connect-send-close per QSO
    inserts the contact, then N1MM pops ``Unable to read data from the
    transport connection`` (see logerror.txt / WSJTCode.LoggingTCPListening).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_TCP_PORT) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None

    @property
    def alive(self) -> bool:
        return self._sock is not None

    def send(self, payload: bytes) -> None:
        sock = self._ensure()
        try:
            sock.sendall(payload)
        except OSError:
            self.close()
            sock = self._ensure()
            sock.sendall(payload)

    def _ensure(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        sock = socket.create_connection((self.host, self.port), timeout=1.0)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        try:
            sock.settimeout(1.0)
        except (OSError, AttributeError):
            pass
        self._sock = sock
        return sock

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            _graceful_close(sock)


def qso_record(msg: M.WsjtxMessage) -> tuple[str, str | None, str | None] | None:
    """Normalize a Logged-QSO message to (adif, call, band); None for others.

    WSJT-X emits BOTH type 5 (QSOLogged) and type 12 (LoggedADIF) for one
    logged QSO. The call is stripped here so the two agree — ADIF text
    carries a trailing space before the next field, and an unequal call
    used to defeat the forward-loop dedup (one QSO -> two N1MM inserts).
    """
    if isinstance(msg, M.LoggedADIF) and msg.adif:
        adif = ensure_adif_datetime(msg.adif)
        m = _ADIF_CALL.search(adif)
        call = (m.group(2).strip() if m else "") or None
        return adif, call, adif_band(adif)
    if isinstance(msg, M.QSOLogged):
        call = (msg.dx_call or "").strip() or None
        return qso_to_adif(msg), call, band_label(msg.tx_frequency or 0)
    return None


def qso_to_adif(msg: M.QSOLogged) -> str:
    mhz = (msg.tx_frequency or 0) / 1e6
    band = _n1mm_band_token(band_label(msg.tx_frequency or 0))
    qdate, qtime = _qt_datetime_to_adif(msg.datetime_off or msg.datetime_on)
    parts = [
        f"<CALL:{len(msg.dx_call or '')}>{msg.dx_call or ''}",
        f"<GRIDSQUARE:{len(msg.dx_grid or '')}>{msg.dx_grid or ''}",
        f"<MODE:{len(msg.mode or '')}>{msg.mode or ''}",
        f"<FREQ:{len(f'{mhz:.6f}')}>{mhz:.6f}",
        f"<BAND:{len(band)}>{band}",
        f"<QSO_DATE:{len(qdate)}>{qdate}",
        f"<TIME_ON:{len(qtime)}>{qtime}",
        f"<STATION_CALLSIGN:{len(msg.my_call or '')}>{msg.my_call or ''}",
        f"<MY_GRIDSQUARE:{len(msg.my_grid or '')}>{msg.my_grid or ''}",
        f"<RST_SENT:{len(msg.report_sent or '')}>{msg.report_sent or ''}",
        f"<RST_RCVD:{len(msg.report_received or '')}>{msg.report_received or ''}",
    ]
    return "".join(parts) + " <eor>"


def deliver_to_n1mm(
    payload: bytes,
    *,
    host: str = "127.0.0.1",
    udp_port: int = 2333,
    tcp_port: int = DEFAULT_TCP_PORT,
    prefer_tcp: bool = True,
    tcp_client: N1mmTcpClient | None = None,
) -> tuple[bool, str]:
    """Deliver Log envelope to local N1MM. Prefer TCP 52001 (has a real handshake).

    UDP 2333 sendto() always looks successful even when nothing is listening —
    that is why agents can report FWD with no N1MM insert.

    Pass a long-lived ``tcp_client`` from the agent loop. One-shot connect /
    send / close makes N1MM pop an error box after a successful insert.
    """
    errors: list[str] = []
    if prefer_tcp:
        try:
            if tcp_client is not None:
                tcp_client.host = host
                tcp_client.port = tcp_port
                tcp_client.send(payload)
            else:
                sock = socket.create_connection((host, tcp_port), timeout=1.0)
                try:
                    try:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except (OSError, AttributeError):
                        pass
                    sock.sendall(payload)
                except BaseException:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    raise
                _graceful_close(sock)
            return True, f"TCP {host}:{tcp_port}"
        except OSError as e:
            errors.append(f"TCP {tcp_port}: {e}")
            if tcp_client is not None:
                tcp_client.close()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(payload, (host, udp_port))
        finally:
            sock.close()
        note = f"UDP {host}:{udp_port}"
        if errors:
            note += " (TCP failed: " + "; ".join(errors) + ")"
        return True, note
    except OSError as e:
        errors.append(f"UDP {udp_port}: {e}")
        return False, "; ".join(errors)


class LogState:
    """Thread-safe snapshot for the status UI / console."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.host = socket.gethostname()
        self.live_band: str | None = None
        self.expect_band: str | None = None
        self.radio_port = DEFAULT_RADIO_PORT
        self.radio_group: str | None = DEFAULT_RADIO_GROUP
        self.radio_iface: str = "0.0.0.0"  # IGMP join for RadioInfo multicast
        self.radio_error: str | None = None
        self.radio_note: str | None = None
        self.last_radio_at: float | None = None
        self._pending_band: str | None = None
        self._pending_count: int = 0
        self._ignore_logged: set[tuple] = set()
        self.group = GROUP
        self.mcast_port = PORT
        self.delivery = "127.0.0.1:2333"
        self.tcp_port = DEFAULT_TCP_PORT
        self.tcp_client: N1mmTcpClient | None = None
        self.dry_run = False
        self.joined = False
        self.join_error: str | None = None
        self.n_fwd = 0
        self.n_drop = 0
        self.n_wait = 0
        self.last_fwd: str | None = None
        self.last_delivery: str | None = None
        self.last_error: str | None = None
        self.running = False
        self.check_lines: list[str] = []
        self.check_severity = "busy"
        self.site_url = (os.environ.get("WIMS_SERVER") or "").rstrip("/") or None
        self.broadcast_fwd = None  # BroadcastForwarder | None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "host": self.host,
                "live_band": self.live_band,
                "expect_band": self.expect_band,
                "radio_port": self.radio_port,
                "radio_group": self.radio_group,
                "radio_iface": self.radio_iface,
                "radio_error": self.radio_error,
                "radio_note": self.radio_note,
                "last_radio_at": self.last_radio_at,
                "group": self.group,
                "mcast_port": self.mcast_port,
                "delivery": self.delivery,
                "tcp_port": self.tcp_port,
                "dry_run": self.dry_run,
                "joined": self.joined,
                "join_error": self.join_error,
                "n_fwd": self.n_fwd,
                "n_drop": self.n_drop,
                "n_wait": self.n_wait,
                "broadcast": (
                    self.broadcast_fwd.snapshot()
                    if self.broadcast_fwd is not None else None
                ),
                "last_fwd": self.last_fwd,
                "last_delivery": self.last_delivery,
                "last_error": self.last_error,
                "running": self.running,
                "check_lines": list(self.check_lines),
                "check_severity": self.check_severity,
                "site_url": self.site_url,
            }

    def set_live_band(self, band: str, meta: dict | None = None) -> bool:
        """Update filter band; return True if it changed.

        First RadioInfo locks immediately (fail-closed wait ends). After that,
        a new band needs ``_BAND_CONFIRM_PACKETS`` consecutive matching
        packets so interleaved Radio 1 / Radio 2 or leftover multicast
        cannot flip-flop the log filter.
        """
        extra = _radioinfo_src(meta)
        with self._lock:
            self.last_radio_at = time.time()
            if self.live_band == band:
                self._pending_band = None
                self._pending_count = 0
                return False
            if self.live_band is None:
                self.live_band = band
                prev = None
            else:
                if self._pending_band != band:
                    self._pending_band = band
                    self._pending_count = 1
                    return False
                self._pending_count += 1
                if self._pending_count < _BAND_CONFIRM_PACKETS:
                    return False
                prev = self.live_band
                self.live_band = band
                self._pending_band = None
                self._pending_count = 0
        _log_line(
            f"log-agent: N1MM band -> {band}"
            + (f" (was {prev})" if prev else " (first RadioInfo)")
            + extra
        )
        return True

    def note_ignored_radioinfo(self, reason: str, meta: dict, band: str) -> bool:
        """True once per (reason, station, radio, band) so Details is not spammed."""
        key = (
            reason,
            str(meta.get("station") or meta.get("netbios") or ""),
            str(meta.get("radio_nr") or ""),
            band,
        )
        with self._lock:
            if key in self._ignore_logged:
                return False
            self._ignore_logged.add(key)
            return True


def _radioinfo_src(meta: dict | None) -> str:
    """Short RadioInfo source suffix for the band-change log line."""
    if not meta:
        return ""
    bits: list[str] = []
    radio = meta.get("radio_nr")
    if radio:
        bits.append(f"radio={radio}")
    station = meta.get("station") or meta.get("netbios")
    if station:
        bits.append(f"station={station}")
    return ("  " + " ".join(bits)) if bits else ""


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
    with state._lock:
        tcp_live = bool(state.tcp_client and state.tcp_client.alive)
    # Do not connect-and-close :52001 while we already hold the JTDX session —
    # that RST is what pops N1MM's error box.
    tcp_probe = (lambda _h, _p: True) if tcp_live else None
    rep = run_checks(
        live_band=snap["live_band"],
        expect_band=snap["expect_band"],
        radio_port=snap["radio_port"],
        radio_group=snap["radio_group"],
        group=snap["group"],
        mcast_port=snap["mcast_port"],
        delivery_host=host,
        delivery_udp_port=udp_port,
        joined=joined,
        dry_run=snap["dry_run"],
        tcp_probe=tcp_probe,
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


def _status_model(state: LogState) -> AgentStatusModel:
    s = state.snapshot()
    band = s["live_band"]
    title = f"WIMS log agent · {band or '...'}"
    # Hear = RadioInfo listen (fleet: localhost). Deliver = localhost N1MM ingest.
    radio_dest = (
        f"{s['radio_group']}:{s['radio_port']}" if s.get("radio_group")
        else f"127.0.0.1:{s['radio_port']}"
    )
    if s.get("radio_group"):
        radio_hear = f"Hear RadioInfo {radio_dest}"
    else:
        radio_hear = f"Hear RadioInfo {radio_dest} (this PC only)"

    fix = ""
    if s["join_error"]:
        level, banner = "err", "Cannot join fleet multicast"
        fix = str(s["join_error"])
    elif s["radio_error"]:
        level, banner = "err", "Cannot hear N1MM RadioInfo"
        fix = (
            f"{s['radio_error']} — N1MM Broadcast Data > Radio → "
            f"{radio_dest}"
        )
    elif not band:
        level, banner = "warn", "Waiting for N1MM band"
        fix = (
            f"N1MM Broadcast Data > Radio → {radio_dest} "
            f"(fleet dest is 127.0.0.1:12060 on the logger PC)"
        )
    elif s["check_severity"] == "error":
        level, banner = "err", f"Log agent — {band}"
        # First error line from checks, if any.
        for ln in s["check_lines"] or []:
            if ln.startswith("[XX]"):
                fix = ln[4:].strip()
                break
        fix = fix or "See Details"
    elif s["check_severity"] == "warn":
        level, banner = "warn", f"Running — {band}"
        for ln in s["check_lines"] or []:
            if ln.startswith("[! ]"):
                fix = ln[4:].strip()
                break
        fix = fix or "Warnings in Details"
    else:
        level, banner = "ok", f"Ready — {band}"
        fix = "Forwarding this band’s Logged QSOs to local N1MM"

    mcast = "joined" if s["joined"] else ("failed" if s["join_error"] else "...")
    facts = [
        f"Band {band or '-'}   FWD {s['n_fwd']}   DROP {s['n_drop']}   WAIT {s['n_wait']}",
        f"WSJT mcast {s['group']}:{s['mcast_port']} {mcast}",
        radio_hear + (f" — {s['radio_note']}" if s["radio_note"] else ""),
        (
            f"Deliver to local N1MM TCP :{s.get('tcp_port', DEFAULT_TCP_PORT)} "
            f"then UDP {s['delivery']} (localhost is correct here)"
            if not s["dry_run"] else "Deliver dry-run"
        ),
        f"Last {s['last_fwd'] or '- none yet -'}",
    ]
    if s.get("last_delivery"):
        facts.append(f"Sent via {s['last_delivery']}")
    if s["last_error"]:
        facts.append(f"Error: {s['last_error']}")

    details = s["check_lines"] or []
    hover_bits = [
        banner,
        fix,
        "",
        *facts,
        "",
        "Config check:",
        *(details if details else ["(none yet — press Rescan)"]),
    ]
    return AgentStatusModel(
        title=title,
        banner_level=level,
        banner_text=banner,
        fix_text=fix,
        fact_lines=facts,
        detail_lines=details,
        hover_text="\n".join(hover_bits),
        site_url=s["site_url"],
    )


def _open_radio_socket(
    port: int,
    group: str | None = DEFAULT_RADIO_GROUP,
    iface: str = "0.0.0.0",
) -> tuple[socket.socket, str, str | None]:
    """Open the N1MM RadioInfo listener; return (socket, where, warning).

    Fleet dest is 127.0.0.1:12060 — bind loopback only so other loggers on
    the LAN cannot drive this PC's live band. Lab ``--radio-group`` joins
    multicast (bind all interfaces; unicast still heard). If the IGMP join
    fails, fall back to unicast and report that as the warning.
    """
    import struct

    from wims.udp.sink import _join_iface_ip

    group = (group or "").strip() or None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_host = "" if group else "127.0.0.1"
    try:
        sock.bind((bind_host, port))
    except OSError:
        sock.close()
        raise
    warn: str | None = None
    if group:
        try:
            join_if = _join_iface_ip(iface)
            mreq = struct.pack(
                "4s4s", socket.inet_aton(group), socket.inet_aton(join_if))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(0.5)
            return sock, f"{group}:{port} (+unicast :{port})", None
        except OSError as e:
            warn = f"multicast join {group} failed ({e}); unicast :{port} only"
    sock.settimeout(0.5)
    where = f"127.0.0.1:{port}" if bind_host == "127.0.0.1" else f"0.0.0.0:{port}"
    return sock, where, warn


def _radio_loop(state: LogState, stop: threading.Event) -> None:
    try:
        sock, where, warn = _open_radio_socket(
            state.radio_port,
            state.radio_group,
            iface=getattr(state, "radio_iface", None) or "0.0.0.0",
        )
    except OSError as e:
        with state._lock:
            state.radio_error = str(e)
        _log_line(f"log-agent: RadioInfo listen failed: {e}")
        rescan(state)
        return
    if warn:
        with state._lock:
            state.radio_note = warn
        _log_line(f"log-agent: RadioInfo: {warn}")
    _log_line(f"log-agent: Broadcast listen on {where}")
    while not stop.is_set():
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError as e:
            with state._lock:
                state.last_error = f"Broadcast recv: {e}"
            break
        text = data.decode("utf-8", "replace")
        with state._lock:
            state.last_radio_at = time.time()
        band, meta = band_from_radioinfo_xml(text)
        if band and band != "?":
            reason = radioinfo_ignore_reason(
                meta,
                hostname=state.host,
                filter_station=bool(state.radio_group),
            )
            if reason:
                if state.note_ignored_radioinfo(reason, meta, band):
                    _log_line(
                        f"log-agent: ignoring RadioInfo ({reason}) "
                        f"band={band} radio={meta.get('radio_nr') or '-'} "
                        f"active={meta.get('active_radio_nr') or '-'} "
                        f"station={meta.get('station') or meta.get('netbios') or '-'}"
                    )
            elif state.set_live_band(band, meta):
                rescan(state)
        # Fleet: N1MM → 127.0.0.1:12060 → site server (presence + contacts).
        fwd = state.broadcast_fwd
        if fwd is not None:
            fwd.maybe_forward(text)
    try:
        sock.close()
    except OSError:
        pass


def _forward_loop(state: LogState, args: argparse.Namespace, stop: threading.Event) -> None:
    nhost, _, nport = args.n1mm.partition(":")
    host = nhost or "127.0.0.1"
    udp_port = int(nport or "2333")
    tcp_port = int(getattr(args, "tcp_port", DEFAULT_TCP_PORT) or DEFAULT_TCP_PORT)
    tcp_client = N1mmTcpClient(host, tcp_port)
    with state._lock:
        state.tcp_client = tcp_client
    try:
        sock = open_socket(args.iface, args.port, args.group)
    except OSError as e:
        with state._lock:
            state.join_error = str(e)
            state.joined = False
            state.running = False
            state.tcp_client = None
        tcp_client.close()
        _log_line(f"log-agent: join failed: {e}")
        rescan(state)
        return

    with state._lock:
        state.joined = True
        state.join_error = None
        state.running = True
        state.tcp_port = tcp_port
    rescan(state)
    dest = "DRY-RUN" if args.dry_run else f"TCP :{tcp_port} then UDP {host}:{udp_port}"
    _log_line(
        f"log-agent: host={state.host}  join {args.group}:{args.port}  {dest}"
    )
    _log_line("          Filter band comes from N1MM RadioInfo (waiting until heard).")
    # ASCII-only: Windows cp1252 consoles mangle em-dashes.
    _log_line("          Enable N1MM Configurer > WSJT/JTDX Setup > JTDX/Others TCP "
              f"(:{tcp_port}) - keep that TCP session open; UDP :{udp_port} is fallback only.")

    seen: set[tuple] = set()
    sock.settimeout(0.5)
    try:
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
            rec = qso_record(msg)
            if rec is None:
                continue
            adif, call, qband = rec
            if not call:
                # A record with no CALL is useless to N1MM (blank log row)
                # and hints at a parse problem — surface it, don't forward.
                _log_line(
                    f"{time.strftime('%H:%M:%S')}  SKIP {msg.id} type={msg.type} "
                    f"no CALL in record  from {addr[0]}"
                )
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
            key = (msg.id, call.upper(), qband)
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
                ok, how = deliver_to_n1mm(
                    payload, host=host, udp_port=udp_port, tcp_port=tcp_port,
                    tcp_client=tcp_client,
                )
                with state._lock:
                    state.last_delivery = how
                    if not ok:
                        state.last_error = how
                _log_line(
                    f"{time.strftime('%H:%M:%S')}  SEND {'OK' if ok else 'FAIL'} via {how}"
                )
    finally:
        with state._lock:
            state.running = False
            state.tcp_client = None
        try:
            sock.close()
        except OSError:
            pass
        tcp_client.close()


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
    ap.add_argument(
        "--radio-group", default="",
        help="N1MM RadioInfo multicast group. Empty (fleet default) = "
             "127.0.0.1:12060 only. Lab: 224.0.0.73 (hears every logger).",
    )
    ap.add_argument("--n1mm", default="127.0.0.1:2333",
                    help="UDP fallback host:port for N1MM ADIF ingest (default 127.0.0.1:2333)")
    ap.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT,
                    help="N1MM JTDX/Others TCP port (default 52001; tried first)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print matching QSOs, do not send to N1MM")
    ap.add_argument("--gui", dest="gui", action="store_true", default=True,
                    help="show compact Tk status window (default)")
    ap.add_argument("--no-gui", dest="gui", action="store_false",
                    help="console only (lab / headless)")
    args = ap.parse_args(argv)

    # Singleton — second Log agent on the same PC must fail (not silently
    # double-FWD). A running merged seat (wims.seat --log, kind n1mm_seat)
    # forwards too, so it counts.
    other = None
    try:
        from wims.launcher.process_replace import other_agent_running
        for kind in ("log", "n1mm_seat"):
            other = other_agent_running(kind)  # type: ignore[arg-type]
            if other is not None:
                break
    except Exception:
        other = None
    if other is not None:
        print(
            f"ERROR: log agent already running (pid {other.pid}).\n"
            f"  {other.cmdline}\n"
            f"  Stop the existing Log agent before starting another.",
            file=sys.stderr,
            flush=True,
        )
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
        target=_radio_loop, args=(state, stop), daemon=True,
    )
    fwd_thread = threading.Thread(
        target=_forward_loop, args=(state, args, stop), daemon=True,
    )
    radio_thread.start()
    fwd_thread.start()

    if args.gui:
        try:
            win = AgentStatusWindow(
                refresh=lambda: _status_model(state),
                on_rescan=lambda: rescan(state),
                on_quit=lambda: stop.set(),
            )
            win.run()
        except Exception as e:
            _log_line(f"log-agent: GUI unavailable ({e}); continuing console-only")
            args.gui = False

    if not args.gui:
        try:
            while fwd_thread.is_alive() or radio_thread.is_alive():
                fwd_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            stop.set()
            _log_line("log-agent: quit")
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
