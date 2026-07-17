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

"""Decode-activity map — UDP-native band-activity view (plan §2.5 / §3.15).

A synthetic "waterfall from decodes": each WSJT-X Decode is plotted by audio
frequency (delta_frequency, ~0-3000 Hz) across the X axis and TX/RX cycle down
the Y axis, with cell intensity from SNR. It is NOT a real spectrogram (WSJT-X
sends no audio), but it confirms at a glance that an instance is hearing the band
and decodes are flowing — confidence without any screen capture or host agent.

Like the WSJT-X waterfall, the view **scrolls on the clock**: empty 15 s cycles
appear as blank rows even when no Decode UDP arrived. Only SNR cells require
messages.

Per WSJT-X instance: one ActivityMap. Pure logic + a console renderer; the same
data feeds the dashboard tile later.
"""

from __future__ import annotations

from datetime import datetime, timezone

# SNR -> glyph, weakest to strongest. Tuned for FT8 (~ -24..+25 dB).
_LEVELS = [(-21, "."), (-16, ":"), (-11, "-"), (-6, "="), (-1, "+"),
           (4, "*"), (9, "#"), (999, "@")]


def snr_glyph(snr: int | None) -> str:
    if snr is None:
        return " "
    for thr, ch in _LEVELS:
        if snr <= thr:
            return ch
    return "@"


def _hms(seconds: int) -> str:
    s = seconds % 86400
    return f"{s // 3600 % 24:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def utc_ms_since_midnight(now: float) -> int:
    """Wall-clock UTC milliseconds since midnight — same epoch WSJT-X uses for Decode.time_ms."""
    t = datetime.fromtimestamp(now, tz=timezone.utc)
    return ((t.hour * 3600 + t.minute * 60 + t.second) * 1000
            + t.microsecond // 1000)


class ActivityMap:
    def __init__(self, instance_id: str, period_s: int = 15,
                 freq_max: int = 3000, n_bins: int = 50, n_rows: int = 15):
        self.instance_id = instance_id
        self.period_s = period_s
        self.freq_max = freq_max
        self.n_bins = n_bins
        self.n_rows = n_rows
        self.count = 0
        # bucket index (time_ms // period_ms) -> [n_bins] best SNR seen, or None.
        # Bucket is period-of-day (0 .. periods_per_day-1), matching WSJT-X time_ms.
        self._rows: dict[int, list[int | None]] = {}

    @property
    def periods_per_day(self) -> int:
        return max(1, (24 * 3600) // self.period_s)

    def bin_of(self, df_hz: int) -> int:
        b = int(df_hz / self.freq_max * self.n_bins)
        return max(0, min(self.n_bins - 1, b))

    def bucket_of(self, time_ms: int) -> int:
        return time_ms // (self.period_s * 1000)

    def period_index_now(self, now: float) -> int:
        """Current FT8/MSK period index from wall clock (UTC)."""
        return self.bucket_of(utc_ms_since_midnight(now)) % self.periods_per_day

    def add(self, decode) -> None:
        """Record a parsed messages.Decode (uses time_ms, delta_frequency, snr)."""
        bucket = self.bucket_of(decode.time_ms) % self.periods_per_day
        b = self.bin_of(decode.delta_frequency)
        row = self._rows.setdefault(bucket, [None] * self.n_bins)
        if row[b] is None or decode.snr > row[b]:
            row[b] = decode.snr
        self.count += 1

    def recent_rows(self, now: float | None = None
                    ) -> list[tuple[int, list[int | None]]]:
        """Most recent `n_rows` cycles, oldest first.

        When `now` is given (dashboard path), the window ends at the **current**
        wall-clock period and includes empty cycles — continuous scroll like
        WSJT-X, not only rows that received a Decode.
        When `now` is omitted, only stored (non-empty) buckets are returned
        (legacy / offline analysis).
        """
        empty = [None] * self.n_bins
        if now is None:
            return [(bk, list(self._rows[bk]))
                    for bk in sorted(self._rows)[-self.n_rows:]]

        end = self.period_index_now(now)
        day = self.periods_per_day
        out: list[tuple[int, list[int | None]]] = []
        for i in range(self.n_rows - 1, -1, -1):
            bk = (end - i) % day
            row = self._rows.get(bk)
            out.append((bk, list(row) if row is not None else list(empty)))
        # Drop buckets that scrolled off the visible window (keep a little margin).
        keep = {bk for bk, _ in out}
        for old in list(self._rows.keys()):
            if old not in keep:
                # Keep a short history beyond the window for late UDP.
                # Distance on circular day clock:
                dist = (end - old) % day
                if dist > self.n_rows + 4:
                    del self._rows[old]
        return out

    def render(self, now: float | None = None) -> str:
        """Render the most recent n_rows cycles as a text heatmap."""
        rows = self.recent_rows(now)
        if not rows:
            return f"[{self.instance_id}] no cycles yet"
        out = [f"[{self.instance_id}]  {self.count} decodes  "
               f"(cols 0..{self.freq_max} Hz, rows = {self.period_s}s cycles)"]
        for bk, snrs in rows:
            line = "".join(snr_glyph(s) for s in snrs)
            out.append(f"  {_hms(bk * self.period_s)} |{line}|")
        # Frequency axis ruler.
        ruler = [" "] * self.n_bins
        for hz in range(0, self.freq_max + 1, 500):
            ruler[min(self.n_bins - 1, self.bin_of(hz))] = "^"
        out.append(f"  {'':8} |{''.join(ruler)}|  ^=500Hz steps")
        return "\n".join(out)


# --------------------------------------------------------------------------- #
# Live driver: join the multicast and redraw per instance.
# --------------------------------------------------------------------------- #

def _main() -> None:
    import argparse
    import sys
    import time
    from pathlib import Path

    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from wims.udp import messages as M
    from wims.udp.sink import open_socket

    ap = argparse.ArgumentParser(description="Live decode-activity map per WSJT-X instance.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=2237)
    ap.add_argument("--multicast", default=None)
    ap.add_argument("--refresh", type=float, default=2.0, help="seconds between redraws")
    args = ap.parse_args()

    sock = open_socket(args.host, args.port, args.multicast)
    maps: dict[str, ActivityMap] = {}
    last = 0.0
    print("WIMS activity map — Ctrl-C to stop\n")
    try:
        while True:
            data, _ = sock.recvfrom(65535)
            msg = M.parse(data)
            if isinstance(msg, M.Decode):
                mid = msg.id or "?"
                maps.setdefault(mid, ActivityMap(mid)).add(msg)
            now = time.time()
            if now - last >= args.refresh and maps:
                last = now
                print("\033[2J\033[H", end="")  # clear screen
                for amap in maps.values():
                    print(amap.render(now=now))
                    print()
    except KeyboardInterrupt:
        print(f"\nstopped — {sum(m.count for m in maps.values())} decodes, "
              f"{len(maps)} instance(s)")


if __name__ == "__main__":
    _main()
