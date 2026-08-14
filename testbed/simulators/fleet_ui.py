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

"""UI fleet scenario — simulated WSJT-X + N1MM for Status / inventory work (no RF).

Default layout matches the multi-multi sketch (networking §1):

  **6 m (port 2237)** — three WSJT-X beams (**South**, **West**, **East**) → **one**
  N1MM on the **SSB/CW PC**:
      South, West, East  →  N1MM-50 @ SSB-50-PC

  **2 m (port 2238)** — two WSJT-X (separate radios/PCs) + **one SSB/CW PC**:
      TRAILER-144-FT8   FT8
      TRAILER-144-MSK   MSK144
      both → N1MM-144
      N1MM-144-SSB (or SSB RadioInfo) — **no WSJT** (voice PC on the band)

  **222 / 432 (ports 2239 / 2241)** — **one PC per band**, switches FT8 ↔ SSB/CW:
      ROY-222 / ROY-432 emit WSJT only in the digital half-period; N1MM stays up
      always so Status shows N1MM with WSJT during FT8 and **no WSJT** during SSB.

Run (repo root):

    scripts/run_ui_fleet.sh
    # or: PYTHONPATH=src python3 testbed/simulators/fleet_ui.py
    # → http://localhost:8787/status

WSJT-X uses band stream ports; N1MM XML → UDP :12060 unicast (--n1mm-host).
"""

from __future__ import annotations

import argparse
import random
import select
import socket
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_esc

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.core.bands import band_label  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

MYCALL, MYGRID = "N2OY", "FN42"

# Band stream registry (wims_networking.md §4) — dial Hz → plane-A port.
BAND_PORT = {
    "6m": 2237,
    "2m": 2238,
    "1.25m": 2239,
    "70cm": 2241,
    "33cm": 2242,
    "23cm": 2243,
}

POOL = [
    ("K1ABC", "FN42"), ("W2XYZ", "FN20"), ("K3DEF", "FM19"), ("N1RWY", "FN43"),
    ("VE3ABC", "FN03"), ("W9XYZ", "EN61"), ("K4GDJ", "EL98"), ("NJ1H", "FN42"),
    ("AA2BB", "FN30"), ("WB8ABC", "EM79"), ("K5XYZ", "EM12"), ("VA2WXY", "FN35"),
]


@dataclass
class SimWsjt:
    id: str
    dial_hz: int
    mode: str = "FT8"
    transmitting: bool = False
    tx_until: float = 0.0
    tx_message: str = ""
    # Roy 222/432: one PC switches FT8 ↔ SSB — when False, stop WSJT UDP (N1MM stays).
    mode_switch: bool = False
    digital_active: bool = True

    @property
    def band(self) -> str:
        return band_label(self.dial_hz)

    @property
    def port(self) -> int:
        return BAND_PORT.get(self.band, 2237)

    @property
    def live(self) -> bool:
        """Emit WSJT traffic only when in digital mode (always for fixed digital seats)."""
        return self.digital_active or not self.mode_switch


@dataclass
class SimN1mm:
    """One N1MM process on the LAN (station name + host identity)."""

    station: str                 # StationName (logger id in WIMS)
    band_mhz: float              # radio / primary digital band (MHz)
    host_label: str              # human note only (printed); UDP src is still iface
    mycall: str = MYCALL
    # Optional: which WSJT ids *should* bind here (documentation + contactinfo band).
    feeds: list[str] = field(default_factory=list)
    # True → logger sits on / with the SSB/CW position for that band.
    ssb_pc: bool = False
    # Linked mode-switch WSJT ids: only send contactinfo while those are digital-active.
    mode_switch_feeds: list[str] = field(default_factory=list)
    seq: int = 0
    # When True, RadioInfo Mode=USB (SSB period) vs DIGI when digital.
    prefer_ssb_radioinfo: bool = False


def default_wsjt() -> list[SimWsjt]:
    return [
        # --- 6 m: three beams → N1MM-50 on SSB-PC ---
        SimWsjt("TRAILER-50-A", 50_313_000, "FT8"),
        SimWsjt("TRAILER-50-B", 50_313_000, "FT8"),
        SimWsjt("TV-50-C", 50_313_000, "FT8"),
        # --- 2 m: FT8 + MSK144 (two WSJT) + separate SSB/CW PC (N1MM only) ---
        SimWsjt("TRAILER-144-FT8", 144_174_000, "FT8"),
        SimWsjt("TRAILER-144-MSK", 144_174_000, "MSK144"),
        # --- 222 / 432: one PC each, switches FT8 ↔ SSB/CW ---
        SimWsjt("ROY-222", 222_174_000, "FT8", mode_switch=True, digital_active=True),
        SimWsjt("ROY-432", 432_174_000, "FT8", mode_switch=True, digital_active=True),
    ]


def default_n1mm() -> list[SimN1mm]:
    return [
        SimN1mm(
            station="N1MM-50",
            band_mhz=50.0,
            host_label="SSB-50-PC",
            feeds=["TRAILER-50-A", "TRAILER-50-B", "TV-50-C"],
            ssb_pc=True,
        ),
        # Digital logger for both 2 m WSJT instances (FT8 + MSK).
        SimN1mm(
            station="N1MM-144",
            band_mhz=144.0,
            host_label="TRAILER-144",
            feeds=["TRAILER-144-FT8", "TRAILER-144-MSK"],
        ),
        # Separate SSB/CW PC on 2 m — on network, no WSJT logging to it.
        SimN1mm(
            station="N1MM-144-SSB",
            band_mhz=144.0,
            host_label="SSB-144-PC",
            feeds=[],
            ssb_pc=True,
            prefer_ssb_radioinfo=True,
        ),
        # Roy: one N1MM per band on the same seat PC as the mode-switch radio.
        SimN1mm(
            station="N1MM-222",
            band_mhz=222.0,
            host_label="ROY-222",
            feeds=["ROY-222"],
            mode_switch_feeds=["ROY-222"],
            ssb_pc=True,
        ),
        SimN1mm(
            station="N1MM-432",
            band_mhz=432.0,
            host_label="ROY-432",
            feeds=["ROY-432"],
            mode_switch_feeds=["ROY-432"],
            ssb_pc=True,
        ),
    ]


def open_mcast_send(group: str, port: int, iface: str, ttl: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind to port so we can also receive Reply/Halt for that band stream.
    try:
        s.bind((iface, port))
    except OSError:
        s.bind(("", port))
    mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(iface))
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError:
        pass
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    return s


def open_n1mm_send() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return s


def now_ms_of_day(now: float) -> int:
    return int((now % 86400) * 1000)


def make_decode_message(rng: random.Random) -> str:
    call, grid = rng.choice(POOL)
    roll = rng.random()
    if roll < 0.55:
        return f"CQ {call} {grid}"
    if roll < 0.75:
        return f"{MYCALL} {call} {grid}"
    return f"{MYCALL} {call} {rng.choice(['-12', '-08', '+01', 'R-15', 'RR73', '73'])}"


def n1mm_freq_100hz(band_mhz: float) -> int:
    """N1MM RadioInfo Freq field is typically 100 Hz units."""
    return int(round(band_mhz * 10_000))


def build_radioinfo(n: SimN1mm, *, mode: str = "USB") -> str:
    n.seq += 1
    freq = n1mm_freq_100hz(n.band_mhz)
    # Include a stable NetBiosName so merges behave like a real PC.
    netbios = n.host_label.replace(" ", "-")[:15]
    return (
        f"<RadioInfo>"
        f"<app>N1MM</app>"
        f"<StationName>{xml_esc(n.station)}</StationName>"
        f"<NetBiosName>{xml_esc(netbios)}</NetBiosName>"
        f"<RadioNr>1</RadioNr>"
        f"<Freq>{freq}</Freq><TXFreq>{freq}</TXFreq>"
        f"<Mode>{xml_esc(mode)}</Mode>"
        f"<OpCall>{xml_esc(n.mycall)}</OpCall>"
        f"<IsRunning>False</IsRunning>"
        f"<IsTransmitting>False</IsTransmitting>"
        f"</RadioInfo>"
    )


def build_appinfo(n: SimN1mm) -> str:
    return (
        f"<AppInfo>"
        f"<app>N1MM</app>"
        f"<StationName>{xml_esc(n.station)}</StationName>"
        f"<dbname>UI_SIM</dbname>"
        f"</AppInfo>"
    )


def build_contactinfo(n: SimN1mm, call: str, grid: str) -> str:
    """Logged QSO on this N1MM's digital band — sets last_band for WSJT bind."""
    cid = uuid.uuid4().hex[:12]
    band = f"{n.band_mhz:g}"  # "50", "144", …
    return (
        f"<contactinfo>"
        f"<app>N1MM</app>"
        f"<contestname>ARRLVHFJUN</contestname>"
        f"<contestnr>1</contestnr>"
        f"<timestamp>{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}</timestamp>"
        f"<mycall>{xml_esc(n.mycall)}</mycall>"
        f"<band>{band}</band>"
        f"<txfreq>{int(n.band_mhz * 1_000_000)}</txfreq>"
        f"<mode>FT8</mode>"
        f"<call>{xml_esc(call)}</call>"
        f"<countryprefix>K</countryprefix>"
        f"<wpxprefix>K1</wpxprefix>"
        f"<stationprefix>{xml_esc(n.mycall)}</stationprefix>"
        f"<continent>NA</continent>"
        f"<snt>599</snt><rcv>599</rcv>"
        f"<sntnr>0</sntnr><rcvnr>0</rcvnr>"
        f"<gridsquare>{xml_esc(grid)}</gridsquare>"
        f"<exchange1></exchange1>"
        f"<section></section>"
        f"<comment>ui-sim</comment>"
        f"<qth></qth>"
        f"<name></name>"
        f"<power></power>"
        f"<misctext></misctext>"
        f"<zone>0</zone><prec></prec><ck>0</ck>"
        f"<ismultiplier1>0</ismultiplier1>"
        f"<ismultiplier2>0</ismultiplier2>"
        f"<ismultiplier3>0</ismultiplier3>"
        f"<points>1</points>"
        f"<radionr>1</radionr>"
        f"<RoverLocation></RoverLocation>"
        f"<RadioInterfaced>1</RadioInterfaced>"
        f"<NetworkedCompNr>0</NetworkedCompNr>"
        f"<IsRunQSO>0</IsRunQSO>"
        f"<StationName>{xml_esc(n.station)}</StationName>"
        f"<ID>{cid}</ID>"
        f"<IsClaimedQso>1</IsClaimedQso>"
        f"</contactinfo>"
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="UI fleet: multi WSJT-X + N1MM (3×6m → N1MM-50 on SSB-PC).")
    ap.add_argument("--group", default="224.0.0.73", help="WSJT-X multicast group")
    ap.add_argument("--iface", default="127.0.0.1",
                    help="multicast iface for WSJT-X (match server --iface)")
    ap.add_argument("--ttl", type=int, default=1)
    ap.add_argument("--n1mm-host", default="127.0.0.1",
                    help="unicast N1MM XML destination (server host)")
    ap.add_argument("--n1mm-port", type=int, default=12060)
    ap.add_argument("--period", type=float, default=8.0,
                    help="WSJT decode cycle seconds (default 8 for snappy UI)")
    ap.add_argument("--rate", type=int, default=3, help="decodes per cycle per instance")
    ap.add_argument("--n1mm-interval", type=float, default=2.0,
                    help="RadioInfo beacon interval (s)")
    ap.add_argument("--contact-every", type=int, default=4,
                    help="emit one contactinfo every N N1MM beacon rounds (per digital N1MM)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--six-only", action="store_true",
                    help="only 3×6m WSJT + N1MM-50 (minimal scenario)")
    ap.add_argument("--mode-switch-s", type=float, default=45.0,
                    help="seconds per FT8 vs SSB half-period for Roy 222/432 "
                         "(0 = stay digital forever)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    if args.six_only:
        wsjt = [
            SimWsjt("TRAILER-50-A", 50_313_000),
            SimWsjt("TRAILER-50-B", 50_313_000),
            SimWsjt("TV-50-C", 50_313_000),
        ]
        n1mms = [
            SimN1mm("N1MM-50", 50.0, "SSB-50-PC",
                    feeds=["TRAILER-50-A", "TRAILER-50-B", "TV-50-C"], ssb_pc=True),
        ]
    else:
        wsjt = default_wsjt()
        n1mms = default_n1mm()

    by_id = {w.id: w for w in wsjt}
    ports = sorted({w.port for w in wsjt})
    socks: dict[int, socket.socket] = {
        p: open_mcast_send(args.group, p, args.iface, args.ttl) for p in ports
    }
    n1mm_sock = open_n1mm_send()
    n1mm_dest = (args.n1mm_host, args.n1mm_port)

    def send_wsjt(inst: SimWsjt, payload: bytes) -> None:
        if not inst.live:
            return
        socks[inst.port].sendto(payload, (args.group, inst.port))

    def send_status(inst: SimWsjt) -> None:
        send_wsjt(inst, E.build_status(
            inst.id, inst.dial_hz, mode=inst.mode, de_call=MYCALL, de_grid=MYGRID,
            transmitting=inst.transmitting, decoding=not inst.transmitting,
            tx_enabled=inst.transmitting, config_name=inst.id,
            tx_message=(inst.tx_message or None) if inst.transmitting else None,
        ))

    def send_n1mm(xml: str) -> None:
        n1mm_sock.sendto(xml.encode("utf-8"), n1mm_dest)

    def digital_feeds_active(n: SimN1mm) -> bool:
        """Whether this N1MM should claim digital feeds (Roy SSB half → False)."""
        if not n.mode_switch_feeds:
            return bool(n.feeds)
        for fid in n.mode_switch_feeds:
            inst = by_id.get(fid)
            if inst is not None and inst.live:
                return True
        return False

    def radio_mode_for(n: SimN1mm) -> str:
        if n.prefer_ssb_radioinfo or not digital_feeds_active(n):
            return "USB"
        return "DIGI"

    print("UI fleet scenario (no RF)")
    print(f"  WSJT-X  {args.group} ports {ports} via {args.iface}")
    print(f"  N1MM    → {args.n1mm_host}:{args.n1mm_port} (unicast XML)")
    print()
    print("  6 m — three WSJT → N1MM-50 on SSB/CW PC")
    for w in wsjt:
        if w.band == "6m":
            print(f"    {w.id:18s}  {w.mode:6s}  {w.dial_hz/1e6:.3f}  :{w.port}")
    for n in n1mms:
        if n.station == "N1MM-50":
            print(f"    {n.station:18s}  @{n.host_label}  feeds {', '.join(n.feeds)}")
    print()
    print("  2 m — FT8 + MSK144 WSJT + separate SSB/CW PC")
    for w in wsjt:
        if w.band == "2m":
            print(f"    {w.id:18s}  {w.mode:6s}  {w.dial_hz/1e6:.3f}  :{w.port}")
    for n in n1mms:
        if "144" in n.station:
            feeds = ", ".join(n.feeds) if n.feeds else "(no WSJT — voice PC)"
            print(f"    {n.station:18s}  @{n.host_label}  {feeds}")
    print()
    print("  222 / 432 — one PC each, FT8 ↔ SSB/CW switch "
          f"(every {args.mode_switch_s:g}s)" if args.mode_switch_s > 0 else
          "  222 / 432 — one PC each (digital only; --mode-switch-s 0)")
    for w in wsjt:
        if w.mode_switch:
            print(f"    {w.id:18s}  {w.mode:6s}  mode_switch  :{w.port}")
    for n in n1mms:
        if n.station in ("N1MM-222", "N1MM-432"):
            print(f"    {n.station:18s}  @{n.host_label}  seat N1MM (same PC)")
    print()
    print("  Server: PYTHONPATH=src python3 -m wims.server.app "
          f"--iface {args.iface} --no-presence --no-seed")
    print("  Status: http://localhost:8787/status")
    print("  Ctrl-C to stop.\n")

    next_cycle = next_hb = next_n1mm = time.time()
    next_mode_switch = time.time() + max(0.0, args.mode_switch_s)
    cycle = 0
    n1mm_round = 0
    try:
        while True:
            rlist = list(socks.values())
            ready, _, _ = select.select(rlist, [], [], 0.2)
            now = time.time()

            # Roy 222/432: flip between FT8 (WSJT up) and SSB (WSJT silent, N1MM stays).
            if args.mode_switch_s > 0 and now >= next_mode_switch:
                next_mode_switch = now + args.mode_switch_s
                for inst in wsjt:
                    if not inst.mode_switch:
                        continue
                    inst.digital_active = not inst.digital_active
                    inst.transmitting = False
                    phase = "FT8/digital" if inst.digital_active else "SSB/CW"
                    print(f"  MODE  [{inst.id}] → {phase}")

            for sock in ready:
                try:
                    data, _addr = sock.recvfrom(65535)
                except OSError:
                    continue
                msg = M.parse(data)
                if msg is None or msg.type not in (M.REPLY, M.HALT_TX):
                    continue
                inst = by_id.get(msg.id)
                if not inst or not inst.live:
                    continue
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
                for inst in wsjt:
                    if inst.live:
                        send_wsjt(inst, E.build_heartbeat(
                            inst.id, version="2.7.0-ui-sim"))

            if now >= next_n1mm:
                next_n1mm = now + args.n1mm_interval
                n1mm_round += 1
                for n in n1mms:
                    send_n1mm(build_radioinfo(n, mode=radio_mode_for(n)))
                    if n1mm_round % 5 == 1:
                        send_n1mm(build_appinfo(n))
                    # contactinfo only when this N1MM is acting as digital logger.
                    if (n.feeds and digital_feeds_active(n)
                            and args.contact_every > 0
                            and n1mm_round % args.contact_every == 0):
                        call, grid = rng.choice(POOL)
                        send_n1mm(build_contactinfo(n, call, grid))
                        nfeed = len(n.feeds)
                        print(f"  N1MM {n.station} logged {call} on {n.band_mhz:g} "
                              f"({nfeed} WSJT feed)")

            if now >= next_cycle:
                next_cycle = now + args.period
                cycle += 1
                tms = now_ms_of_day(now)
                parts = []
                for inst in wsjt:
                    if not inst.live:
                        parts.append(f"{inst.id}:ssb")
                        continue
                    if inst.transmitting and now >= inst.tx_until:
                        inst.transmitting = False
                    send_status(inst)
                    if not inst.transmitting:
                        # MSK144 uses a different "mode" char in Decode; FT8 uses ~.
                        dmode = "~" if inst.mode == "FT8" else (
                            "`" if inst.mode == "MSK144" else "+")
                        for _ in range(args.rate):
                            send_wsjt(inst, E.build_decode(
                                inst.id, time_ms=tms, snr=rng.randint(-22, 8),
                                delta_time=round(rng.uniform(-0.3, 0.3), 1),
                                delta_frequency=rng.randint(200, 2800),
                                message=make_decode_message(rng),
                                mode=dmode,
                            ))
                    parts.append(f"{inst.id}:{'TX' if inst.transmitting else 'rx'}")
                if cycle % 2 == 0:
                    print(f"  cycle {cycle:3d}  " + "  ".join(parts[:5])
                          + (" …" if len(parts) > 5 else ""))
    except KeyboardInterrupt:
        print("\nfleet_ui stopped")
    finally:
        for s in socks.values():
            s.close()
        n1mm_sock.close()


if __name__ == "__main__":
    main()
