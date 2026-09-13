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

from wims.core.bands import band_label, rf_band, rf_hz
from wims.agent_ui import AgentStatusModel, AgentStatusWindow
from wims.log import GROUP, PORT
from wims.log.check import run_checks
from wims.log.pfx import lookup_pfx
from wims.log.radioinfo import band_from_radioinfo_xml, radioinfo_ignore_reason
from wims.udp import messages as M
from wims.udp.sink import open_socket

_ADIF_BAND = re.compile(r"<BAND:(\d+)>([^<]+)", re.I)
_ADIF_FREQ = re.compile(r"<FREQ:(\d+)>([^<]+)", re.I)
_ADIF_CALL = re.compile(r"<CALL:(\d+)>([^<]*)", re.I)
_ADIF_HAS_DATE = re.compile(r"<QSO_DATE:", re.I)
_ADIF_HAS_TIME = re.compile(r"<TIME_ON:", re.I)
_ADIF_FIELD = re.compile(
    r"<([A-Za-z0-9_]+):(\d+)(?::[^>]*)?>([^<]*)", re.I,
)
_ADIF_EOH = re.compile(r"<eoh>", re.I)
_WSJT_ID_PREFIX = re.compile(r"^(?:WSJT-X|JTDX)\s*[-–—]\s*", re.I)
# N1MM TCP Log whitelist (Sending Log Data). Extra tags (EOH, STATION_CALLSIGN)
# make its parser miss CALL → blank Call in the contest log.
_N1MM_LOG_TAGS = (
    "CALL", "QSO_DATE", "TIME_ON", "CONTEST_ID", "MODE", "FREQ", "FREQ_RX",
    "BAND", "COMMENT", "CQZ", "ITUZ", "GRIDSQUARE", "NAME", "RST_RCVD",
    "RST_SENT", "TX_PWR", "RX_PWR", "SRX", "STX", "QTH", "OPERATOR",
    "RADIO_NR", "POINTS", "PFX", "STATE", "SECTION", "ARRL_SECT", "EOR",
)

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
# TCP sendall() succeeding does not mean N1MM inserted. Confirm via Broadcast
# <contactinfo> on :12060; if that never arrives, reconnect + UDP retry.
_CONFIRM_WAIT_S = 1.5
_CONFIRM_MAX_TRIES = 3


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
            # WSJT-X BAND on a transverter is the IF (10m/15m). Map to RF
            # the same way band_label/rf_band do (WIMS_TRANSVERTER=0 disables).
            return rf_band(label)
        # Unknown BAND tag — fall through to FREQ.
    m = _ADIF_FREQ.search(adif or "")
    if m:
        try:
            mhz = float(m.group(2).strip())
        except ValueError:
            return None
        return band_label(int(mhz * 1_000_000))
    return None


def rewrite_adif_rf(adif: str) -> str:
    """Lift IF FREQ/BAND to RF before N1MM TCP Log (28 MHz → 432, 10m → 70cm)."""
    text = adif or ""
    m = _ADIF_FREQ.search(text)
    if m:
        try:
            mhz = float(m.group(2).strip())
        except ValueError:
            mhz = 0.0
        if mhz > 0:
            hz = rf_hz(int(mhz * 1_000_000))
            s = f" {hz / 1e6:.6f}".strip()
            repl = f"<FREQ:{len(s)}>{s}"
            text = text[: m.start()] + repl + text[m.end():]
    lab = adif_band(text)
    if lab:
        token = _n1mm_band_token(lab)
        mb = _ADIF_BAND.search(text)
        if mb:
            repl = f"<BAND:{len(token)}>{token}"
            text = text[: mb.start()] + repl + text[mb.end():]
    return text


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


def _adif_has(adif: str, tag: str) -> bool:
    return bool(re.search(rf"<{re.escape(tag)}:\d+>", adif or "", re.I))


def _adif_append(adif: str, tag: str, value: str | int | None) -> str:
    """Insert ``<TAG:n>value`` before ``<eor>`` if missing and value is set."""
    if value is None:
        return adif
    s = str(value).strip()
    if not s or _adif_has(adif, tag):
        return adif
    piece = f"<{tag}:{len(s)}>{s}"
    text = adif or ""
    low = text.lower()
    idx = low.rfind("<eor>")
    if idx >= 0:
        return text[:idx].rstrip() + piece + " <eor>"
    return text + piece


def parse_adif_fields(adif: str) -> dict[str, str]:
    """Map ADIF tag → value. Skip the header before ``<eoh>``. Honor :len:."""
    text = adif or ""
    eoh = _ADIF_EOH.search(text)
    if eoh:
        text = text[eoh.end():]
    out: dict[str, str] = {}
    for m in _ADIF_FIELD.finditer(text):
        tag = m.group(1).upper()
        if tag == "EOR":
            break
        try:
            n = int(m.group(2))
        except ValueError:
            continue
        raw = m.group(3)
        out[tag] = raw[:n] if n <= len(raw) else raw
    return out


# JTDX TCP :52001: lowercase tags, no header/EOH, <call: first (after the
# leading space wrap_adif puts in N). OPERATOR is the WSJT-X rig-name for now.
_N1MM_WIRE_TAGS = (
    "call", "gridsquare", "mode", "rst_sent", "rst_rcvd",
    "qso_date", "time_on", "band", "freq", "tx_pwr", "name", "comment",
    "operator",
)


def operator_from_instance_id(instance_id: str | None) -> str | None:
    """Rig-name for N1MM OPERATOR. Drop the redundant ``WSJT-X - `` prefix."""
    s = (instance_id or "").strip()
    if not s:
        return None
    s = _WSJT_ID_PREFIX.sub("", s).strip()
    return s or None


def rebuild_n1mm_adif(adif: str, *, operator: str | None = None) -> str:
    """One JTDX-style QSO record: lowercase tags, <call: first, no EOH."""
    f = parse_adif_fields(adif)
    call = (f.get("CALL") or "").strip().split()[0].upper()
    if call:
        f["CALL"] = call
    freq = (f.get("FREQ") or "").strip()
    if freq:
        try:
            mhz = float(freq)
            hz = rf_hz(int(mhz * 1_000_000))
            if hz > 0:
                f["FREQ"] = f"{hz / 1e6:.6f}"
        except ValueError:
            pass
    band = f.get("BAND") or ""
    if band:
        lab = adif_band(
            f"<BAND:{len(band)}>{band}"
            + (f"<FREQ:{len(f.get('FREQ') or '')}>{f.get('FREQ')}" if f.get("FREQ") else "")
        ) or band
        f["BAND"] = _n1mm_band_token(lab)
    grid = (f.get("GRIDSQUARE") or "").strip().upper()
    if grid:
        f["GRIDSQUARE"] = grid
    op = (operator or "").strip()
    if op:
        f["OPERATOR"] = op
    parts: list[str] = []
    for tag in _N1MM_WIRE_TAGS:
        val = (f.get(tag.upper()) or "").strip()
        if not val:
            continue
        parts.append(f"<{tag}:{len(val)}>{val}")
    return " ".join(parts) + " <eor>"


def normalize_adif_call(adif: str) -> str:
    """Rewrite CALL so N1MM gets a real callsign.

    WSJT-X LoggedADIF often uses ``<call:6>K1ABC `` (trailing space counted in
    length). N1MM TCP Log then inserts a row with a blank Call field.
    """
    text = adif or ""
    m = _ADIF_CALL.search(text)
    if not m:
        return text
    raw = m.group(2)
    call = raw.strip().split()[0] if raw.strip() else ""
    if not call:
        return text
    new = f"<CALL:{len(call)}>{call}"
    rest = text[m.end():]
    if rest.lstrip().startswith("<") and not new.endswith(" "):
        new += " "
    return text[:m.start()] + new + rest


def enrich_n1mm_adif(adif: str, *, call: str | None = None) -> str:
    """Fill Callsign Info fields N1MM skips on TCP Log (no Entry-window lookup).

    Documented Log tags include PFX, CQZ, ITUZ, NAME, COMMENT. Country in
    Edit Contact follows PFX/CQZ from this record, not a later CTY pass.
    """
    text = adif or ""
    if call is None:
        m = _ADIF_CALL.search(text)
        call = m.group(2).strip() if m else None
    hit = lookup_pfx(call or "")
    if hit:
        pfx, cqz, ituz = hit
        text = _adif_append(text, "PFX", pfx)
        text = _adif_append(text, "CQZ", cqz)
        text = _adif_append(text, "ITUZ", ituz)
    return text


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


def wrap_adif(adif: str, *, operator: str | None = None) -> bytes:
    """N1MM Secondary-UDP / JTDX-TCP ingest envelope (Sending Log Data).

    ``<command:3>Log <parameters:N>`` + ADIF + EOR. Raw ADIF alone is often ignored.
    ``operator`` is the WSJT-X rig-name (UDP id) until seats identify by call.
    """
    text = ensure_adif_datetime((adif or "").strip())
    text = rewrite_adif_rf(text)
    text = rebuild_n1mm_adif(text, operator=operator)
    if "<eor>" not in text.lower():
        text += " <eor>"
    raw = text.encode("ascii", "replace")
    # N1MM LoggingTCP (measured 2026-09-13 on this PC, ham.s3db):
    # it discards the first byte after ``<parameters:N>`` then searches
    # ``<call:``. If the ADIF starts at that byte, Call is stored empty
    # while gridsquare/mode/freq/band still parse. A leading space *inside
    # N* fixes it. Confirmed: wrap_adif without space → Call=''; space in N
    # → Call='W9WIMS'; WSJT ``<EOH>`` blob also works (first byte is not
    # the ``<`` of ``<call:``). Newline after EOR is not in N.
    raw = b" " + raw
    header = f"<command:3>Log <parameters:{len(raw)}>"
    return header.encode("ascii") + raw + b"\n"


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
    """N1MM JTDX/Others TCP logger (:52001), one connection per Log envelope.

    N1MM reads ``<parameters:N>`` then exactly N bytes on that TCP stream.
    Keeping the socket open across QSOs means one truncated send (seat
    killed mid-write, wrong N, RST) leaves N1MM blocked waiting for the
    rest of the *previous* message. Later sendall() succeeds — TCP is
    fine — and nothing inserts. That is the black hole.

    JTDX keeps a session open. Connect-then-RST per QSO inserts but N1MM
    pops ``Unable to read data from the transport connection``. We FIN
    (graceful close) after each send so framing cannot carry over and
    N1MM sees EOF, not a reset.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_TCP_PORT) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self.last_error: str | None = None
        self._reachable = False

    @property
    def alive(self) -> bool:
        """N1MM accepted a TCP connect recently (socket is not held idle)."""
        return self._reachable

    def send(self, payload: bytes) -> None:
        """Connect, send one Log, FIN. Next QSO gets a new accept/read."""
        try:
            sock = self._ensure()
            try:
                sock.sendall(payload)
            except OSError:
                self.close()
                sock = self._ensure()
                sock.sendall(payload)
        finally:
            self.close()

    def try_connect(self) -> bool:
        """Probe that N1MM :52001 accepts. Do **not** hold the socket.

        An idle hold wedges N1MM LoggingTCP (single accept/read). Later
        sendall() times out, UDP :2333 reports OK but does not insert, and
        Operate/N1MM look like logging has 'stopped'.
        """
        sock = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=2.0)
            self.last_error = None
            self._reachable = True
            return True
        except OSError as e:
            self.last_error = str(e)
            self._reachable = False
            return False
        finally:
            if sock is not None:
                _graceful_close(sock)

    def reconnect(self) -> bool:
        """Drop any half-open socket. Next send() opens a fresh one."""
        self.close()
        self._reachable = False
        return self.try_connect()

    def _ensure(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        sock = socket.create_connection((self.host, self.port), timeout=3.0)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        try:
            sock.settimeout(3.0)
        except (OSError, AttributeError):
            pass
        self._sock = sock
        self.last_error = None
        self._reachable = True
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
        adif = normalize_adif_call(ensure_adif_datetime(msg.adif))
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
    call = (msg.dx_call or "").strip()
    grid = (msg.dx_grid or "").strip()
    mode = (msg.mode or "").strip()
    my = (msg.my_call or "").strip()
    myg = (msg.my_grid or "").strip()
    rst_s = (msg.report_sent or "").strip()
    rst_r = (msg.report_received or "").strip()
    # Spaces between fields — N1MM TCP Log example format. CALL length must
    # match the trimmed call or N1MM inserts a blank Call.
    parts = [
        f"<CALL:{len(call)}>{call}",
        f"<GRIDSQUARE:{len(grid)}>{grid}",
        f"<MODE:{len(mode)}>{mode}",
        f"<FREQ:{len(f'{mhz:.6f}')}>{mhz:.6f}",
        f"<BAND:{len(band)}>{band}",
        f"<QSO_DATE:{len(qdate)}>{qdate}",
        f"<TIME_ON:{len(qtime)}>{qtime}",
        f"<STATION_CALLSIGN:{len(my)}>{my}",
        f"<MY_GRIDSQUARE:{len(myg)}>{myg}",
        f"<RST_SENT:{len(rst_s)}>{rst_s}",
        f"<RST_RCVD:{len(rst_r)}>{rst_r}",
    ]
    if msg.name and str(msg.name).strip():
        n = str(msg.name).strip()
        parts.append(f"<NAME:{len(n)}>{n}")
    if msg.comments and str(msg.comments).strip():
        c = str(msg.comments).strip()
        parts.append(f"<COMMENT:{len(c)}>{c}")
    if msg.tx_power and str(msg.tx_power).strip():
        p = str(msg.tx_power).strip()
        parts.append(f"<TX_PWR:{len(p)}>{p}")
    # OPERATOR on the wire is the rig-name, injected in wrap_adif — not WSJT-X
    # Settings operator (that becomes a callsign later).
    return " ".join(parts) + " <eor>"


def _send_udp(payload: bytes, host: str, udp_port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, (host, udp_port))
    finally:
        sock.close()


def deliver_to_n1mm(
    payload: bytes,
    *,
    host: str = "127.0.0.1",
    udp_port: int = 2333,
    tcp_port: int = DEFAULT_TCP_PORT,
    prefer_tcp: bool = True,
    tcp_client: N1mmTcpClient | None = None,
    also_udp: bool = False,
) -> tuple[bool, str]:
    """Deliver Log envelope to local N1MM. Prefer TCP 52001 (has a real handshake).

    UDP 2333 sendto() always looks successful even when nothing is listening —
    that is why agents can report FWD with no N1MM insert.

    ``tcp_client`` opens a new TCP session per Log and FINs after send so
    N1MM cannot stay blocked on a previous length-prefixed message.

    ``also_udp``: also unicast localhost :2333 (retry path). Harmless if
    N1MM is not bound there.
    """
    errors: list[str] = []
    hows: list[str] = []
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
            hows.append(f"TCP {host}:{tcp_port}")
        except OSError as e:
            errors.append(f"TCP {tcp_port}: {e}")
            if tcp_client is not None:
                tcp_client.close()
    if also_udp or not hows:
        try:
            _send_udp(payload, host, udp_port)
            hows.append(f"UDP {host}:{udp_port}")
            if errors:
                hows[-1] += " (TCP failed: " + "; ".join(errors) + ")"
        except OSError as e:
            errors.append(f"UDP {udp_port}: {e}")
            if not hows:
                return False, "; ".join(errors)
    return True, " + ".join(hows)


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
        self.n_logged = 0
        self._log_keys: set[tuple] = set()
        self.last_wsjt_mono: float = 0.0
        self.log_rejoins: int = 0
        self.log_rebinds: int = 0
        self.n_unconfirmed = 0
        self.last_fwd: str | None = None
        self.last_delivery: str | None = None
        self.last_error: str | None = None
        # WSJT Logged QSO waiting for N1MM <contactinfo> (same process hears :12060).
        self._pending: list[dict] = []
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
                "n_logged": self.n_logged,
                "log_rejoins": self.log_rejoins,
                "log_rebinds": self.log_rebinds,
                "n_unconfirmed": self.n_unconfirmed,
                "n_pending": sum(1 for p in self._pending if not p.get("confirmed")),
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
                "tcp_alive": bool(self.tcp_client and self.tcp_client.alive),
                "tcp_error": (
                    getattr(self.tcp_client, "last_error", None)
                    if self.tcp_client is not None else None
                ),
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

    def note_n1mm_contact(self, call: str, band: str | None, now: float) -> bool:
        """Mark a pending WSJT forward confirmed if N1MM broadcast this QSO.

        Returns True if at least one pending row matched.
        """
        call_u = (call or "").strip().upper()
        if not call_u:
            return False
        band_n = (band or "").strip().lower() or None
        hit = False
        with self._lock:
            for p in self._pending:
                if p.get("confirmed"):
                    continue
                if p["call"] != call_u:
                    continue
                if band_n and p.get("band") and p["band"] != band_n:
                    # N1MM <band>2</band> parses as 160m; still ack a VHF pending.
                    vhf = {
                        "6m", "2m", "1.25m", "70cm", "33cm", "23cm",
                        "13cm", "9cm", "6cm", "3cm", "1.2cm",
                    }
                    if band_n in vhf:
                        continue
                p["confirmed"] = True
                p["acked_at"] = now
                hit = True
        return hit

    def track_pending(
        self, *, call: str, band: str | None, payload: bytes, instance: str,
        now: float,
    ) -> dict:
        row = {
            "call": (call or "").strip().upper(),
            "band": (band or "").strip().lower() or None,
            "payload": payload,
            "instance": instance,
            "tries": 1,
            "last_send": now,
            "confirmed": False,
        }
        with self._lock:
            self._pending.append(row)
        return row

    def take_confirmed(self) -> list[dict]:
        """Remove and return pending rows N1MM has acked."""
        done: list[dict] = []
        with self._lock:
            keep: list[dict] = []
            for p in self._pending:
                if p.get("confirmed"):
                    done.append(p)
                    self.n_logged += 1
                else:
                    keep.append(p)
            self._pending = keep
        return done

    def due_retries(self, now: float) -> list[dict]:
        """Pending rows whose confirm wait expired; exhausted ones are dropped."""
        retry: list[dict] = []
        failed: list[dict] = []
        with self._lock:
            keep: list[dict] = []
            for p in self._pending:
                if p.get("confirmed"):
                    keep.append(p)
                    continue
                if now - float(p["last_send"]) < _CONFIRM_WAIT_S:
                    keep.append(p)
                    continue
                if int(p["tries"]) >= _CONFIRM_MAX_TRIES:
                    failed.append(p)
                    self.n_unconfirmed += 1
                    continue
                retry.append(p)
                keep.append(p)
            self._pending = keep
        for p in failed:
            _log_line(
                f"{time.strftime('%H:%M:%S')}  UNCONFIRMED  {p.get('instance') or ''} "
                f"{p['call']} {p.get('band') or '?'} - N1MM did not insert. "
                f"Log it by hand."
            )
        return retry

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
    elif s.get("n_unconfirmed"):
        level, banner = "warn", f"N1MM missed {s['n_unconfirmed']} WSJT QSO(s)"
        fix = (
            "Configurer > WSJT/JTDX Setup > Enable JTDX/Others TCP, then "
            "log the missed call by hand. WIMS retried TCP+UDP and got no insert."
        )
    else:
        level, banner = "ok", f"Ready — {band}"
        fix = "Forwarding this band’s Logged QSOs to local N1MM"

    mcast = "joined" if s["joined"] else ("failed" if s["join_error"] else "...")
    facts = [
        f"Band {band or '-'}   FWD {s['n_fwd']}   LOGGED {s.get('n_logged', 0)}   "
        f"UNCONF {s.get('n_unconfirmed', 0)}   DROP {s['n_drop']}   WAIT {s['n_wait']}",
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


def _note_contact_broadcast(state: LogState, text: str) -> None:
    """If this Broadcast datagram is a logged QSO, ack a pending WSJT forward."""
    if "<contactinfo" not in text.lower() and "<contactreplace" not in text.lower():
        return
    try:
        from wims.integrations.n1mm.qso import LoggedQso
        q = LoggedQso.from_contactinfo(text)
    except Exception:
        return
    state.note_n1mm_contact(q.call, q.band, time.time())


def _pump_pending(
    state: LogState,
    tcp_client: N1mmTcpClient,
    *,
    host: str,
    udp_port: int,
    tcp_port: int,
    dry_run: bool,
) -> None:
    """Confirm N1MM inserts; reconnect+UDP-retry if contactinfo never arrives."""
    now = time.time()
    for p in state.take_confirmed():
        _log_line(
            f"{time.strftime('%H:%M:%S')}  LOGGED  {p.get('instance') or ''} "
            f"{p['call']} {p.get('band') or '?'}"
        )
    if dry_run:
        return
    for p in state.due_retries(now):
        p["tries"] = int(p["tries"]) + 1
        p["last_send"] = now
        ok, how = deliver_to_n1mm(
            p["payload"], host=host, udp_port=udp_port, tcp_port=tcp_port,
            tcp_client=tcp_client, also_udp=True,
        )
        with state._lock:
            state.last_delivery = how
            if not ok:
                state.last_error = how
        _log_line(
            f"{time.strftime('%H:%M:%S')}  RETRY {p['tries']}/{_CONFIRM_MAX_TRIES}  "
            f"{p.get('instance') or ''} {p['call']} {p.get('band') or '?'}  "
            f"{'OK' if ok else 'FAIL'} via {how}"
        )


def apply_logged_qso(
    state: LogState,
    *,
    instance: str,
    call: str,
    band: str | None,
    adif: str,
    src: str,
    dry_run: bool,
    host: str,
    udp_port: int,
    tcp_port: int,
) -> bool:
    """Filter + deliver one Logged QSO. True if forwarded (or WAIT/DROP logged)."""
    call_u = (call or "").strip().upper()
    if not call_u:
        _log_line(
            f"{time.strftime('%H:%M:%S')}  SKIP {instance} no CALL in record  from {src}"
        )
        return False
    qband = band or "?"
    pin = state.snapshot()["live_band"]
    if not pin:
        with state._lock:
            state.n_wait += 1
        _log_line(
            f"{time.strftime('%H:%M:%S')}  WAIT {instance} {call_u} "
            f"band={qband} (no N1MM band yet)  from {src}"
        )
        return False
    if qband != pin:
        with state._lock:
            state.n_drop += 1
        _log_line(
            f"{time.strftime('%H:%M:%S')}  DROP {instance} {call_u} "
            f"band={qband} (want {pin})  from {src}"
        )
        return False
    key = (instance, call_u, qband)
    with state._lock:
        if key in state._log_keys:
            return False
        state._log_keys.add(key)
    payload = wrap_adif(adif or "", operator=operator_from_instance_id(instance))
    with state._lock:
        state.n_fwd += 1
        state.last_fwd = (
            f"{time.strftime('%H:%M:%S')} {call_u} {qband} ({len(payload)} B)"
        )
        n_fwd, n_drop = state.n_fwd, state.n_drop
        tcp_client = state.tcp_client
    _log_line(
        f"{time.strftime('%H:%M:%S')}  FWD  {instance} {call_u} {qband}  "
        f"{len(payload)} B  ({n_fwd} fwd / {n_drop} drop)  via {src}"
    )
    try:
        i = payload.lower().find(b"<call:")
        chunk = payload[i:i + 200] if i >= 0 else payload[:200]
        _log_line("          ADIF " + chunk.decode("ascii", "replace").strip())
    except Exception:
        pass
    if dry_run:
        return True
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
    state.track_pending(
        call=call_u, band=qband, payload=payload,
        instance=instance, now=time.time(),
    )
    return True


def _pull_site_logged(
    state: LogState,
    args: argparse.Namespace,
    host: str,
    udp_port: int,
    tcp_port: int,
    since: float,
) -> float:
    """Backup: QSOs the site server heard on 2237 even if this seat's join is deaf."""
    base = (state.snapshot().get("site_url") or "").rstrip("/")
    if not base:
        return since
    import json
    import urllib.error
    import urllib.request
    url = f"{base}/api/logged-qsos?since={since:.3f}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=1.0) as r:
            body = json.loads(r.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return since
    newest = since
    for q in body.get("qsos") or []:
        try:
            ts = float(q.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts > newest:
            newest = ts
        apply_logged_qso(
            state,
            instance=str(q.get("instance") or "?"),
            call=str(q.get("call") or ""),
            band=q.get("band"),
            adif=str(q.get("adif") or ""),
            src="site-relay",
            dry_run=bool(args.dry_run),
            host=host, udp_port=udp_port, tcp_port=tcp_port,
        )
    return newest


def _site_logged_pull_loop(
    state: LogState,
    args: argparse.Namespace,
    stop: threading.Event,
    host: str,
    udp_port: int,
    tcp_port: int,
) -> None:
    since = time.time() - 5.0
    while not stop.wait(2.0):
        since = _pull_site_logged(
            state, args, host, udp_port, tcp_port, since,
        )


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
            _log_line(f"log-agent: Broadcast recv failed ({e}); rebinding")
            try:
                sock.close()
            except OSError:
                pass
            try:
                sock, where, warn = _open_radio_socket(
                    state.radio_port,
                    state.radio_group,
                    iface=getattr(state, "radio_iface", None) or "0.0.0.0",
                )
                _log_line(f"log-agent: Broadcast listen on {where}")
            except OSError as e2:
                _log_line(f"log-agent: Broadcast rebind failed: {e2}")
                if stop.wait(2.0):
                    break
            continue
        text = data.decode("utf-8", "replace")
        with state._lock:
            state.last_radio_at = time.time()
        _note_contact_broadcast(state, text)
        band, meta = band_from_radioinfo_xml(text)
        reason = None
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
        # Do not POST inactive-radio RadioInfo (SO2R flood → site timeouts).
        fwd = state.broadcast_fwd
        if fwd is not None and not reason:
            fwd.submit(text)
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
    if tcp_client.try_connect():
        _log_line(f"log-agent: N1MM TCP {host}:{tcp_port} connected")
    else:
        _log_line(
            f"log-agent: N1MM TCP {host}:{tcp_port} not open yet "
            f"({tcp_client.last_error or 'connection refused'}). "
            "Configurer > WSJT/JTDX Setup > JTDX/Others TCP, then restart N1MM."
        )
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
    dest = (
        "DRY-RUN" if args.dry_run
        else f"TCP {host}:{tcp_port} per QSO (UDP {host}:{udp_port} on retry)"
    )
    _log_line(
        f"log-agent: host={state.host}  join {args.group}:{args.port}  {dest}"
    )
    _log_line("          Filter band comes from N1MM RadioInfo (waiting until heard).")
    # ASCII-only: Windows cp1252 consoles mangle em-dashes.
    _log_line("          Enable N1MM Configurer > WSJT/JTDX Setup > JTDX/Others TCP "
              f"(:{tcp_port}) - keep that TCP session open; UDP :{udp_port} is fallback only.")

    if not getattr(state, "_pull_started", False):
        state._pull_started = True
        threading.Thread(
            target=_site_logged_pull_loop,
            args=(state, args, stop, host, udp_port, tcp_port),
            daemon=True, name="seat-log-pull",
        ).start()
        _log_line("log-agent: site Logged-QSO relay on (backup if multicast goes deaf)")
    sock.settimeout(0.5)
    last_rejoin = 0.0
    last_tcp_probe = 0.0
    last_rebind = 0.0
    iface = getattr(args, "iface", None) or "0.0.0.0"
    try:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                now_m = time.monotonic()
                if args.group and (now_m - last_rejoin) >= 30.0:
                    try:
                        from wims.udp.sink import rejoin_multicast
                        rejoin_multicast(sock, args.group, iface)
                        with state._lock:
                            state.log_rejoins += 1
                    except OSError:
                        pass
                    last_rejoin = now_m
                silent = (
                    state.last_wsjt_mono > 0.0
                    and (now_m - state.last_wsjt_mono) >= 25.0
                    and (now_m - last_rebind) >= 20.0
                )
                if silent and args.group:
                    _log_line(
                        "log-agent: no WSJT UDP for "
                        f"{now_m - state.last_wsjt_mono:.0f}s — rebinding {args.group}:{args.port}"
                    )
                    try:
                        ns = open_socket(iface, args.port, args.group)
                        ns.settimeout(0.5)
                        old, sock = sock, ns
                        try:
                            old.close()
                        except OSError:
                            pass
                        with state._lock:
                            state.log_rebinds += 1
                        last_rebind = now_m
                        last_rejoin = now_m
                    except OSError as e:
                        _log_line(f"log-agent: rebind failed: {e}")
                        last_rebind = now_m
                if not tcp_client.alive and (now_m - last_tcp_probe) >= 15.0:
                    last_tcp_probe = now_m
                    if tcp_client.try_connect():
                        _log_line(f"log-agent: N1MM TCP {host}:{tcp_port} connected")
                _pump_pending(
                    state, tcp_client,
                    host=host, udp_port=udp_port, tcp_port=tcp_port,
                    dry_run=bool(args.dry_run),
                )
                continue
            except OSError as e:
                with state._lock:
                    state.last_error = str(e)
                _log_line(f"log-agent: recv failed ({e}); rebinding")
                try:
                    sock.close()
                except OSError:
                    pass
                try:
                    sock = open_socket(iface, args.port, args.group)
                    sock.settimeout(0.5)
                    with state._lock:
                        state.log_rebinds += 1
                except OSError as e2:
                    _log_line(f"log-agent: rebind failed: {e2}")
                    if stop.wait(2.0):
                        break
                continue
            msg = M.parse(data)
            if msg is None:
                continue
            state.last_wsjt_mono = time.monotonic()
            rec = qso_record(msg)
            if rec is None:
                continue
            adif, call, qband = rec
            apply_logged_qso(
                state,
                instance=msg.id or "?",
                call=call or "",
                band=qband,
                adif=adif or "",
                src=addr[0],
                dry_run=bool(args.dry_run),
                host=host, udp_port=udp_port, tcp_port=tcp_port,
            )
            _pump_pending(
                state, tcp_client,
                host=host, udp_port=udp_port, tcp_port=tcp_port,
                dry_run=bool(args.dry_run),
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
