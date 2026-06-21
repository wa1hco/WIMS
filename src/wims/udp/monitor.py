"""Live read-only console view of WSJT-X instances (plan §2 / M1 read-only).

Joins the WSJT-X multicast group, parses every datagram with the §3.1 parser, and
prints a per-instance live view: decodes (grid highlighted), status changes, QSO
logs, and instance liveness. Receive-only — never transmits, never disturbs the
running WSJT-X -> GridTracker -> N1MM chain.

Run (from the repo root):
    python src/wims/udp/monitor.py --port 2237 --multicast 224.0.0.73

This is the read-only slice of milestone M1: watch instances, no control.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running directly as a script (python src/wims/udp/monitor.py) without install.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wims.core.bands import band_label as band_of  # noqa: E402
from wims.udp import messages as M  # noqa: E402
from wims.udp.sink import open_socket  # noqa: E402


def hms(msecs_since_midnight: int) -> str:
    s = msecs_since_midnight // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# Status fields whose change is worth printing (the rest are noise at decode rate).
_WATCHED = ("dial_frequency", "mode", "sub_mode", "tx_enabled", "transmitting",
            "decoding", "dx_call", "tx_message", "config_name")


class Monitor:
    def __init__(self) -> None:
        # id -> {"status": dict of last watched fields, "version": str, "last": ts}
        self._instances: dict[str, dict] = {}

    def _inst(self, mid: str | None) -> dict:
        key = mid or "?"
        return self._instances.setdefault(key, {"status": {}, "version": None, "last": 0.0})

    def handle(self, msg: M.WsjtxMessage, now: float) -> None:
        mid = msg.id or "?"
        inst = self._inst(mid)
        inst["last"] = now

        if isinstance(msg, M.Heartbeat):
            if inst["version"] is None and msg.version:
                inst["version"] = msg.version
                print(f"  * {mid} up (WSJT-X {msg.version}, schema {msg.max_schema})")

        elif isinstance(msg, M.Status):
            new = {f: getattr(msg, f) for f in _WATCHED}
            old = inst["status"]
            changed = {k: v for k, v in new.items() if old.get(k) != v}
            inst["status"] = new
            if not old:
                self._print_baseline(mid, msg)  # show band/mode the moment we see it
            elif set(changed) - {"decoding"}:
                # 'decoding' toggles every cycle and would flood the view.
                self._print_status_change(mid, msg, changed)

        elif isinstance(msg, M.Decode):
            self._print_decode(mid, msg)

        elif isinstance(msg, M.QSOLogged):
            print(f"  OK LOGGED [{mid}] {msg.dx_call} {msg.dx_grid or ''} "
                  f"{msg.mode} {msg.report_sent}/{msg.report_received}")

        elif isinstance(msg, M.Clear):
            print(f"  * {mid} band-activity cleared")

        elif isinstance(msg, M.Close):
            print(f"  * {mid} closed")

    def _print_baseline(self, mid: str, s: M.Status) -> None:
        band = band_of(s.dial_frequency)
        state = "TX" if s.transmitting else ("DEC" if s.decoding else "RX")
        mode = f"{s.mode}{('/' + s.sub_mode) if s.sub_mode else ''}"
        dx = f"  DX={s.dx_call} {s.dx_grid or ''}".rstrip() if s.dx_call else ""
        txen = " TxEn" if s.tx_enabled else ""
        print(f"  [{mid:<10}] {band:<5} {s.dial_frequency / 1e6:.6f} MHz  "
              f"mode={mode}  {state}{txen}{dx}")

    def _print_status_change(self, mid: str, s: M.Status, changed: dict) -> None:
        band = band_of(s.dial_frequency)
        state = "TX" if s.transmitting else ("DEC" if s.decoding else "RX ")
        tx = " TxEn" if s.tx_enabled else ""
        bits = []
        if "dial_frequency" in changed:
            bits.append(f"{s.dial_frequency / 1e6:.6f} ({band})")
        if "mode" in changed or "sub_mode" in changed:
            bits.append(f"mode={s.mode}{('/' + s.sub_mode) if s.sub_mode else ''}")
        if "transmitting" in changed or "tx_enabled" in changed or "decoding" in changed:
            bits.append(state.strip() + tx)
        if "dx_call" in changed and s.dx_call:
            bits.append(f"DX={s.dx_call} {s.dx_grid or ''}".strip())
        if "tx_message" in changed and s.tx_message:
            bits.append(f'Tx="{s.tx_message}"')
        if bits:
            print(f"  [{mid:<10}] {band:<5} {state} | " + "  ".join(bits))

    def _print_decode(self, mid: str, d: M.Decode) -> None:
        flag = "CQ" if d.is_cq else "  "
        grid = f"  [{d.grid}]" if d.grid else ""
        print(f"{hms(d.time_ms)} [{mid:<10}] {flag} {d.snr:+3d}dB "
              f"{d.delta_time:+4.1f}s {d.delta_frequency:4d}Hz  "
              f"{d.message or '':<22}{grid}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Live read-only WSJT-X instance monitor.")
    ap.add_argument("--host", default="0.0.0.0", help="local interface to bind / multicast")
    ap.add_argument("--port", type=int, default=2237, help="UDP port (default 2237)")
    ap.add_argument("--multicast", default=None, help="multicast group to join (e.g. 224.0.0.73)")
    args = ap.parse_args()

    sock = open_socket(args.host, args.port, args.multicast)
    where = f"{args.multicast} (multicast)" if args.multicast else args.host
    print(f"WIMS monitor — listening on {where}:{args.port}  (Ctrl-C to stop)\n")

    mon = Monitor()
    try:
        while True:
            data, _addr = sock.recvfrom(65535)
            msg = M.parse(data)
            if msg is not None:
                mon.handle(msg, time.time())
    except KeyboardInterrupt:
        print(f"\nstopped — {len(mon._instances)} instance(s) seen: "
              f"{', '.join(mon._instances) or 'none'}")


if __name__ == "__main__":
    main()
