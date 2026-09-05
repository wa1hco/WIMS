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

"""WIMS solo launcher — the whole stack on one PC (`python -m wims.solo`).

For a single operator watching one FT8 frequency (any band, HF included) with
N1MM + WSJT-X on the same machine. It runs the WIMS server with single-PC defaults:

  * ingest + TX over the WSJT-X multicast group on loopback (127.0.0.1) — set WSJT-X
    'UDP Server' to 224.0.0.73:2237 with "Accept UDP requests" ON,
  * no fleet presence plane (one PC, no site-server election),
  * seed dupe/needed from your ordinary N1MM log (auto-found), so editing the log
    flips the roster between needed and dupe,
  * open the Operate console in your browser.

This is a thin wrapper: it assembles the equivalent `wims.server.app` arguments and
calls its `main()`, so there is exactly one server implementation. If your WSJT-X
sends UDP to a plain address (e.g. 127.0.0.1) rather than the multicast group, add
`--tx-host 127.0.0.1`.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wims.server import app as server  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m wims.solo",
        description="Run WIMS on this PC alongside your local WSJT-X + N1MM "
                    "(single operator, one FT8 frequency, any band).")
    ap.add_argument("--http-port", type=int, default=8787,
                    help="console HTTP port (default 8787)")
    ap.add_argument("--iface", default="127.0.0.1",
                    help="interface for WSJT-X multicast ingest/TX (default 127.0.0.1 = this PC)")
    ap.add_argument("--port", type=int, default=2237,
                    help="WSJT-X plane-A UDP port (default 2237 — all bands share "
                         "224.0.0.73:2237; use --rig-name to distinguish instances)")
    ap.add_argument("--tx-host", default=None,
                    help="send WSJT-X control to this unicast host instead of the multicast "
                         "group — use 127.0.0.1 if your WSJT-X 'UDP Server' is a plain address")
    ap.add_argument("--seed-db", default=None,
                    help="specific N1MM .s3db to seed dupe/needed from (default: auto-find)")
    ap.add_argument("--no-seed", action="store_true",
                    help="start with an empty log (every station reads as needed)")
    ap.add_argument("--enable-cq-freetext", action="store_true",
                    help="EXPERIMENTAL Call CQ via WSJT-X FreeText (unverified; off by default)")
    ap.add_argument("--no-open", action="store_true",
                    help="do not open the browser on start")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the WSJT-X / N1MM setup check printed before start")
    args = ap.parse_args()

    # Friendly single-PC setup check first, so the tester sees "is my setup OK?"
    # in plain language before the server output scrolls past.
    if not args.no_check:
        try:
            from wims.agent.report import build_report, format_report_solo
            print(format_report_solo(build_report(solo=True)))
            print()
        except Exception as e:
            print(f"(setup check skipped: {e})\n")

    # Translate to server args — solo = localhost, no fleet presence, one WSJT port.
    argv = [
        "--http-port", str(args.http_port),
        "--iface", args.iface,
        "--no-presence",
        "--ports", str(args.port),
    ]
    if args.tx_host:
        argv += ["--tx-host", args.tx_host]
    if args.seed_db:
        argv += ["--seed-db", args.seed_db]
    if args.no_seed:
        argv += ["--no-seed"]
    if args.enable_cq_freetext:
        argv += ["--enable-cq-freetext"]

    print(f"WIMS solo — single-PC console. In WSJT-X: Settings → Reporting → UDP Server "
          f"224.0.0.73:{args.port}, 'Accept UDP requests' ON.")

    if not args.no_open:
        url = f"http://localhost:{args.http_port}/"
        # Give the server a moment to bind before launching the browser.
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)),
                         daemon=True).start()

    sys.argv = ["wims.server.app"] + argv
    server.main()


if __name__ == "__main__":
    main()
