"""WSJT-X emulator — N simulated instances with no RF (plan §5.1).

Emits realistic Heartbeat/Status/Decode UDP for several instances (distinct
rig-name ids, bands) on the multicast group, and reacts to inbound Reply / Halt Tx
(an instance flips to TX for a period on Reply, stops on Halt). Lets WIMS's
monitor / fleet view / activity map — and later the §3.2 sender and §3.4 arbiter —
be developed and tested at multi-instance scale with no radios.

Run (from the repo root), then point the fleet view at the same group:
    python testbed/simulators/emulator.py
    python testbed/simulators/emulator.py --period 3 --instances SIM-6M:50313000,SIM-2M:144174000
    # in another window:
    python src/wims/discovery/fleet.py --port 2237 --multicast 224.0.0.73 --host 127.0.0.1

Defaults send on the loopback interface so a local fleet view (--host 127.0.0.1)
sees it without touching the real network.
"""

from __future__ import annotations

import argparse
import random
import select
import socket
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

MYCALL, MYGRID = "WA1HCO", "FN42"

# DX stations the simulated instances "hear" (call, grid).
POOL = [
    ("K1ABC", "FN42"), ("W2XYZ", "FN20"), ("K3DEF", "FM19"), ("N1RWY", "FN43"),
    ("VE3ABC", "FN03"), ("W9XYZ", "EN61"), ("K4GDJ", "EL98"), ("NJ1H", "FN42"),
    ("AA2BB", "FN30"), ("WB8ABC", "EM79"), ("K5XYZ", "EM12"), ("VA2WXY", "FN35"),
]
ROVER_CALL = "K1ROV/R"
ROVER_GRIDS = ["FN31", "FN32", "FN42", "FN41"]  # rover crosses grid lines over time


@dataclass
class SimInstance:
    id: str
    dial_hz: int
    mode: str = "FT8"
    transmitting: bool = False
    tx_until: float = 0.0
    tx_message: str = ""


def parse_instances(spec: str | None) -> list[SimInstance]:
    if not spec:
        return [
            SimInstance("SIM-6M", 50_313_000, "FT8"),
            SimInstance("SIM-2M", 144_174_000, "FT8"),
            SimInstance("SIM-432", 432_174_000, "FT8"),
            SimInstance("SIM-1296", 1_296_174_000, "Q65"),
        ]
    out = []
    for item in spec.split(","):
        parts = item.split(":")
        out.append(SimInstance(parts[0], int(parts[1]), parts[2] if len(parts) > 2 else "FT8"))
    return out


def open_socket(group: str, port: int, iface: str, ttl: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(iface))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)      # receive commands
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    return s


def now_ms_of_day(now: float) -> int:
    return int((now % 86400) * 1000)


def make_decode_message(rng: random.Random, cycle: int) -> str:
    if rng.random() < 0.15:                       # a rover, sometimes in a new grid
        return f"CQ {ROVER_CALL} {ROVER_GRIDS[cycle % len(ROVER_GRIDS)]}"
    call, grid = rng.choice(POOL)
    roll = rng.random()
    if roll < 0.6:
        return f"CQ {call} {grid}"                # calling CQ with grid
    if roll < 0.8:
        return f"{MYCALL} {call} {grid}"          # answering us (Tx1, grid)
    return f"{MYCALL} {call} {rng.choice(['-12', '-08', '+01', 'R-15', 'RR73', '73'])}"


def main() -> None:
    ap = argparse.ArgumentParser(description="WSJT-X emulator (no RF).")
    ap.add_argument("--group", default="224.0.0.73")
    ap.add_argument("--port", type=int, default=2237)
    ap.add_argument("--iface", default="127.0.0.1", help="outgoing/membership interface")
    ap.add_argument("--ttl", type=int, default=1)
    ap.add_argument("--period", type=float, default=15.0, help="TX/RX cycle seconds (lower = faster test)")
    ap.add_argument("--rate", type=int, default=4, help="decodes per cycle per instance")
    ap.add_argument("--instances", default=None, help="comma list of ID:DIAL_HZ[:MODE]")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    instances = parse_instances(args.instances)
    by_id = {i.id: i for i in instances}
    sock = open_socket(args.group, args.port, args.iface, args.ttl)
    dest = (args.group, args.port)

    def send_status(inst: SimInstance) -> None:
        sock.sendto(E.build_status(
            inst.id, inst.dial_hz, mode=inst.mode, de_call=MYCALL, de_grid=MYGRID,
            transmitting=inst.transmitting, decoding=not inst.transmitting,
            tx_enabled=inst.transmitting, config_name=inst.id,
            tx_message=(inst.tx_message or None) if inst.transmitting else None,
        ), dest)

    print(f"WSJT-X emulator -> {args.group}:{args.port} via {args.iface}  "
          f"| {len(instances)} instances, period {args.period}s  | Ctrl-C to stop")
    for i in instances:
        print(f"  {i.id}: {i.dial_hz/1e6:.6f} MHz {i.mode}")
    print()

    next_cycle = next_hb = time.time()
    cycle = 0
    try:
        while True:
            ready, _, _ = select.select([sock], [], [], 0.2)
            now = time.time()
            if ready:
                data, addr = sock.recvfrom(65535)
                msg = M.parse(data)
                if msg is not None and msg.type in (M.REPLY, M.HALT_TX):
                    inst = by_id.get(msg.id)
                    if inst:
                        if msg.type == M.REPLY:
                            inst.transmitting = True
                            inst.tx_until = now + args.period
                            inst.tx_message = f"{MYCALL} <dx> {MYGRID}"
                            send_status(inst)
                            print(f"  <- REPLY  [{inst.id}] -> TX")
                        else:
                            inst.transmitting = False
                            send_status(inst)
                            print(f"  <- HALT   [{inst.id}] -> RX")
            if now >= next_hb:
                next_hb = now + 15.0
                for inst in instances:
                    sock.sendto(E.build_heartbeat(inst.id, version="2.7.0-sim"), dest)
            if now >= next_cycle:
                next_cycle = now + args.period
                cycle += 1
                tms = now_ms_of_day(now)
                active = []
                for inst in instances:
                    if inst.transmitting and now >= inst.tx_until:
                        inst.transmitting = False
                    send_status(inst)
                    if not inst.transmitting:
                        for _ in range(args.rate):
                            sock.sendto(E.build_decode(
                                inst.id, time_ms=tms, snr=rng.randint(-22, 8),
                                delta_time=round(rng.uniform(-0.3, 0.3), 1),
                                delta_frequency=rng.randint(200, 2800),
                                message=make_decode_message(rng, cycle),
                                mode="~" if inst.mode == "FT8" else "+",
                            ), dest)
                    active.append("TX" if inst.transmitting else "rx")
                print(f"  cycle {cycle:3d}  " + "  ".join(
                    f"{i.id}:{s}" for i, s in zip(instances, active)))
    except KeyboardInterrupt:
        print("\nemulator stopped")


if __name__ == "__main__":
    main()
