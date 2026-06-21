"""Build WSJT-X UDP datagrams — the inverse of `messages.parse` (plan §3.2 / §5.1).

Used by the WSJT-X emulator (§5.1) to emit Heartbeat/Status/Decode, and by the
UDP controller (§3.2) to send Reply / Halt Tx. Same big-endian QDataStream layout
as `NetworkMessage.hpp`; `messages.parse(build_x(...))` round-trips.
"""

from __future__ import annotations

import struct

from wims.udp.messages import (
    MAGIC, HEARTBEAT, STATUS, DECODE, REPLY, HALT_TX, QUINT32_MAX,
)


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
