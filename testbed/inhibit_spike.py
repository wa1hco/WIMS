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

"""TX-inhibit spike (design doc wims_tx_inhibit.md §11.6 step 1).

Two small programs and a selftest, exercising the pure logic in
``wims.interlock.inhibit`` over real UDP — no WSJT-X involved:

  gate      WSJT-X-side stand-in: bind the inhibit port (22372, else
            ephemeral), print state transitions with timestamps; with
            --rts /dev/ttyUSBn also drive the RTS line = NOT inhibited
            (Linux only) so a scope can measure the full path.
  agent     SSB/CW Key-agent stand-in: send keyed/clear/keepalives to
            --targets.  Key input from --script (offline timeline), or
            --serial /dev/ttyUSBn CTS (Linux, TIOCMIWAIT edge wait).
  selftest  Run agent logic against a gate over UDP loopback with a
            CW-style keying script; assert behavior and print the
            measured send->transition latency distribution.  Exits
            nonzero on failure (usable as a slow test).

Examples:
  python testbed/inhibit_spike.py selftest
  python testbed/inhibit_spike.py gate --rts /dev/ttyUSB1
  python testbed/inhibit_spike.py agent --targets 192.168.1.42:22372 \
      --script "k0.7 c0.4 k0.05 c0.05 k0.05 c2.0"
"""

from __future__ import annotations

import argparse
import select
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wims.interlock.inhibit import (  # noqa: E402
    DEFAULT_GATE_PORT,
    InhibitGate,
    KeyAgentScheduler,
)

TICK_S = 0.02  # gate/agent loop period; well under the 0.2 s keepalive


# ---------------------------------------------------------------- serial I/O
# Linux-only, stdlib-only (fcntl ioctl on the tty).  Windows would use
# WaitCommEvent via ctypes — out of spike scope, noted in the design doc.

TIOCMGET = 0x5415
TIOCMBIS = 0x5416
TIOCMBIC = 0x5417
TIOCMIWAIT = 0x545C
TIOCM_RTS = 0x004
TIOCM_CTS = 0x020


def _open_tty(dev):
    import os
    return os.open(dev, getattr(__import__("os"), "O_RDWR") | 0)


def rts_set(fd, asserted):
    import fcntl
    import struct
    bits = struct.pack("I", TIOCM_RTS)
    fcntl.ioctl(fd, TIOCMBIS if asserted else TIOCMBIC, bits)


def cts_get(fd):
    import fcntl
    import struct
    buf = struct.pack("I", 0)
    res = fcntl.ioctl(fd, TIOCMGET, buf)
    return bool(struct.unpack("I", res)[0] & TIOCM_CTS)


def cts_wait_edge(fd):
    """Block until any CTS transition (TIOCMIWAIT). Returns new CTS state."""
    import fcntl
    import struct
    fcntl.ioctl(fd, TIOCMIWAIT, struct.pack("I", TIOCM_CTS))
    return cts_get(fd)


# -------------------------------------------------------------------- gate

def bind_gate_socket(prefer_port=DEFAULT_GATE_PORT):
    """§11.2 zero-config bind: well-known port if free, else ephemeral."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", prefer_port))
    except OSError:
        sock.bind(("", 0))
    return sock


def run_gate(args):
    sock = bind_gate_socket(args.port)
    port = sock.getsockname()[1]
    gate = InhibitGate()
    rts_fd = None
    if args.rts:
        rts_fd = _open_tty(args.rts)
        rts_set(rts_fd, True)  # gate open -> line allowed
    print(f"gate: listening on UDP :{port}"
          + (f", driving RTS on {args.rts}" if args.rts else "")
          + "  (Ctrl-C to stop)")
    inhibited = False
    while True:
        ready, _, _ = select.select([sock], [], [], TICK_S)
        now = time.monotonic()
        if ready:
            data, addr = sock.recvfrom(2048)
            gate.on_datagram(data, now)
        state = gate.inhibited(now)
        if state != inhibited:
            inhibited = state
            if rts_fd is not None:
                rts_set(rts_fd, not inhibited)
            who = ",".join(gate.holding_stations(now)) or "-"
            print(f"{now:14.6f}  {'INHIBITED' if inhibited else 'OPEN':9s}"
                  f"  by={who}  keyed_rx={gate.keyed_rx}"
                  f" clear_rx={gate.clear_rx} expiries={gate.expiries}"
                  f" invalid={gate.invalid}")


# -------------------------------------------------------------------- agent

def parse_script(text):
    """'k0.7 c0.4 k0.05' -> [(True, 0.7), (False, 0.4), (True, 0.05)]."""
    steps = []
    for tok in text.split():
        kind, dur = tok[0], tok[1:]
        if kind not in "kc":
            raise ValueError(f"bad script token {tok!r} (want k<sec>/c<sec>)")
        steps.append((kind == "k", float(dur)))
    return steps


def parse_targets(text):
    out = []
    for item in text.split(","):
        host, _, port = item.strip().rpartition(":")
        out.append((host or "127.0.0.1", int(port)))
    return out


def run_agent(args):
    targets = parse_targets(args.targets)
    sched = KeyAgentScheduler(args.station, args.band,
                              hang_s=args.hang, ttl_ms=args.ttl_ms)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(datagrams):
        for d in datagrams:
            for t in targets:
                sock.sendto(d, t)

    if args.script:
        steps = parse_script(args.script)
        print(f"agent: scripted keying to {targets}: {args.script}")
        deadline = time.monotonic()
        for keyed, dur in steps:
            send(sched.set_key(keyed, time.monotonic()))
            deadline += dur
            while time.monotonic() < deadline:
                send(sched.poll(time.monotonic()))
                time.sleep(TICK_S)
        while sched.holding:                      # drain hang -> clear
            send(sched.poll(time.monotonic()))
            time.sleep(TICK_S)
        print("agent: script done")
        return

    if args.serial:
        import threading
        print(f"agent: watching CTS on {args.serial}, sending to {targets}")
        fd = _open_tty(args.serial)
        state = {"cts": cts_get(fd)}

        def watcher():
            while True:
                state["cts"] = cts_wait_edge(fd)

        threading.Thread(target=watcher, daemon=True).start()
        send(sched.set_key(state["cts"], time.monotonic()))
        while True:
            send(sched.set_key(state["cts"], time.monotonic()))
            send(sched.poll(time.monotonic()))
            time.sleep(TICK_S)

    raise SystemExit("agent: need --script or --serial")


# ----------------------------------------------------------------- selftest

def run_selftest(_args):
    """Agent -> UDP loopback -> gate, CW-style script, latency measured."""
    sock = bind_gate_socket(0)                    # ephemeral: never collide in CI
    port = sock.getsockname()[1]
    gate = InhibitGate()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sched = KeyAgentScheduler("SELFTEST-SSB", "222",
                              hang_s=0.3, keepalive_s=0.1, ttl_ms=400)

    latencies = []
    transitions = []                              # (t, inhibited)
    failures = []

    def pump(deadline):
        """Deliver datagrams until deadline, recording gate transitions."""
        while True:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                return
            ready, _, _ = select.select([sock], [], [], min(timeout, TICK_S))
            now = time.monotonic()
            before = gate.inhibited(now)
            if ready:
                data, _addr = sock.recvfrom(2048)
                gate.on_datagram(data, now)
            after = gate.inhibited(time.monotonic())
            if after != before:
                transitions.append((time.monotonic(), after))

    def send_and_time(datagrams):
        for d in datagrams:
            t0 = time.monotonic()
            tx.sendto(d, ("127.0.0.1", port))
            before = gate.inhibited(t0)
            pump(time.monotonic() + 0.05)         # give the datagram 50 ms max
            after = gate.inhibited(time.monotonic())
            if after != before:
                latencies.append(transitions[-1][0] - t0)

    # Scenario 1: one 0.7 s SSB burst -> assert immediately, clear after hang.
    send_and_time(sched.set_key(True, time.monotonic()))
    if not gate.inhibited(time.monotonic()):
        failures.append("burst: gate did not assert on key-down")
    end = time.monotonic() + 0.7
    while time.monotonic() < end:
        send_and_time(sched.poll(time.monotonic()))
        pump(time.monotonic() + TICK_S)
        if not gate.inhibited(time.monotonic()):
            failures.append("burst: gate dropped during hold")
            break
    send_and_time(sched.set_key(False, time.monotonic()))
    t_keyup = time.monotonic()
    while sched.holding:
        send_and_time(sched.poll(time.monotonic()))
        pump(time.monotonic() + TICK_S)
    pump(time.monotonic() + 0.05)
    t_open = time.monotonic()
    if gate.inhibited(t_open):
        failures.append("burst: gate still inhibited after clear")
    hang_measured = t_open - t_keyup
    if not (0.25 <= hang_measured <= 0.6):
        failures.append(f"burst: release at {hang_measured:.3f}s vs hang 0.3s")
    if gate.expiries != 0:
        failures.append("burst: released by deadman, not by clear")

    # Scenario 2: CW string (40 ms dits / 60 ms gaps) -> one continuous hold.
    clears_before = gate.clear_rx
    for _ in range(15):
        send_and_time(sched.set_key(True, time.monotonic()))
        pump(time.monotonic() + 0.04)
        send_and_time(sched.set_key(False, time.monotonic()))
        pump(time.monotonic() + 0.06)
        send_and_time(sched.poll(time.monotonic()))
        if not gate.inhibited(time.monotonic()):
            failures.append("cw: gate dropped between elements")
            break
    while sched.holding:
        send_and_time(sched.poll(time.monotonic()))
        pump(time.monotonic() + TICK_S)
    pump(time.monotonic() + 0.05)
    if gate.clear_rx - clears_before != 1:
        failures.append(f"cw: expected exactly 1 clear, got "
                        f"{gate.clear_rx - clears_before}")
    if gate.inhibited(time.monotonic()):
        failures.append("cw: gate stuck after string")

    # Scenario 3: agent death -> deadman releases and alarms.
    expiries_before = gate.expiries
    sched2 = KeyAgentScheduler("DYING-SSB", "222", keepalive_s=0.1, ttl_ms=400)
    send_and_time(sched2.set_key(True, time.monotonic()))
    pump(time.monotonic() + 0.6)                  # no keepalives: ttl 400 ms
    if gate.inhibited(time.monotonic()):
        failures.append("deadman: gate not released after ttl")
    if gate.expiries != expiries_before + 1:
        failures.append("deadman: expiry not counted/alarmed")

    lat_ms = sorted(x * 1000 for x in latencies)
    if lat_ms:
        mid = lat_ms[len(lat_ms) // 2]
        print(f"selftest: {len(lat_ms)} UDP-loopback transitions — "
              f"median {mid:.3f} ms, min {lat_ms[0]:.3f}, max {lat_ms[-1]:.3f}")
    print(f"selftest: hang release measured at {hang_measured * 1000:.0f} ms "
          f"(configured 300 + one keepalive/tick of slack)")
    if failures:
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print("selftest: PASS (assert-on-keydown, continuous CW hold, "
          "clear-after-hang, deadman+alarm)")
    return 0


# --------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="WSJT-X-side gate stand-in")
    g.add_argument("--port", type=int, default=DEFAULT_GATE_PORT)
    g.add_argument("--rts", help="drive RTS on this tty = NOT inhibited (Linux)")

    a = sub.add_parser("agent", help="SSB/CW Key-agent stand-in")
    a.add_argument("--targets", required=True,
                   help="host:port[,host:port...] of gate(s)")
    a.add_argument("--station", default="SPIKE-SSB")
    a.add_argument("--band", default="222")
    a.add_argument("--hang", type=float, default=0.5)
    a.add_argument("--ttl-ms", type=int, default=600)
    a.add_argument("--script", help='keying timeline, e.g. "k0.7 c0.4 k0.05"')
    a.add_argument("--serial", help="watch CTS on this tty (Linux)")

    sub.add_parser("selftest", help="loopback agent+gate, assert + latency")

    args = ap.parse_args(argv)
    if args.cmd == "gate":
        run_gate(args)
    elif args.cmd == "agent":
        run_agent(args)
    else:
        return run_selftest(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
