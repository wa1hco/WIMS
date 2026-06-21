"""WSJT-X UDP message parser (plan §3.1).

Decodes the big-endian QDataStream datagrams documented in WSJT-X's
``Network/NetworkMessage.hpp`` into typed events. Covers the outbound messages
WIMS consumes: Heartbeat, Status, Decode, Clear, QSO Logged, Close, WSPR Decode,
Logged ADIF. Unknown/inbound types are returned as ``UnknownMessage`` rather than
raising, per the protocol's "ignore silently" rule.

Encodings (Qt_5_2 = schema 2, Qt_5_4 = schema 3; identical for the fields used):
    quint8/bool   1 byte
    qint32/quint32 4 bytes, big-endian
    quint64       8 bytes
    double        8 bytes IEEE-754
    utf8          quint32 byte-length + bytes; length 0xFFFFFFFF == null
    QTime         quint32 msecs since midnight
    QDateTime     QDate(qint64 Julian day) + QTime(quint32) + timespec(quint8)
                  [+ qint32 offset if timespec==2]
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

MAGIC = 0xADBCCBDA

# Message type numbers (NetworkMessage::Type enum).
HEARTBEAT, STATUS, DECODE, CLEAR, REPLY, QSO_LOGGED, CLOSE = 0, 1, 2, 3, 4, 5, 6
REPLAY, HALT_TX, FREE_TEXT, WSPR_DECODE, LOCATION, LOGGED_ADIF = 7, 8, 9, 10, 11, 12

QUINT32_MAX = 0xFFFFFFFF

# A Maidenhead 4- or 6-char grid. "RR73" matches the shape but is an FT8 sign-off,
# never a grid in practice, so it is excluded by the extractor below.
_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.IGNORECASE)


class _Reader:
    """Sequential big-endian reader over a datagram, with bounds checks."""

    def __init__(self, data: bytes):
        self._d = data
        self._i = 0

    def _take(self, n: int) -> bytes:
        if self._i + n > len(self._d):
            raise ValueError(f"truncated: need {n} at offset {self._i} of {len(self._d)}")
        chunk = self._d[self._i : self._i + n]
        self._i += n
        return chunk

    def u8(self) -> int:
        return self._take(1)[0]

    def boolean(self) -> bool:
        return self._take(1)[0] != 0

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def double(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def u32_opt(self) -> int | None:
        """quint32 where 0xFFFFFFFF means 'not applicable'."""
        v = self.u32()
        return None if v == QUINT32_MAX else v

    def utf8(self) -> str | None:
        n = self.u32()
        if n == QUINT32_MAX:
            return None
        return self._take(n).decode("utf-8", "replace")

    def datetime(self) -> dict | None:
        """QDateTime -> dict, or None if the QDate is null (Julian day 0)."""
        julian = struct.unpack(">q", self._take(8))[0]
        msecs = self.u32()
        timespec = self.u8()
        offset = self.i32() if timespec == 2 else 0
        if julian == 0:
            return None
        return {"julian_day": julian, "msecs": msecs, "timespec": timespec, "offset": offset}

    def at_end(self) -> bool:
        return self._i >= len(self._d)


# --------------------------------------------------------------------------- #
# Typed events
# --------------------------------------------------------------------------- #


@dataclass
class WsjtxMessage:
    """Common header fields present on every message."""

    schema: int
    type: int
    id: str | None  # the emitting instance's unique key (the "WSJT-X id")


@dataclass
class Heartbeat(WsjtxMessage):
    max_schema: int | None = None
    version: str | None = None
    revision: str | None = None


@dataclass
class Status(WsjtxMessage):
    dial_frequency: int = 0
    mode: str | None = None
    dx_call: str | None = None
    report: str | None = None
    tx_mode: str | None = None
    tx_enabled: bool = False
    transmitting: bool = False
    decoding: bool = False
    rx_df: int = 0
    tx_df: int = 0
    de_call: str | None = None
    de_grid: str | None = None
    dx_grid: str | None = None
    tx_watchdog: bool = False
    sub_mode: str | None = None
    fast_mode: bool = False
    special_op_mode: int = 0
    frequency_tolerance: int | None = None
    tr_period: int | None = None
    config_name: str | None = None
    tx_message: str | None = None


@dataclass
class Decode(WsjtxMessage):
    new: bool = False
    time_ms: int = 0
    snr: int = 0
    delta_time: float = 0.0
    delta_frequency: int = 0
    mode: str | None = None
    message: str | None = None
    low_confidence: bool = False
    off_air: bool = False
    # Derived from the message text (see _interpret_decode):
    is_cq: bool = False
    dx_call: str | None = None
    grid: str | None = None


@dataclass
class Clear(WsjtxMessage):
    pass


@dataclass
class QSOLogged(WsjtxMessage):
    datetime_off: dict | None = None
    dx_call: str | None = None
    dx_grid: str | None = None
    tx_frequency: int = 0
    mode: str | None = None
    report_sent: str | None = None
    report_received: str | None = None
    tx_power: str | None = None
    comments: str | None = None
    name: str | None = None
    datetime_on: dict | None = None
    operator_call: str | None = None
    my_call: str | None = None
    my_grid: str | None = None
    exchange_sent: str | None = None
    exchange_received: str | None = None
    propagation_mode: str | None = None


@dataclass
class Close(WsjtxMessage):
    pass


@dataclass
class WSPRDecode(WsjtxMessage):
    new: bool = False
    time_ms: int = 0
    snr: int = 0
    delta_time: float = 0.0
    frequency: int = 0
    drift: int = 0
    callsign: str | None = None
    grid: str | None = None
    power_dbm: int = 0
    off_air: bool = False


@dataclass
class LoggedADIF(WsjtxMessage):
    adif: str | None = None


@dataclass
class UnknownMessage(WsjtxMessage):
    payload: bytes = field(default=b"", repr=False)


# --------------------------------------------------------------------------- #
# Message-text interpretation (grid + CQ + DX call)
# --------------------------------------------------------------------------- #

# Directional/qualifier tokens that can follow "CQ" before the actual callsign,
# e.g. "CQ DX K1ABC FN42", "CQ NA K1ABC", "CQ POTA K1ABC".
_CQ_QUALIFIERS = {"DX", "NA", "SA", "EU", "AS", "AF", "OC", "TEST", "POTA", "SOTA", "QRP"}


def extract_grid(message: str | None) -> str | None:
    """Return the 4/6-char Maidenhead grid in a decode message, else None.

    Grid rides in CQ and Tx1 ('CALL CALL GRID') messages as the final token;
    reports/sign-offs ('R-12', 'RRR', 'RR73', '73') carry none. 'RR73' matches
    the grid shape but is always a sign-off, so it is excluded.
    """
    if not message:
        return None
    last = message.split()[-1]
    if last.upper() == "RR73":
        return None
    return last.upper() if _GRID_RE.match(last) else None


def _interpret_decode(message: str | None) -> tuple[bool, str | None, str | None]:
    """Best-effort (is_cq, dx_call, grid) from decode text.

    Full WSJT-X message grammar is richer; this covers CQ and standard exchanges
    well enough for the roster/decision engine and is refined later (§3.5).
    """
    grid = extract_grid(message)
    if not message:
        return False, None, grid
    tokens = message.split()
    if tokens and tokens[0] == "CQ":
        # Skip an optional qualifier (DX / region / contest tag) after CQ.
        idx = 1
        if len(tokens) > 2 and tokens[1].upper() in _CQ_QUALIFIERS:
            idx = 2
        dx_call = tokens[idx] if len(tokens) > idx else None
        return True, dx_call, grid
    # Standard exchange "<to> <from> <report/grid>": the caller of interest (the
    # station transmitting) is the 2nd token.
    dx_call = tokens[1] if len(tokens) >= 2 else None
    return False, dx_call, grid


# --------------------------------------------------------------------------- #
# Top-level parse
# --------------------------------------------------------------------------- #


def parse(data: bytes) -> WsjtxMessage | None:
    """Parse one datagram into a typed event, or None if it is not WSJT-X.

    Tolerates trailing fields added by newer WSJT-X versions (reads only what it
    knows) and never raises on a recognized type with extra/optional data.
    """
    if len(data) < 8:
        return None
    r = _Reader(data)
    if r.u32() != MAGIC:
        return None
    schema = r.u32()
    mtype = r.u32()
    mid = r.utf8()

    if mtype == HEARTBEAT:
        msg = Heartbeat(schema, mtype, mid)
        if not r.at_end():
            msg.max_schema = r.u32()
            msg.version = r.utf8()
            msg.revision = r.utf8()
        return msg

    if mtype == STATUS:
        return Status(
            schema, mtype, mid,
            dial_frequency=r.u64(),
            mode=r.utf8(),
            dx_call=r.utf8(),
            report=r.utf8(),
            tx_mode=r.utf8(),
            tx_enabled=r.boolean(),
            transmitting=r.boolean(),
            decoding=r.boolean(),
            rx_df=r.u32(),
            tx_df=r.u32(),
            de_call=r.utf8(),
            de_grid=r.utf8(),
            dx_grid=r.utf8(),
            tx_watchdog=r.boolean(),
            sub_mode=r.utf8(),
            fast_mode=r.boolean(),
            special_op_mode=r.u8(),
            frequency_tolerance=r.u32_opt(),
            tr_period=r.u32_opt(),
            config_name=r.utf8(),
            tx_message=r.utf8(),
        )

    if mtype == DECODE:
        msg = Decode(
            schema, mtype, mid,
            new=r.boolean(),
            time_ms=r.u32(),
            snr=r.i32(),
            delta_time=r.double(),
            delta_frequency=r.u32(),
            mode=r.utf8(),
            message=r.utf8(),
            low_confidence=r.boolean(),
            off_air=r.boolean() if not r.at_end() else False,
        )
        msg.is_cq, msg.dx_call, msg.grid = _interpret_decode(msg.message)
        return msg

    if mtype == CLEAR:
        return Clear(schema, mtype, mid)

    if mtype == QSO_LOGGED:
        return QSOLogged(
            schema, mtype, mid,
            datetime_off=r.datetime(),
            dx_call=r.utf8(),
            dx_grid=r.utf8(),
            tx_frequency=r.u64(),
            mode=r.utf8(),
            report_sent=r.utf8(),
            report_received=r.utf8(),
            tx_power=r.utf8(),
            comments=r.utf8(),
            name=r.utf8(),
            datetime_on=r.datetime(),
            operator_call=r.utf8(),
            my_call=r.utf8(),
            my_grid=r.utf8(),
            exchange_sent=r.utf8() if not r.at_end() else None,
            exchange_received=r.utf8() if not r.at_end() else None,
            propagation_mode=r.utf8() if not r.at_end() else None,
        )

    if mtype == CLOSE:
        return Close(schema, mtype, mid)

    if mtype == WSPR_DECODE:
        return WSPRDecode(
            schema, mtype, mid,
            new=r.boolean(),
            time_ms=r.u32(),
            snr=r.i32(),
            delta_time=r.double(),
            frequency=r.u64(),
            drift=r.i32(),
            callsign=r.utf8(),
            grid=r.utf8(),
            power_dbm=r.i32(),
            off_air=r.boolean() if not r.at_end() else False,
        )

    if mtype == LOGGED_ADIF:
        return LoggedADIF(schema, mtype, mid, adif=r.utf8())

    return UnknownMessage(schema, mtype, mid)
