# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Test log agent: WSJT-X multicast Logged QSO → local N1MM.

Run this on the N1MM PC (e.g. VM hostname wims-test-50). It joins
224.0.0.73:2237, keeps Logged ADIF / QSO Logged for the pinned band,
and delivers the Log envelope to N1MM on localhost.

Default today: UDP 127.0.0.1:2333. Preferred direction (2026-08-29):
TCP 127.0.0.1:52001 (N1MM "JTDX/Others") — see
docs/decisions/2026-08-22-remote-n1mm-logging.md. Remote UDP 2333 is
untrusted (LAN packets arrive; inserts often only from loopback).

Band pin: --band, else trailing -50 / -144 / … on the hostname
(wims-test-50 → 6m). Fail closed if no pin.

  python testbed/log_agent.py --dry-run
  python testbed/log_agent.py
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wims.core.bands import band_label  # noqa: E402
from wims.udp import messages as M  # noqa: E402
from wims.udp.sink import open_socket  # noqa: E402

GROUP = "224.0.0.73"
PORT = 2237
N1MM_ADIF = ("127.0.0.1", 2333)

# Hostname suffix MHz → same table as fleet seats (TRAILER-50, wims-test-50).
_MHZ_PIN = {
    50: "6m", 144: "2m", 222: "1.25m", 432: "70cm",
    902: "33cm", 1296: "23cm",
}

_ADIF_BAND = re.compile(r"<BAND:(\d+)>([^<]+)", re.I)
_ADIF_FREQ = re.compile(r"<FREQ:(\d+)>([^<]+)", re.I)
_ADIF_CALL = re.compile(r"<CALL:(\d+)>([^<]+)", re.I)


def pin_from_hostname(name: str) -> str | None:
    host = name.split(".")[0]
    m = re.search(r"(?:^|[-_])(\d+)$", host)
    if not m:
        return None
    return _MHZ_PIN.get(int(m.group(1)))


def adif_band(adif: str) -> str | None:
    m = _ADIF_BAND.search(adif or "")
    if m:
        key = m.group(2).strip().lower()
        aliases = {"6m": "6m", "50": "6m", "2m": "2m", "144": "2m",
                   "1.25m": "1.25m", "222": "1.25m", "70cm": "70cm",
                   "432": "70cm", "33cm": "33cm", "902": "33cm",
                   "23cm": "23cm", "1296": "23cm"}
        return aliases.get(key)
    m = _ADIF_FREQ.search(adif or "")
    if m:
        try:
            mhz = float(m.group(2).strip())
        except ValueError:
            return None
        return band_label(int(mhz * 1_000_000))
    return None


def wrap_adif(adif: str) -> bytes:
    text = (adif or "").strip()
    if "<eor>" not in text.lower():
        text += " <eor>"
    return text.encode("ascii", "replace")


def qso_to_adif(msg: M.QSOLogged) -> str:
    mhz = (msg.tx_frequency or 0) / 1e6
    band = band_label(msg.tx_frequency or 0)
    parts = [
        f"<CALL:{len(msg.dx_call or '')}>{msg.dx_call or ''}",
        f"<GRIDSQUARE:{len(msg.dx_grid or '')}>{msg.dx_grid or ''}",
        f"<MODE:{len(msg.mode or '')}>{msg.mode or ''}",
        f"<FREQ:{len(f'{mhz:.6f}')}>{mhz:.6f}",
        f"<BAND:{len(band)}>{band}",
        f"<STATION_CALLSIGN:{len(msg.my_call or '')}>{msg.my_call or ''}",
        f"<MY_GRIDSQUARE:{len(msg.my_grid or '')}>{msg.my_grid or ''}",
        f"<RST_SENT:{len(msg.report_sent or '')}>{msg.report_sent or ''}",
        f"<RST_RCVD:{len(msg.report_received or '')}>{msg.report_received or ''}",
    ]
    return "".join(parts) + " <eor>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", default=GROUP)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--iface", default="0.0.0.0",
                    help="LAN iface to join multicast (default: auto)")
    ap.add_argument("--band", default=None,
                    help="pin this band label (6m, 2m, …); default from hostname")
    ap.add_argument("--n1mm", default="127.0.0.1:2333")
    ap.add_argument("--dry-run", action="store_true",
                    help="print matching QSOs, do not send to N1MM")
    args = ap.parse_args(argv)

    host = socket.gethostname()
    pin = args.band or os.environ.get("WIMS_BAND") or pin_from_hostname(host)
    if isinstance(pin, str):
        pin = pin.strip() or None
    if not pin:
        print(
            f"log-agent: no band pin (hostname={host!r}).\n"
            f"  Pass --band 6m   or set WIMS_BAND=6m\n"
            f"  or name this PC ...-50 / ...-144 / ...-222 / ...-432",
            file=sys.stderr,
        )
        return 2

    nhost, _, nport = args.n1mm.partition(":")
    n1mm = (nhost or "127.0.0.1", int(nport or "2333"))
    sock = open_socket(args.iface, args.port, args.group)
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # ASCII-only prints: Windows consoles often use cp1252 and crash on arrows.
    dest = "DRY-RUN" if args.dry_run else f"-> {args.n1mm}"
    print(f"log-agent: host={host}  pin={pin}  join {args.group}:{args.port}  {dest}")
    print("          N1MM WSJT UDP reader must be OFF on this PC (no 2237).")
    seen = set()
    n_fwd = n_drop = 0
    while True:
        data, addr = sock.recvfrom(65535)
        msg = M.parse(data)
        if msg is None:
            continue
        adif = None
        call = None
        qband = None
        if isinstance(msg, M.LoggedADIF) and msg.adif:
            adif = msg.adif
            qband = adif_band(adif)
            m = _ADIF_CALL.search(adif)
            call = m.group(2) if m else msg.id
        elif isinstance(msg, M.QSOLogged):
            qband = band_label(msg.tx_frequency or 0)
            call = msg.dx_call
            adif = qso_to_adif(msg)
        else:
            continue
        if qband != pin:
            n_drop += 1
            print(f"{time.strftime('%H:%M:%S')}  DROP {msg.id} {call} "
                  f"band={qband} (want {pin})  from {addr[0]}")
            continue
        key = (msg.id, call, qband)
        if key in seen:
            continue
        seen.add(key)
        payload = wrap_adif(adif)
        n_fwd += 1
        print(f"{time.strftime('%H:%M:%S')}  FWD  {msg.id} {call} {qband}  "
              f"{len(payload)} B  ({n_fwd} fwd / {n_drop} drop)")
        if not args.dry_run:
            out.sendto(payload, n1mm)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nlog-agent: quit")
        raise SystemExit(0)
