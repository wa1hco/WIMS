"""Decode-activity map — UDP-native band-activity view (plan §2.5 / §3.15).

A synthetic "waterfall from decodes": each WSJT-X Decode is plotted by audio
frequency (delta_frequency, ~0-3000 Hz) across the X axis and TX/RX cycle down
the Y axis, with cell intensity from SNR. It is NOT a real spectrogram (WSJT-X
sends no audio), but it confirms at a glance that an instance is hearing the band
and decodes are flowing — confidence without any screen capture or host agent.

Per WSJT-X instance: one ActivityMap. Pure logic + a console renderer; the same
data feeds the dashboard tile later.
"""

from __future__ import annotations

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
    return f"{seconds // 3600 % 24:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


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
        self._rows: dict[int, list[int | None]] = {}

    def bin_of(self, df_hz: int) -> int:
        b = int(df_hz / self.freq_max * self.n_bins)
        return max(0, min(self.n_bins - 1, b))

    def bucket_of(self, time_ms: int) -> int:
        return time_ms // (self.period_s * 1000)

    def add(self, decode) -> None:
        """Record a parsed messages.Decode (uses time_ms, delta_frequency, snr)."""
        bucket = self.bucket_of(decode.time_ms)
        b = self.bin_of(decode.delta_frequency)
        row = self._rows.setdefault(bucket, [None] * self.n_bins)
        if row[b] is None or decode.snr > row[b]:
            row[b] = decode.snr
        self.count += 1

    def recent_rows(self) -> list[tuple[int, list[int | None]]]:
        """The most-recent n_rows cycles as `(bucket, [n_bins] best-SNR-or-None)`,
        oldest first — the data behind `render()`, for the dashboard tile (§2.5)."""
        return [(bk, self._rows[bk]) for bk in sorted(self._rows)[-self.n_rows:]]

    def render(self) -> str:
        """Render the most recent n_rows cycles as a text heatmap."""
        if not self._rows:
            return f"[{self.instance_id}] no decodes yet"
        buckets = sorted(self._rows)[-self.n_rows:]
        out = [f"[{self.instance_id}]  {self.count} decodes  "
               f"(cols 0..{self.freq_max} Hz, rows = {self.period_s}s cycles)"]
        for bk in buckets:
            line = "".join(snr_glyph(s) for s in self._rows[bk])
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
                    print(amap.render())
                    print()
    except KeyboardInterrupt:
        print(f"\nstopped — {sum(m.count for m in maps.values())} decodes, "
              f"{len(maps)} instance(s)")


if __name__ == "__main__":
    _main()
