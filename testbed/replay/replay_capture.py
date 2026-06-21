"""Replay a captured WSJT-X JSONL capture (plan §5.1 captured-traffic replay).

Two modes:
  --view  (default) parse each datagram and feed the live console Monitor — an
          offline dry-run of the §3.1 parser + monitor over recorded traffic.
  --emit HOST:PORT   re-send the raw datagrams over UDP (optionally at original
          timing) so the real monitor / WIMS can consume them with no radio.

Run (from the repo root):
    python testbed/replay/replay_capture.py
    python testbed/replay/replay_capture.py captures/wsjtx-20260616-221551.jsonl
    python testbed/replay/replay_capture.py --emit 224.0.0.73:2237 --realtime
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp.monitor import Monitor  # noqa: E402


def latest_capture() -> Path | None:
    caps = sorted(Path("captures").glob("wsjtx-*.jsonl"))
    return caps[-1] if caps else None


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def run_view(records: list[dict]) -> None:
    mon = Monitor()
    seq = 0.0
    for rec in records:
        msg = M.parse(bytes.fromhex(rec["hex"]))
        if msg is not None:
            seq += 1
            mon.handle(msg, seq)
    print(f"\nreplayed {len(records)} datagrams - "
          f"{len(mon._instances)} instance(s): {', '.join(mon._instances) or 'none'}")


def run_emit(records: list[dict], dest: str, realtime: bool) -> None:
    host, port = dest.rsplit(":", 1)
    addr = (host, int(port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 3)
    print(f"emitting {len(records)} datagrams to {host}:{port} "
          f"({'realtime' if realtime else 'as fast as possible'})")
    prev_ts = None
    for rec in records:
        if realtime and prev_ts is not None:
            time.sleep(max(0.0, rec["ts"] - prev_ts))
        prev_ts = rec["ts"]
        sock.sendto(bytes.fromhex(rec["hex"]), addr)
    print("done")


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay a captured WSJT-X JSONL capture.")
    ap.add_argument("capture", nargs="?", help="capture file (default: newest in captures/)")
    ap.add_argument("--emit", metavar="HOST:PORT", help="re-emit over UDP instead of viewing")
    ap.add_argument("--realtime", action="store_true", help="with --emit, preserve original timing")
    args = ap.parse_args()

    path = Path(args.capture) if args.capture else latest_capture()
    if not path or not path.exists():
        sys.exit("no capture file found (pass one, or capture into captures/ first)")

    records = load(path)
    print(f"loaded {len(records)} datagrams from {path}\n")
    if args.emit:
        run_emit(records, args.emit, args.realtime)
    else:
        run_view(records)


if __name__ == "__main__":
    main()
