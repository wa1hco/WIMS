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

"""Build WSJT-X UDP datagrams — the inverse of `messages.parse` (plan §3.2 / §5.1).

Used by the WSJT-X emulator (§5.1) to emit Heartbeat/Status/Decode, and by the
UDP controller (§3.2) to send Reply / Halt Tx. Same big-endian QDataStream layout
as `NetworkMessage.hpp`; `messages.parse(build_x(...))` round-trips.
"""

from __future__ import annotations

import struct
from datetime import date, datetime, timezone

from wims.udp.messages import (
    MAGIC, HEARTBEAT, STATUS, DECODE, REPLY, HALT_TX, CONFIGURE,
    QSO_LOGGED, LOGGED_ADIF, INHIBIT_STATUS, QUINT32_MAX,
)

# Qt QDate Julian day for 1970-01-01 (UTC civil date).
_JULIAN_UNIX_EPOCH = 2440588


def _qt_datetime_utc(dt: datetime | None = None) -> tuple[int, int, int]:
    """Return (julian_day, msecs_since_midnight, timespec) for a UTC QDateTime.

    timespec 1 = Qt::UTC (no offset field). Matches ``messages._Reader.datetime``.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    julian = _JULIAN_UNIX_EPOCH + (dt.date() - date(1970, 1, 1)).days
    msecs = ((dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000
             + dt.microsecond // 1000)
    return julian, msecs, 1


class _Writer:
    def __init__(self, schema: int, mtype: int, mid: str | None):
        self.buf = bytearray()
        self.u32(MAGIC)
        self.u32(schema)
        self.u32(mtype)
        self.utf8(mid)

    def u8(self, v: int) -> None:
        self.buf += struct.pack(">B", v & 0xFF)

    def boolean(self, v: bool) -> None:
        self.buf += struct.pack(">B", 1 if v else 0)

    def u16(self, v: int) -> None:
        self.buf += struct.pack(">H", v & 0xFFFF)

    def u32(self, v: int) -> None:
        self.buf += struct.pack(">I", v & 0xFFFFFFFF)

    def i32(self, v: int) -> None:
        self.buf += struct.pack(">i", v)

    def u64(self, v: int) -> None:
        self.buf += struct.pack(">Q", v)

    def double(self, v: float) -> None:
        self.buf += struct.pack(">d", v)

    def u32_opt(self, v: int | None) -> None:
        self.u32(QUINT32_MAX if v is None else v)

    def utf8(self, s: str | None) -> None:
        if s is None:
            self.u32(QUINT32_MAX)            # null
        else:
            b = s.encode("utf-8")
            self.u32(len(b))
            self.buf += b

    def datetime_utc(self, dt: datetime | None = None) -> None:
        """Write a non-null QDateTime in UTC (timespec=1)."""
        julian, msecs, timespec = _qt_datetime_utc(dt)
        self.buf += struct.pack(">q", julian)
        self.u32(msecs)
        self.u8(timespec)

    def datetime_null(self) -> None:
        """Write a null QDateTime (julian day 0)."""
        self.buf += struct.pack(">q", 0)
        self.u32(0)
        self.u8(0)

    def bytes(self) -> bytes:
        return bytes(self.buf)


def build_heartbeat(mid: str, max_schema: int = 3, version: str = "2.7.0",
                    revision: str = "", schema: int = 2) -> bytes:
    w = _Writer(schema, HEARTBEAT, mid)
    w.u32(max_schema)
    w.utf8(version)
    w.utf8(revision)
    return w.bytes()


def build_status(mid: str, dial_frequency: int, *, mode: str = "FT8", dx_call: str = "",
                 report: str = "", tx_mode: str = "FT8", tx_enabled: bool = False,
                 transmitting: bool = False, decoding: bool = False, rx_df: int = 1500,
                 tx_df: int = 1500, de_call: str = "", de_grid: str = "", dx_grid: str = "",
                 tx_watchdog: bool = False, sub_mode: str | None = None, fast_mode: bool = False,
                 special_op_mode: int = 0, frequency_tolerance: int | None = None,
                 tr_period: int | None = None, config_name: str = "Default",
                 tx_message: str | None = None, schema: int = 2) -> bytes:
    w = _Writer(schema, STATUS, mid)
    w.u64(dial_frequency)
    w.utf8(mode); w.utf8(dx_call); w.utf8(report); w.utf8(tx_mode)
    w.boolean(tx_enabled); w.boolean(transmitting); w.boolean(decoding)
    w.u32(rx_df); w.u32(tx_df)
    w.utf8(de_call); w.utf8(de_grid); w.utf8(dx_grid)
    w.boolean(tx_watchdog); w.utf8(sub_mode); w.boolean(fast_mode); w.u8(special_op_mode)
    w.u32_opt(frequency_tolerance); w.u32_opt(tr_period)
    w.utf8(config_name); w.utf8(tx_message)
    return w.bytes()


def build_decode(mid: str, *, time_ms: int, snr: int, delta_time: float,
                 delta_frequency: int, message: str, mode: str = "~", new: bool = True,
                 low_confidence: bool = False, off_air: bool = False, schema: int = 2) -> bytes:
    w = _Writer(schema, DECODE, mid)
    w.boolean(new); w.u32(time_ms); w.i32(snr); w.double(delta_time); w.u32(delta_frequency)
    w.utf8(mode); w.utf8(message); w.boolean(low_confidence); w.boolean(off_air)
    return w.bytes()


def build_reply(mid: str, *, time_ms: int, snr: int, delta_time: float, delta_frequency: int,
                message: str, mode: str = "~", low_confidence: bool = False,
                modifiers: int = 0, schema: int = 2) -> bytes:
    """Reply (msg 4): ask a WSJT-X instance to start a QSO with a prior decode.

    Fields per NetworkMessage.hpp: Time, snr, dt, df, mode, message, low_confidence,
    modifiers (no 'New' field — that's Decode-only).
    """
    w = _Writer(schema, REPLY, mid)
    w.u32(time_ms); w.i32(snr); w.double(delta_time); w.u32(delta_frequency)
    w.utf8(mode); w.utf8(message); w.boolean(low_confidence); w.u8(modifiers)
    return w.bytes()


def build_halt_tx(mid: str, *, auto_only: bool = False, schema: int = 2) -> bytes:
    """Halt Tx (msg 8): stop transmitting (immediately, or just unset Auto)."""
    w = _Writer(schema, HALT_TX, mid)
    w.boolean(auto_only)
    return w.bytes()


def build_configure(mid: str, *, mode: str = "", frequency_tolerance: int | None = None,
                    submode: str = "", fast_mode: bool = False,
                    tr_period: int | None = None, rx_df: int | None = None,
                    dx_call: str = "", dx_grid: str = "",
                    generate_messages: bool = True, schema: int = 2) -> bytes:
    """Configure (msg 15): set DX call/grid / Rx DF / generate standard messages.

    Empty utf8 fields = no change; ``None`` for quint32 opts = QUINT32_MAX (no change).
    Does **not** Enable Tx — use Reply for that (CQ/73 or Hold Tx Freq).
    """
    w = _Writer(schema, CONFIGURE, mid)
    w.utf8(mode)
    w.u32_opt(frequency_tolerance)
    w.utf8(submode)
    w.boolean(fast_mode)
    w.u32_opt(tr_period)
    w.u32_opt(rx_df)
    w.utf8(dx_call)
    # GT2 uses a single space when grid unknown so the field is non-empty.
    w.utf8(dx_grid if dx_grid else " ")
    w.boolean(generate_messages)
    return w.bytes()


def build_qso_logged(
    mid: str, *,
    dx_call: str,
    tx_frequency: int,
    mode: str = "FT8",
    dx_grid: str = "",
    report_sent: str = "-10",
    report_received: str = "-12",
    tx_power: str = "",
    comments: str = "",
    name: str = "",
    operator_call: str = "",
    my_call: str = "W1AW",
    my_grid: str = "FN31",
    exchange_sent: str = "",
    exchange_received: str = "",
    propagation_mode: str = "",
    datetime_off: datetime | None = None,
    datetime_on: datetime | None = None,
    schema: int = 2,
) -> bytes:
    """QSO Logged (msg 5): the datagram N1MM's WSJT UDP reader consumes to log."""
    w = _Writer(schema, QSO_LOGGED, mid)
    when = datetime_off or datetime_on or datetime.now(timezone.utc)
    w.datetime_utc(when)          # datetime_off
    w.utf8(dx_call)
    w.utf8(dx_grid or None)
    w.u64(int(tx_frequency))
    w.utf8(mode)
    w.utf8(report_sent)
    w.utf8(report_received)
    w.utf8(tx_power)
    w.utf8(comments)
    w.utf8(name)
    w.datetime_utc(datetime_on or when)
    w.utf8(operator_call or my_call)
    w.utf8(my_call)
    w.utf8(my_grid)
    w.utf8(exchange_sent)
    w.utf8(exchange_received)
    w.utf8(propagation_mode)
    return w.bytes()


def build_logged_adif(mid: str, adif: str, *, schema: int = 2) -> bytes:
    """Logged ADIF (msg 12): ADIF payload (Secondary UDP / some bridges use this)."""
    w = _Writer(schema, LOGGED_ADIF, mid)
    text = (adif or "").strip()
    if text and "<eor>" not in text.lower():
        text += " <eor>"
    w.utf8(text)
    return w.bytes()


def build_inhibit_status(
    mid: str,
    inhibit_port: int,
    *,
    inhibited: bool = False,
    source_station: str = "",
    hold_rx: int = 0,
    release_rx: int = 0,
    expiries: int = 0,
    invalid: int = 0,
    schema: int = 3,
) -> bytes:
    """InhibitStatus (msg 17): digi seat announce inhibit listen port + counters."""
    w = _Writer(schema, INHIBIT_STATUS, mid)
    w.u16(int(inhibit_port))
    w.boolean(inhibited)
    w.utf8(source_station)
    w.u32(hold_rx)
    w.u32(release_rx)
    w.u32(expiries)
    w.u32(invalid)
    return w.bytes()
