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

Design: docs/plan/wims_tx_inhibit.md §3, §4.4, §11 (spike step §11.6.1).

Two sides of one wire protocol:

- ``InhibitGate`` is the WSJT-X side (§11.1): two states, one hold, one TTL
  deadman, no hysteresis, no configuration of who may inhibit.  Written to be
  transplanted into the WSJT-X fork's gate thread, so it must stay free of
  I/O, threads, and wall-clock reads — callers inject monotonic time.
- ``KeyAgentScheduler`` is the SSB/CW Key-agent side (§3): immediate assert on
  key-down, keepalives while holding the band, hang time before the release
  (a datagram with ``ttl_ms=0`` — the protocol's only message type is
  "inhibit for ttl_ms").  All the hysteresis lives here, keeping the gate
  state-free.

Both return/accept encoded datagrams; transport (UDP, loopback, test harness)
is the caller's job.
"""

from __future__ import annotations

import json
from collections import deque

PROTOCOL_KEY = "tx_inhibit"
PROTOCOL_VERSION = 1

DEFAULT_GATE_PORT = 22372     # try first; fall back to ephemeral (§11.2)
DEFAULT_TTL_MS = 600          # a hold expires without keepalive (§4.2 deadman)
DEFAULT_KEEPALIVE_S = 0.2     # hold re-armed at this rate while keyed
LONG_HANG_S = 0.0             # long/SSB: no hang, no software PTT debounce (§3, 2026-08-16)

# Adaptive hang (§3): the line self-classifies from closure statistics.
ADAPTIVE_DITS = 8             # CW hang = 8 x measured dit-time
ADAPTIVE_HANG_MIN_S = 0.2     # clamp: ~60 WPM floor
ADAPTIVE_HANG_MAX_S = 1.0     # clamp: ~10 WPM ceiling
LONG_CLOSURE_S = 0.75         # at/above: SSB-PTT/VOX/semi-BK (rig pre-hangs)
DIT_MAX_S = 0.2               # a dit at >=6 WPM; longer closures are not dit evidence
CLOSURE_DEBOUNCE_S = 0.02     # omit sub-20 ms glitches from dit estimate only (not PTT hang)
CLOSURE_WINDOW = 8            # closures kept for the dit estimate

MAX_DATAGRAM_BYTES = 512
_TTL_MS_MIN, _TTL_MS_MAX = 100, 30_000


def adaptive_hang_s(closures):
    """§3 adaptive hang from recent closure durations (seconds, newest last).

    Returns ``(hang_s, mode)`` with mode ``"cw"`` or ``"long"``.  The latest
    closure picks the mode: at/above ``LONG_CLOSURE_S`` the line is
    SSB-PTT/VOX/semi-break-in-like — no CW elements to bridge, so hang
    is ``LONG_HANG_S`` (0: no software PTT debounce; manual switches
    already debounce).  Hang exists only to keep the WSJT-X radio's PTT
    from following break-in dits.  CW mode needs **evidence of actual
    elements**: a dit-plausible closure (<= ``DIT_MAX_S``) in the
    window; then hang = ``ADAPTIVE_DITS`` x the shortest such closure,
    clamped.  A mid-length closure (0.2-0.75 s) alone is neither — not
    a dit, not a rig-hung over — and also gets hang 0 (keyboard-bench
    2026-08-02: a ~0.4 s press otherwise reads as a "3 WPM dit").
    """
    if not closures or closures[-1] >= LONG_CLOSURE_S:
        return LONG_HANG_S, "long"
    dits = [c for c in closures if c <= DIT_MAX_S]
    if not dits:
        return LONG_HANG_S, "long"    # no CW elements in evidence
    hang = max(ADAPTIVE_HANG_MIN_S, min(ADAPTIVE_HANG_MAX_S,
                                        ADAPTIVE_DITS * min(dits)))
    return hang, "cw"


def encode_datagram(station, band, seq, ttl_ms=DEFAULT_TTL_MS):
    """Encode one inhibit datagram (§11.3).

    One message type only: "inhibit this band for ``ttl_ms``".  A fresh
    hold or keepalive carries a real TTL; **release is ``ttl_ms=0``** —
    the same message meaning "inhibit for zero more milliseconds"
    (decision 2026-08-02: eliminates the clear code path in WSJT-X).
    """
    ttl_ms = int(ttl_ms)
    if ttl_ms != 0 and not (_TTL_MS_MIN <= ttl_ms <= _TTL_MS_MAX):
        raise ValueError(f"bad ttl_ms {ttl_ms}")
    return json.dumps(
        {
            PROTOCOL_KEY: PROTOCOL_VERSION,
            "ttl_ms": ttl_ms,
            "station": str(station),
            "band": str(band),
            "seq": int(seq),
        },
        separators=(",", ":"),
    ).encode("utf-8")


def parse_datagram(data):
    """Validate + decode one datagram. Returns dict or None (never raises)."""
    if not data or len(data) > MAX_DATAGRAM_BYTES:
        return None
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get(PROTOCOL_KEY) != PROTOCOL_VERSION:
        return None
    ttl = msg.get("ttl_ms")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or (
            ttl != 0 and not (_TTL_MS_MIN <= ttl <= _TTL_MS_MAX)):
        return None
    msg["station"] = str(msg.get("station", ""))
    msg["band"] = str(msg.get("band", ""))
    return msg


class InhibitGate:
    """WSJT-X-side gate (§11.1): one inhibit source, one deadline.

    The gate deliberately tracks **one hold** (decision 2026-08-02): every
    valid hold re-arms the single deadline to ``now + ttl_ms`` and names
    the holder (last datagram wins); a release (``ttl_ms=0``) drops the
    hold at receipt, whoever sent it.  Arbitration among multiple SSB/CW
    stations, if a site ever needs it, belongs on the SSB/CW side (e.g.
    OR-ing KEY lines in hardware) — outside the WSJT-X thread's scope.
    A *nonzero* deadline that lapses without refresh is counted as an
    expiry (keepalive loss — alarm-worthy); a release never looks like an
    expiry because it clears the deadline at receipt.
    """

    def __init__(self):
        self._deadline = None         # monotonic s; None = no hold
        self._holder = ""             # station named by the current hold
        self.hold_rx = 0             # datagrams with ttl > 0
        self.release_rx = 0           # datagrams with ttl == 0
        self.expiries = 0
        self.invalid = 0

    # -- input ---------------------------------------------------------------

    def on_datagram(self, data, now):
        """Feed one raw datagram. Returns True if the gate output changed."""
        msg = parse_datagram(data)
        if msg is None:
            self.invalid += 1
            return False
        before = self.inhibited(now)
        if msg["ttl_ms"] == 0:
            self.release_rx += 1
            self._deadline = None
        else:
            self.hold_rx += 1
            self._deadline = now + msg["ttl_ms"] / 1000.0
            self._holder = msg["station"]
        return self.inhibited(now) != before

    # -- output --------------------------------------------------------------

    def inhibited(self, now):
        """True while the hold is unexpired. Expiry here is the deadman."""
        if self._deadline is not None and now >= self._deadline:
            self._deadline = None
            self.expiries += 1
        return self._deadline is not None

    def holding_station(self, now):
        """Station holding the band, or "" (for UI badge / telemetry)."""
        return self._holder if self.inhibited(now) else ""

    def status(self, now):
        """Telemetry dict for InhibitStatus announcements (§11.4)."""
        return {
            "inhibited": self.inhibited(now),
            "station": self.holding_station(now),
            "hold_rx": self.hold_rx,
            "release_rx": self.release_rx,
            "expiries": self.expiries,
            "invalid": self.invalid,
        }


class KeyAgentScheduler:
    """Key-agent-side logic (§3): edges in, datagrams out, hysteresis here.

    Feed physical key edges via ``set_key`` and call ``poll`` on a timer
    (any period ≤ keepalive_s / 2 is fine); both return a list of encoded
    datagrams to send to every assigned target.  "Holding" spans from the
    first key-down until hang time after the last key-up, so a CW string
    is one continuous hold — the gate never sees the gaps between dits.

    Hang time is **adaptive by default** (``hang_s=None``): each key-up
    picks its hang via ``adaptive_hang_s`` over the recent closure history,
    so a 30 WPM QSK op releases the band in ~0.32 s while an SSB-PTT/VOX
    line releases immediately (hang 0).  Agents do not debounce PTT —
    the sense path is built for manual switches that already debounce.
    No mode input, no knob (§3).  Passing a numeric ``hang_s`` is the
    manual override for pathological cases; the classifier is then
    off.  The chosen value and mode are exposed as ``last_hang_s`` /
    ``hang_mode`` (``"cw"`` | ``"long"`` | ``"manual"``) for telemetry.
    """

    def __init__(self, station, band, hang_s=None,
                 keepalive_s=DEFAULT_KEEPALIVE_S, ttl_ms=DEFAULT_TTL_MS):
        if ttl_ms / 1000.0 <= 2 * keepalive_s:
            raise ValueError("ttl must comfortably exceed the keepalive period")
        self.station = station
        self.band = band
        self.hang_override = None if hang_s is None else float(hang_s)
        self.keepalive_s = float(keepalive_s)
        self.ttl_ms = int(ttl_ms)
        self.seq = 0
        self.last_hang_s = self.hang_override
        self.hang_mode = "manual" if self.hang_override is not None else None
        self._closures = deque(maxlen=CLOSURE_WINDOW)
        self._down_at = None          # when the current closure began
        self._key = False             # physical input as last reported
        self._holding = False         # hold sent, release (ttl 0) not yet
        self._release_at = None       # when hang expires (key currently up)
        self._next_keepalive = None

    def _emit(self, ttl_ms):
        self.seq += 1
        return encode_datagram(self.station, self.band, self.seq, ttl_ms)

    def set_key(self, keyed, now):
        """Report the physical key state. Returns datagrams to send now."""
        keyed = bool(keyed)
        if keyed == self._key:
            return []
        self._key = keyed
        if keyed:
            self._down_at = now
            self._release_at = None                 # re-key during hang: keep holding
            if not self._holding:
                self._holding = True              # assert is immediate (§3)
                self._next_keepalive = now + self.keepalive_s
                return [self._emit(self.ttl_ms)]
            return []
        if self._down_at is not None:             # key up: record the closure...
            closure = now - self._down_at
            self._down_at = None
            if closure >= CLOSURE_DEBOUNCE_S:     # ...unless it was bounce
                self._closures.append(closure)
        if self.hang_override is not None:
            self.last_hang_s, self.hang_mode = self.hang_override, "manual"
        else:
            self.last_hang_s, self.hang_mode = adaptive_hang_s(self._closures)
        self._release_at = now + self.last_hang_s   # ...then start the hang window
        return []

    def poll(self, now):
        """Timer tick. Returns datagrams to send now (possibly empty)."""
        if not self._holding:
            return []
        if not self._key and self._release_at is not None and now >= self._release_at:
            self._holding = False
            self._release_at = None
            self._next_keepalive = None
            return [self._emit(0)]      # release: hold for 0 more ms
        if now >= self._next_keepalive:
            self._next_keepalive = now + self.keepalive_s
            return [self._emit(self.ttl_ms)]
        return []

    @property
    def holding(self):
        return self._holding
