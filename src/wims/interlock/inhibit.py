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

"""TX-inhibit gate and SSB/CW Key-agent logic — pure, I/O-free.

Wire authority: docs/protocols/wsjtx_tx_inhibit.md and sister-repo
wsjtx-inhibit docs/TX_INHIBIT.md. Product context: docs/plan/wims_tx_inhibit.md
(JSON §11.3 examples are historical).

Two sides of one wire protocol:

- ``InhibitGate`` is the WSJT-X side: per-Controller-ID leases OR'd into hold,
  TTL deadman per row, no hysteresis. Written to mirror the station gate, so
  it stays free of I/O, threads, and wall-clock reads — callers inject
  monotonic time.
- ``KeyAgentScheduler`` is the SSB/CW Key-agent side: immediate assert on
  key-down, keepalives while holding, hang time before release
  (``ttl_ms=0``). All hysteresis lives here.

Wire is ``NetworkMessage::TxInhibit`` type **18** (QDataStream schema 3).
Legacy JSON is invalid. Transport (UDP, loopback, test harness) is the
caller's job.
"""

from __future__ import annotations

import struct
from collections import deque

NM_MAGIC = 0xADBCCBDA
NM_SCHEMA = 3
NM_TX_INHIBIT = 18

DEFAULT_GATE_PORT = 22372     # try first; fall back to ephemeral
DEFAULT_TTL_MS = 600          # a lease expires without keepalive (deadman)
DEFAULT_KEEPALIVE_S = 0.2     # hold re-armed at this rate while keyed
LONG_HANG_S = 0.0             # long/SSB: no hang (TX_INHIBIT.md §3.2)

# Adaptive hang (TX_INHIBIT.md §3.4): break-in CW hang = 1.5 × word gap = 10.5 × dit.
ADAPTIVE_DITS = 10.5
ADAPTIVE_HANG_MIN_S = 0.315   # clamp: ~40 WPM floor
ADAPTIVE_HANG_MAX_S = 1.260   # clamp: ~10 WPM ceiling
LONG_CLOSURE_S = 0.75         # at/above: SSB-PTT/VOX/semi-BK (rig pre-hangs)
DIT_MAX_S = 0.2               # a dit at >=6 WPM; longer closures are not dit evidence
CLOSURE_DEBOUNCE_S = 0.02     # omit sub-20 ms glitches from dit estimate only
CLOSURE_WINDOW = 8            # closures kept for the dit estimate

MAX_DATAGRAM_BYTES = 512
_TTL_MS_MIN, _TTL_MS_MAX = 100, 30_000


def adaptive_hang_s(closures):
    """Adaptive hang from recent closure durations (seconds, newest last).

    Returns ``(hang_s, mode)`` with mode ``"cw"`` or ``"long"``.  The latest
    closure picks the mode: at/above ``LONG_CLOSURE_S`` the line is
    SSB-PTT/VOX/semi-break-in-like — hang ``LONG_HANG_S`` (0).  CW mode needs
    evidence of actual elements: a dit-plausible closure (<= ``DIT_MAX_S``)
    in the window; then hang = ``ADAPTIVE_DITS`` × the shortest such closure,
    clamped.  A mid-length closure (0.2–0.75 s) alone is neither and also
    gets hang 0.
    """
    if not closures or closures[-1] >= LONG_CLOSURE_S:
        return LONG_HANG_S, "long"
    dits = [c for c in closures if c <= DIT_MAX_S]
    if not dits:
        return LONG_HANG_S, "long"
    hang = max(ADAPTIVE_HANG_MIN_S, min(ADAPTIVE_HANG_MAX_S,
                                        ADAPTIVE_DITS * min(dits)))
    return hang, "cw"


def _qbytearray(data: bytes) -> bytes:
    """QDataStream QByteArray: quint32 length + bytes (empty length 0)."""
    return struct.pack(">I", len(data)) + data


def encode_tx_inhibit(controller_id: str, ttl_ms: int,
                      station: str = "", target_id: str = "") -> bytes:
    """Build NetworkMessage::TxInhibit (type 18).

    Nonzero ``ttl_ms`` = create/refresh that controller's lease.
    ``ttl_ms == 0`` = release **only** that controller's lease.
    """
    if not controller_id:
        raise ValueError("controller_id must be non-empty")
    ttl_ms = int(ttl_ms)
    if ttl_ms != 0 and not (_TTL_MS_MIN <= ttl_ms <= _TTL_MS_MAX):
        raise ValueError(f"bad ttl_ms {ttl_ms}")
    body = struct.pack(">III", NM_MAGIC, NM_SCHEMA, NM_TX_INHIBIT)
    body += _qbytearray(target_id.encode("utf-8"))
    body += _qbytearray(controller_id.encode("utf-8"))
    body += struct.pack(">I", ttl_ms & 0xFFFFFFFF)
    body += _qbytearray(station.encode("utf-8"))
    if len(body) > MAX_DATAGRAM_BYTES:
        raise ValueError(f"datagram too large ({len(body)} > {MAX_DATAGRAM_BYTES})")
    return body


# Alias kept for older lab call sites / mental model ("one datagram type").
encode_datagram = encode_tx_inhibit


def parse_datagram(data):
    """Validate + decode one type-18 datagram. Returns dict or None (never raises).

    Dict keys: ``target_id``, ``controller_id``, ``ttl_ms``, ``station``.
    JSON and other non-type-18 payloads return None.
    """
    if not data or len(data) > MAX_DATAGRAM_BYTES:
        return None
    try:
        if len(data) < 12:
            return None
        magic, schema, mtype = struct.unpack_from(">III", data, 0)
        if magic != NM_MAGIC or schema != NM_SCHEMA or mtype != NM_TX_INHIBIT:
            return None
        i = 12

        def read_utf8(buf, off):
            if off + 4 > len(buf):
                raise ValueError("short utf8 length")
            n = struct.unpack_from(">I", buf, off)[0]
            off += 4
            if n == 0xFFFFFFFF:  # Qt null QByteArray — treat as empty string
                return "", off
            if off + n > len(buf):
                raise ValueError("short utf8 body")
            return buf[off:off + n].decode("utf-8"), off + n

        target_id, i = read_utf8(data, i)
        controller_id, i = read_utf8(data, i)
        if not controller_id:
            return None
        if i + 4 > len(data):
            return None
        ttl = struct.unpack_from(">I", data, i)[0]
        i += 4
        station, i = read_utf8(data, i)
    except (ValueError, UnicodeDecodeError, struct.error):
        return None
    if ttl != 0 and not (_TTL_MS_MIN <= ttl <= _TTL_MS_MAX):
        return None
    return {
        "target_id": target_id,
        "controller_id": controller_id,
        "ttl_ms": int(ttl),
        "station": station,
    }


class InhibitGate:
    """WSJT-X-side gate: per-controller leases, OR'd into hold.

    Each valid hold upserts that Controller ID's lease to ``now + ttl_ms``.
    A release (``ttl_ms=0``) clears **only** that Controller ID. Hold is
    active while any lease is live. Expired rows are swept on read and
    counted as expiries (keepalive loss — alarm-worthy).
    """

    def __init__(self):
        # controller_id -> (deadline_mono_s, station_badge)
        self._leases: dict[str, tuple[float, str]] = {}
        self.hold_rx = 0
        self.release_rx = 0
        self.expiries = 0
        self.invalid = 0

    def _sweep(self, now):
        dead = [cid for cid, (deadline, _) in self._leases.items()
                if now >= deadline]
        for cid in dead:
            del self._leases[cid]
            self.expiries += 1

    def on_datagram(self, data, now):
        """Feed one raw datagram. Returns True if the gate output changed."""
        msg = parse_datagram(data)
        if msg is None:
            self.invalid += 1
            return False
        before = self.inhibited(now)
        cid = msg["controller_id"]
        if msg["ttl_ms"] == 0:
            self.release_rx += 1
            self._leases.pop(cid, None)
        else:
            self.hold_rx += 1
            self._leases[cid] = (now + msg["ttl_ms"] / 1000.0, msg["station"])
        return self.inhibited(now) != before

    def inhibited(self, now):
        """True while any lease is unexpired. Expiry here is the deadman."""
        self._sweep(now)
        return bool(self._leases)

    def holding_station(self, now):
        """Badge text for live holders, or "" when open.

        Multiple holders are joined with ``, `` in stable controller-id order.
        Prefers each lease's Station field; falls back to controller_id.
        """
        self._sweep(now)
        if not self._leases:
            return ""
        parts = []
        for cid in sorted(self._leases):
            station = self._leases[cid][1]
            parts.append(station or cid)
        return ", ".join(parts)

    def live_controllers(self, now):
        """Sorted list of controller_ids with live leases (for tests/telemetry)."""
        self._sweep(now)
        return sorted(self._leases)

    def status(self, now):
        """Telemetry dict aligned with InhibitStatus counters."""
        return {
            "inhibited": self.inhibited(now),
            "station": self.holding_station(now),
            "controllers": self.live_controllers(now),
            "hold_rx": self.hold_rx,
            "release_rx": self.release_rx,
            "expiries": self.expiries,
            "invalid": self.invalid,
        }


class KeyAgentScheduler:
    """Key-agent-side logic: edges in, type-18 datagrams out, hysteresis here.

    Feed physical key edges via ``set_key`` and call ``poll`` on a timer
    (any period ≤ keepalive_s / 2 is fine); both return a list of encoded
    datagrams to send to every assigned target.  "Holding" spans from the
    first key-down until hang time after the last key-up, so a CW string
    is one continuous hold — the gate never sees the gaps between dits.

    Hang time is **adaptive by default** (``hang_s=None``): each key-up
    picks its hang via ``adaptive_hang_s``.  Passing a numeric ``hang_s``
    is a manual override.  ``controller_id`` is required (lease key on the
    wire).  ``station`` is badge text; ``band`` / ``target_id`` are off-wire
    routing metadata (``target_id`` may be placed in the type-18 Id field).
    """

    def __init__(self, controller_id, station="", *, band=None, hang_s=None,
                 keepalive_s=DEFAULT_KEEPALIVE_S, ttl_ms=DEFAULT_TTL_MS,
                 target_id=""):
        if not controller_id:
            raise ValueError("controller_id must be non-empty")
        if ttl_ms / 1000.0 <= 2 * keepalive_s:
            raise ValueError("ttl must comfortably exceed the keepalive period")
        self.controller_id = str(controller_id)
        self.station = str(station) if station else self.controller_id
        self.band = band  # off-wire only (WIMS routing / logs)
        self.target_id = str(target_id or "")
        self.hang_override = None if hang_s is None else float(hang_s)
        self.keepalive_s = float(keepalive_s)
        self.ttl_ms = int(ttl_ms)
        self.emit_count = 0
        self.last_hang_s = self.hang_override
        self.hang_mode = "manual" if self.hang_override is not None else None
        self._closures = deque(maxlen=CLOSURE_WINDOW)
        self._down_at = None
        self._key = False
        self._holding = False
        self._release_at = None
        self._next_keepalive = None

    def _emit(self, ttl_ms):
        self.emit_count += 1
        return encode_tx_inhibit(
            self.controller_id, ttl_ms,
            station=self.station, target_id=self.target_id,
        )

    def set_key(self, keyed, now):
        """Report the physical key state. Returns datagrams to send now."""
        keyed = bool(keyed)
        if keyed == self._key:
            return []
        self._key = keyed
        if keyed:
            self._down_at = now
            self._release_at = None
            if not self._holding:
                self._holding = True
                self._next_keepalive = now + self.keepalive_s
                return [self._emit(self.ttl_ms)]
            return []
        if self._down_at is not None:
            closure = now - self._down_at
            self._down_at = None
            if closure >= CLOSURE_DEBOUNCE_S:
                self._closures.append(closure)
        if self.hang_override is not None:
            self.last_hang_s, self.hang_mode = self.hang_override, "manual"
        else:
            self.last_hang_s, self.hang_mode = adaptive_hang_s(self._closures)
        self._release_at = now + self.last_hang_s
        return []

    def poll(self, now):
        """Timer tick. Returns datagrams to send now (possibly empty)."""
        if not self._holding:
            return []
        if not self._key and self._release_at is not None and now >= self._release_at:
            self._holding = False
            self._release_at = None
            self._next_keepalive = None
            return [self._emit(0)]
        if now >= self._next_keepalive:
            self._next_keepalive = now + self.keepalive_s
            return [self._emit(self.ttl_ms)]
        return []

    @property
    def holding(self):
        return self._holding

    def force_release(self, now):
        """Emit release immediately if holding (band change / shutdown).

        Clears hang bookkeeping. If the key is still down, caller should
        ``set_key(True, …)`` again afterward to re-assert.
        """
        if not self._holding:
            self._release_at = None
            return []
        self._holding = False
        self._release_at = None
        self._next_keepalive = None
        return [self._emit(0)]
