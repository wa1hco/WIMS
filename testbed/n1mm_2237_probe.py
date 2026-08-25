# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Measure how N1MM (or a socket bound like N1MM) receives log traffic on :2237.

Hard-won lab question this answers
----------------------------------
WSJT-X sends to ``224.0.0.73:2237``. N1MM's WSJT reader is often set to
``127.0.0.1:2237`` (2333 / 52001 off). Does that loopback bind ignore LAN
multicast, so a log agent must forward mcast → localhost:2237?

Two modes
---------
1. **``--self-test``** (no N1MM): bind a UDP socket the way N1MM is *configured*
   (loopback vs any + optional multicast join), send QSO Logged to several
   destinations, report which packets arrive. Pure OS/socket measurement.

2. **``--live``** (default when not self-test): send distinctive QSO Logged
   probes to multicast / unicast targets and watch N1MM Broadcast Contacts
   (``:12060``) for matching ``<contactinfo>``. Needs Contacts broadcast on.

Examples
--------
  # OS-level: does 127.0.0.1:2237 see multicast?
  python testbed/n1mm_2237_probe.py --self-test --bind 127.0.0.1

  # OS-level: 0.0.0.0:2237 + join group (true dual-consumer seat)
  python testbed/n1mm_2237_probe.py --self-test --bind 0.0.0.0 --join 224.0.0.73

  # Live against three N1MM VMs (from Linux contest NIC)
  python testbed/n1mm_2237_probe.py --live \\
      --iface 192.168.1.119 \\
      --targets 192.168.1.120,192.168.1.121,192.168.1.122 \\
      --wait 8
"""

from __future__ import annotations

import argparse
import re
import select
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

GROUP_DEFAULT = "224.0.0.73"
PORT_DEFAULT = 2237
N1MM_CONTACT_PORT = 12060
MID = "WIMS-2237-PROBE"

_CALL_RE = re.compile(r"<call>([^<]+)</call>", re.I)
_STATION_RE = re.compile(r"<StationName>([^<]+)</StationName>", re.I)
_BAND_RE = re.compile(r"<band>([^<]+)</band>", re.I)
_FREQ_RE = re.compile(r"<frequency[^>]*>([^<]+)</frequency>", re.I)


@dataclass
class Probe:
    tag: str
    dx_call: str
    dest: tuple[str, int]
    kind: str  # mcast | unicast | loopback | adif2237 | adif2333 | adif52001
    freq_hz: int
    payload: bytes
    sent_ok: bool = False
    send_err: str = ""
    heard_socket: bool = False          # self-test: arrived on bind
    heard_contactinfo: bool = False     # live: N1MM broadcast Contacts
    contact_from: str = ""
    contact_station: str = ""
    notes: list[str] = field(default_factory=list)


def _parse_hostport(spec: str, default_port: int) -> tuple[str, int]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("empty host:port")
    if ":" in spec:
        host, _, port = spec.rpartition(":")
        return host or "127.0.0.1", int(port or default_port)
    return spec, default_port


def _unique_calls(n: int, prefix: str = "W1P") -> list[str]:
    """Synthetic but callsign-shaped markers (digit in body)."""
    out = []
    for i in range(1, n + 1):
        out.append(f"{prefix}{i:02d}")
    return out


def build_probes(
    *,
    group: str,
    port: int,
    targets: list[str],
    include_loopback: bool,
    include_adif_controls: bool,
    freq_hz: int,
    my_call: str,
    my_grid: str,
) -> list[Probe]:
    dests: list[tuple[str, str, int]] = []  # kind, host, port
    dests.append(("mcast", group, port))
    if include_loopback:
        dests.append(("loopback", "127.0.0.1", port))
    for t in targets:
        host, p = _parse_hostport(t, port)
        dests.append(("unicast", host, p))
    if include_adif_controls:
        # Wrong-protocol control on 2237 + known alternate ingest ports.
        dests.append(("adif2237", group, port))
        if targets:
            host, _ = _parse_hostport(targets[0], port)
            dests.append(("adif2333", host, 2333))
            dests.append(("adif52001", host, 52001))
        else:
            dests.append(("adif2333", "127.0.0.1", 2333))
            dests.append(("adif52001", "127.0.0.1", 52001))

    calls = _unique_calls(len(dests))
    probes: list[Probe] = []
    for call, (kind, host, p) in zip(calls, dests):
        tag = f"WIMS2237-{kind}-{host}-{p}"
        if kind.startswith("adif"):
            mhz = freq_hz / 1e6
            band = "6m" if freq_hz >= 50e6 and freq_hz < 54e6 else (
                "2m" if freq_hz >= 144e6 and freq_hz < 148e6 else "20m")
            adif = (
                f"<CALL:{len(call)}>{call}"
                f"<GRIDSQUARE:4>FN42"
                f"<MODE:3>FT8"
                f"<FREQ:{len(f'{mhz:.6f}')}>{mhz:.6f}"
                f"<BAND:{len(band)}>{band}"
                f"<STATION_CALLSIGN:{len(my_call)}>{my_call}"
                f"<MY_GRIDSQUARE:{len(my_grid)}>{my_grid}"
                f"<COMMENT:{len(tag)}>{tag}"
                " <eor>"
            )
            if kind == "adif2237":
                # NetworkMessage Logged ADIF on the WSJT reader port (protocol mismatch probe).
                payload = E.build_logged_adif(MID, adif)
            else:
                # Raw ADIF+eor — Secondary UDP / 52001 style.
                payload = adif.encode("ascii", "replace")
        else:
            payload = E.build_qso_logged(
                MID,
                dx_call=call,
                dx_grid="FN42",
                tx_frequency=freq_hz,
                mode="FT8",
                my_call=my_call,
                my_grid=my_grid,
                comments=tag,
                report_sent="-10",
                report_received="-12",
            )
        probes.append(Probe(
            tag=tag, dx_call=call, dest=(host, p), kind=kind,
            freq_hz=freq_hz, payload=payload,
        ))
    return probes


def _send_all(probes: list[Probe], *, iface: str | None) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Same-host self-test needs the datagram to loop back to other local members.
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    except OSError:
        pass
    # Bind source for IGMP / correct egress NIC when multicasting from Linux.
    if iface and iface not in ("0.0.0.0", ""):
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(iface))
        except OSError as e:
            print(f"warning: IP_MULTICAST_IF {iface}: {e}", file=sys.stderr)
        if iface not in ("127.0.0.1", "::1"):
            try:
                sock.bind((iface, 0))
            except OSError as e:
                print(f"warning: bind({iface},0): {e}", file=sys.stderr)
    for pr in probes:
        try:
            sock.sendto(pr.payload, pr.dest)
            pr.sent_ok = True
        except OSError as e:
            pr.send_err = str(e)
            pr.notes.append(f"send failed: {e}")
    return sock

# --------------------------------------------------------------------------- #
# Self-test: measure what a N1MM-like bind receives
# --------------------------------------------------------------------------- #

def run_self_test(args: argparse.Namespace) -> int:
    bind_host = args.bind
    port = args.port
    join = args.join
    print(f"self-test: bind {bind_host}:{port}"
          + (f" join {join}" if join else " (no multicast join)"))
    print("           sending QSO Logged to mcast / loopback / targets; "
          "report which arrive on this bind.\n")

    listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listen.bind((bind_host, port))
    except OSError as e:
        print(f"FATAL: cannot bind {bind_host}:{port}: {e}", file=sys.stderr)
        print("       Is N1MM (or another probe) already holding the port?",
              file=sys.stderr)
        return 2
    if join:
        # 0.0.0.0 in the mreq iface slot = "any interface" (works for local loop).
        if_ip = args.iface or "0.0.0.0"
        if if_ip in ("127.0.0.1", "::1"):
            if_ip = "0.0.0.0"
        try:
            mreq = socket.inet_aton(join) + socket.inet_aton(if_ip)
            listen.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError as e:
            print(f"FATAL: join {join} via {if_ip}: {e}", file=sys.stderr)
            return 2
    listen.setblocking(False)

    probes = build_probes(
        group=args.group, port=port, targets=list(args.targets or []),
        include_loopback=True,
        include_adif_controls=bool(args.controls),
        freq_hz=args.freq_hz, my_call=args.my_call, my_grid=args.my_grid,
    )
    # Map dx_call / payload identity → probe
    by_call = {p.dx_call: p for p in probes}

    _send_all(probes, iface=args.iface)
    deadline = time.time() + args.wait
    while time.time() < deadline:
        r, _, _ = select.select([listen], [], [], max(0.0, deadline - time.time()))
        if not r:
            continue
        try:
            data, addr = listen.recvfrom(65535)
        except OSError:
            continue
        msg = M.parse(data)
        call = None
        if isinstance(msg, M.QSOLogged):
            call = msg.dx_call
        elif isinstance(msg, M.LoggedADIF) and msg.adif:
            m = re.search(r"<CALL:\d+>([^<]+)", msg.adif, re.I)
            call = m.group(1) if m else None
        else:
            # Raw ADIF control
            m = re.search(r"<CALL:\d+>([^<]+)", data.decode("ascii", "replace"), re.I)
            call = m.group(1) if m else None
        if call and call in by_call:
            by_call[call].heard_socket = True
            by_call[call].notes.append(f"recv from {addr[0]}:{addr[1]}")
        else:
            print(f"  (noise {len(data)} B from {addr[0]}:{addr[1]})")

    listen.close()
    _print_report(probes, mode="self-test", bind=f"{bind_host}:{port}", join=join)
    # Hypothesis check for the common config.
    mcast = next((p for p in probes if p.kind == "mcast"), None)
    loop = next((p for p in probes if p.kind == "loopback"), None)
    if bind_host in ("127.0.0.1", "::1") and not join:
        if mcast and loop:
            if not mcast.heard_socket and loop.heard_socket:
                print("RESULT: loopback bind ignored multicast — matches the "
                      "log-agent premise (forward mcast → 127.0.0.1:2237).")
                return 0
            if mcast.heard_socket:
                print("RESULT: UNEXPECTED — loopback bind still saw multicast. "
                      "OS/socket semantics differ from the lab assumption.")
                return 1
    return 0


# --------------------------------------------------------------------------- #
# Live: send probes, watch N1MM contactinfo
# --------------------------------------------------------------------------- #

def run_live(args: argparse.Namespace) -> int:
    probes = build_probes(
        group=args.group, port=args.port, targets=list(args.targets or []),
        include_loopback=bool(args.loopback),
        include_adif_controls=bool(args.controls),
        freq_hz=args.freq_hz, my_call=args.my_call, my_grid=args.my_grid,
    )
    by_call = {p.dx_call.upper(): p for p in probes}

    print("live: sending distinctive QSO Logged probes, then listening for")
    print(f"      N1MM <contactinfo> on :{args.n1mm_port} for {args.wait}s")
    print("      (Config → Broadcast Data → Contacts must be ON)\n")
    for p in probes:
        print(f"  will send {p.dx_call:8}  {p.kind:10} → {p.dest[0]}:{p.dest[1]}"
              f"  freq={p.freq_hz}  tag={p.tag}")
    print()

    contact_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    contact_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        contact_sock.bind(("0.0.0.0", args.n1mm_port))
    except OSError as e:
        print(f"FATAL: bind 0.0.0.0:{args.n1mm_port}: {e}", file=sys.stderr)
        return 2
    if args.n1mm_group:
        if_ip = args.iface or "0.0.0.0"
        try:
            mreq = (socket.inet_aton(args.n1mm_group)
                    + socket.inet_aton(if_ip))
            contact_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            print(f"joined N1MM contact multicast {args.n1mm_group} via {if_ip}")
        except OSError as e:
            print(f"warning: N1MM group join failed: {e}", file=sys.stderr)
    contact_sock.setblocking(False)

    # Brief settle so the listen socket is ready before sends.
    time.sleep(0.2)
    _send_all(probes, iface=args.iface)
    for p in probes:
        status = "sent" if p.sent_ok else f"FAIL {p.send_err}"
        print(f"  {status:4} {p.dx_call:8} → {p.dest[0]}:{p.dest[1]}")

    deadline = time.time() + args.wait
    noise = 0
    while time.time() < deadline:
        r, _, _ = select.select([contact_sock], [], [],
                                max(0.0, deadline - time.time()))
        if not r:
            continue
        try:
            data, addr = contact_sock.recvfrom(65535)
        except OSError:
            continue
        text = data.decode("utf-8", "replace")
        if "<contactinfo" not in text.lower() and "<contactreplace" not in text.lower():
            noise += 1
            continue
        m = _CALL_RE.search(text)
        if not m:
            continue
        call = m.group(1).strip().upper()
        st = _STATION_RE.search(text)
        station = st.group(1) if st else ""
        if call in by_call:
            pr = by_call[call]
            pr.heard_contactinfo = True
            pr.contact_from = f"{addr[0]}:{addr[1]}"
            pr.contact_station = station
            band = _BAND_RE.search(text)
            print(f"  HIT  {call}  from {pr.contact_from}  "
                  f"StationName={station!r}  "
                  f"band={(band.group(1) if band else '?')}")
        else:
            print(f"  (other contact {call} from {addr[0]})")

    contact_sock.close()
    if noise:
        print(f"  ({noise} non-contact UDP on :{args.n1mm_port})")
    _print_report(probes, mode="live", bind=f"contact :{args.n1mm_port}",
                  join=args.n1mm_group)
    return 0


def _print_report(probes: list[Probe], *, mode: str, bind: str,
                  join: str | None) -> None:
    print()
    print("=" * 72)
    print(f"N1MM :2237 probe report  mode={mode}  listen={bind}"
          + (f" join={join}" if join else ""))
    print("-" * 72)
    hdr = f"{'call':8} {'kind':10} {'dest':22} {'sent':4} {'heard':5} notes"
    print(hdr)
    for p in probes:
        heard = p.heard_socket if mode == "self-test" else p.heard_contactinfo
        dest = f"{p.dest[0]}:{p.dest[1]}"
        note = "; ".join(p.notes)
        if p.contact_station:
            note = (note + "; " if note else "") + f"Station={p.contact_station}"
        print(f"{p.dx_call:8} {p.kind:10} {dest:22} "
              f"{'Y' if p.sent_ok else 'N':4} "
              f"{'Y' if heard else 'N':5} {note}")
    print("=" * 72)
    print("Interpretation hints:")
    print("  mcast heard + loopback/unicast not  → reader joined the group")
    print("  loopback heard only                 → bind is localhost-only "
          "(agent must forward)")
    print("  unicast to VM IP heard, mcast not   → bound 0.0.0.0 but no IGMP join")
    print("  adif2333/52001 hit, qso2237 miss    → 2237 path dead; alternate ingest works")
    print("  nothing in live mode                → Contacts broadcast off, or "
          "N1MM did not log")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true",
                      help="no N1MM: measure what a local bind receives")
    mode.add_argument("--live", action="store_true",
                      help="send probes and watch N1MM contactinfo :12060")

    ap.add_argument("--group", default=GROUP_DEFAULT,
                    help="WSJT multicast group (default 224.0.0.73)")
    ap.add_argument("--port", type=int, default=PORT_DEFAULT,
                    help="WSJT / N1MM reader port (default 2237)")
    ap.add_argument("--iface", default=None,
                    help="LAN IP for multicast send/join (Linux contest NIC)")
    ap.add_argument("--targets", default="",
                    help="comma-separated N1MM host or host:port unicast targets")
    ap.add_argument("--freq-hz", type=int, default=50_313_000,
                    help="tx_frequency in QSO Logged (default 50313000 = 6m)")
    ap.add_argument("--my-call", default="WA1HCO")
    ap.add_argument("--my-grid", default="FN42")
    ap.add_argument("--wait", type=float, default=5.0,
                    help="seconds to listen after send (default 5)")
    ap.add_argument("--controls", action="store_true",
                    help="also probe LoggedADIF on :2237 and raw ADIF on :2333/:52001")
    ap.add_argument("--loopback", action="store_true",
                    help="live mode: also send to 127.0.0.1:port (only useful on N1MM PC)")

    # self-test bind shape
    ap.add_argument("--bind", default="127.0.0.1",
                    help="self-test bind address (default 127.0.0.1)")
    ap.add_argument("--join", default=None,
                    help="self-test: multicast group to join (omit = no join)")

    # live contact listen
    ap.add_argument("--n1mm-port", type=int, default=N1MM_CONTACT_PORT)
    ap.add_argument("--n1mm-group", default=None,
                    help="optional multicast group for N1MM Contacts "
                         "(default: unicast/broadcast bind only)")

    args = ap.parse_args(argv)
    args.targets = [t.strip() for t in (args.targets or "").split(",") if t.strip()]
    args.freq_hz = int(args.freq_hz)

    if args.self_test:
        return run_self_test(args)
    # Default to live when neither flag given — but require explicit --live
    # if that seems surprising; accept bare invocation as live with a note.
    if not args.live and not args.self_test:
        print("note: defaulting to --live (use --self-test for OS bind measurement)\n")
    return run_live(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nprobe: quit")
        raise SystemExit(130)
