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

- ``InhibitGate`` is the WSJT-X side (§11.1): two states, per-station TTL
  deadman, no hysteresis, no configuration of who may inhibit.  Written to be
  transplanted into the WSJT-X fork's gate thread, so it must stay free of
  I/O, threads, and wall-clock reads — callers inject monotonic time.
- ``KeyAgentScheduler`` is the SSB/CW Key-agent side (§3): immediate assert on
  key-down, keepalives while holding the band, hang time before ``clear``.
  All the hysteresis lives here, keeping the gate state-free.

Both return/accept encoded datagrams; transport (UDP, loopback, test harness)
is the caller's job.
"""

from __future__ import annotations

import json

PROTOCOL_KEY = "wims_inhibit"
PROTOCOL_VERSION = 1

DEFAULT_GATE_PORT = 22372     # try first; fall back to ephemeral (§11.2)
DEFAULT_TTL_MS = 600          # keyed state expires without keepalive (§4.2)
DEFAULT_KEEPALIVE_S = 0.2     # keyed repeat while holding
DEFAULT_HANG_S = 0.5          # agent-side release hysteresis (§3)

MAX_DATAGRAM_BYTES = 512
_TTL_MS_MIN, _TTL_MS_MAX = 100, 30_000


def encode_datagram(state, station, band, seq, ttl_ms=DEFAULT_TTL_MS):
    """Encode one inhibit datagram (§11.3). state: 'keyed' | 'clear'."""
    if state not in ("keyed", "clear"):
        raise ValueError(f"bad state {state!r}")
    return json.dumps(
        {
            PROTOCOL_KEY: PROTOCOL_VERSION,
            "state": state,
            "ttl_ms": int(ttl_ms),
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
    if msg.get("state") not in ("keyed", "clear"):
        return None
    ttl = msg.get("ttl_ms", DEFAULT_TTL_MS)
    if not isinstance(ttl, int) or not (_TTL_MS_MIN <= ttl <= _TTL_MS_MAX):
        return None
    msg["ttl_ms"] = ttl
    msg["station"] = str(msg.get("station", ""))
    msg["band"] = str(msg.get("band", ""))
    return msg


class InhibitGate:
    """WSJT-X-side gate (§11.1): INHIBIT = any station keyed and unexpired.

    Per-station deadlines implement the §4.3 compose rule (two SSB/CW
    stations may hold the band; a clear from one must not release the
    other's hold).  A station whose deadline passes without a ``clear``
    is dropped and counted as an expiry (keepalive loss — alarm-worthy).
    """

    def __init__(self):
        self._deadlines = {}          # station -> (deadline monotonic s, band)
        self.keyed_rx = 0
        self.clear_rx = 0
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
        station = msg["station"]
        if msg["state"] == "keyed":
            self.keyed_rx += 1
            self._deadlines[station] = (now + msg["ttl_ms"] / 1000.0, msg["band"])
        else:
            self.clear_rx += 1
            self._deadlines.pop(station, None)
        return self.inhibited(now) != before

    # -- output --------------------------------------------------------------

    def inhibited(self, now):
        """True while any station's hold is unexpired. Prunes as it goes."""
        expired = [s for s, (dl, _b) in self._deadlines.items() if now >= dl]
        for station in expired:
            del self._deadlines[station]
            self.expiries += 1
        return bool(self._deadlines)

    def holding_stations(self, now):
        """Stations currently holding the band (for UI badge / telemetry)."""
        self.inhibited(now)
        return sorted(self._deadlines)

    def status(self, now):
        """Telemetry dict for InhibitStatus announcements (§11.4)."""
        return {
            "inhibited": self.inhibited(now),
            "stations": self.holding_stations(now),
            "keyed_rx": self.keyed_rx,
            "clear_rx": self.clear_rx,
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
    """

    def __init__(self, station, band, hang_s=DEFAULT_HANG_S,
                 keepalive_s=DEFAULT_KEEPALIVE_S, ttl_ms=DEFAULT_TTL_MS):
        if ttl_ms / 1000.0 <= 2 * keepalive_s:
            raise ValueError("ttl must comfortably exceed the keepalive period")
        self.station = station
        self.band = band
        self.hang_s = float(hang_s)
        self.keepalive_s = float(keepalive_s)
        self.ttl_ms = int(ttl_ms)
        self.seq = 0
        self._key = False             # physical input as last reported
        self._holding = False         # keyed sent, clear not yet sent
        self._clear_at = None         # when hang expires (key currently up)
        self._next_keepalive = None

    def _emit(self, state):
        self.seq += 1
        return encode_datagram(state, self.station, self.band, self.seq,
                               self.ttl_ms)

    def set_key(self, keyed, now):
        """Report the physical key state. Returns datagrams to send now."""
        keyed = bool(keyed)
        if keyed == self._key:
            return []
        self._key = keyed
        if keyed:
            self._clear_at = None                 # re-key during hang: keep holding
            if not self._holding:
                self._holding = True              # assert is immediate (§3)
                self._next_keepalive = now + self.keepalive_s
                return [self._emit("keyed")]
            return []
        self._clear_at = now + self.hang_s        # key up: start hang window
        return []

    def poll(self, now):
        """Timer tick. Returns datagrams to send now (possibly empty)."""
        if not self._holding:
            return []
        if not self._key and self._clear_at is not None and now >= self._clear_at:
            self._holding = False
            self._clear_at = None
            self._next_keepalive = None
            return [self._emit("clear")]
        if now >= self._next_keepalive:
            self._next_keepalive = now + self.keepalive_s
            return [self._emit("keyed")]
        return []

    @property
    def holding(self):
        return self._holding
