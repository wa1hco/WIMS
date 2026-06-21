"""Live interlock-stress harness (plan §5.1 assertion / §5.2 interlock stress).

Starts the emulator with TWO instances sharing one resource group (both on 6 m),
then drives them through the real TxArbiter + TxController: both continuously want
to transmit, the arbiter serializes, the controller sends Reply to whichever holds
the grant. An OverlapDetector watches the actual transmit state off the wire and
asserts **the group never has two transmitters at once** — end-to-end, no RF.

    python testbed/interlock_bench.py
"""

from __future__ import annotations

import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp.controller import TxController  # noqa: E402
from wims.interlock.arbiter import TxArbiter, OverlapDetector  # noqa: E402

GROUP, PORT, IFACE = "224.0.0.73", 2237, "127.0.0.1"
INSTANCES = ["SIM-6A", "SIM-6B"]            # both 6 m -> same resource group
GROUP_OF = lambda i: "6m"                    # noqa: E731  (one shared group)


def main() -> int:
    emu = subprocess.Popen(
        [sys.executable, str(ROOT / "testbed" / "simulators" / "emulator.py"),
         "--period", "2", "--rate", "3", "--seed", "2", "--iface", IFACE,
         "--instances", "SIM-6A:50313000,SIM-6B:50314000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", PORT))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                        struct.pack("4s4s", socket.inet_aton(GROUP), socket.inet_aton(IFACE)))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE))
        sock.settimeout(0.3)

        ctrl = TxController(sock, (GROUP, PORT))
        arb = TxArbiter(GROUP_OF)
        det = OverlapDetector(GROUP_OF)
        prev_tx = {i: False for i in INSTANCES}
        last_cq: M.Decode | None = None
        tx_counts = {i: 0 for i in INSTANCES}

        def want_tx(inst: str) -> None:
            if last_cq is None or prev_tx[inst] or arb.is_granted(inst):
                return
            if arb.request(inst):
                ctrl.reply(inst, last_cq)

        print("interlock bench: two 6 m instances contend for TX (Ctrl-C to stop early)\n")
        end = time.time() + 12
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                for i in INSTANCES:
                    want_tx(i)
                continue
            now = time.time()
            msg = M.parse(data)
            if isinstance(msg, M.Decode) and msg.is_cq:
                last_cq = msg
            elif isinstance(msg, M.Status) and msg.id in INSTANCES:
                det.observe(msg.id, msg.transmitting, now)
                if msg.transmitting and not prev_tx[msg.id]:
                    tx_counts[msg.id] += 1
                if prev_tx[msg.id] and not msg.transmitting:   # this instance just finished TX
                    if arb.holder("6m") == msg.id:
                        promoted = arb.release(msg.id)
                        if promoted and last_cq is not None:
                            ctrl.reply(promoted, last_cq)
                    want_tx(msg.id)
                prev_tx[msg.id] = msg.transmitting

        print(f"TX turns:        {tx_counts}")
        print(f"max concurrent:  {len(det.transmitting)} transmitting now")
        print(f"overlap violations (must be 0): {len(det.violations)}")
        ok = det.clean and all(c > 0 for c in tx_counts.values())
        print("\nRESULT:", "PASS - serialized, zero overlap" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        emu.terminate()
        try:
            emu.wait(timeout=3)
        except subprocess.TimeoutExpired:
            emu.kill()


if __name__ == "__main__":
    sys.exit(main())
