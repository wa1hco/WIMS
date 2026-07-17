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

"""N1MM+ External UDP broadcast listener (plan §1.3 / §3.6).

N1MM broadcasts XML datagrams (one XML document per packet) to its configured
destination (default 127.0.0.1:12060) when External Broadcasts are enabled. Unlike
WSJT-X's binary protocol these are plain UTF-8 XML, e.g. <contactinfo>, <spot>,
<lookupinfo>, <RadioInfo>, <dynamicresults>.

This listener captures them to captures/, prints the root element + key fields, and
**flags any field whose name hints at dupe / multiplier / needed status** — the
make-or-break question for the §3.6 spot round-trip (can WIMS read N1MM's
contest-rules verdict instead of reimplementing it?).

Enable in N1MM: Config -> "Configure Ports, Telnet Address, Other..." -> "Broadcast
Data" tab -> tick Contacts, Spots, Radio, and "Lookup" / External Lookup -> destination
either this host's LAN IP:12060 (unicast) or a multicast group e.g. 224.0.0.73:12060
(multi-host fleets) -> OK. Then type a call into the Entry Window (lookup) and log a
test QSO (contact) to generate traffic.

Run (from the repo root):
    python src/wims/integrations/n1mm/listener.py --port 12060
    # multicast (same group as WSJT-X is fine; port differs):
    python src/wims/integrations/n1mm/listener.py --port 12060 \\
        --multicast 224.0.0.73 --host 192.168.1.119
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# Field-name substrings that would answer the round-trip question. ("worked" is
# omitted: it false-matches "networked" in e.g. NetworkedCompNr.)
_INTERESTING = ("dupe", "mult", "needed", "points", "iscontest", "newmult", "newval")


def flatten(elem: ET.Element, prefix: str = "") -> dict[str, str]:
    """Flatten an XML element's leaf text into {tag-path: text}."""
    out: dict[str, str] = {}
    children = list(elem)
    if not children and elem.text and elem.text.strip():
        out[prefix or elem.tag] = elem.text.strip()
    for child in children:
        path = f"{prefix}/{child.tag}" if prefix else child.tag
        out.update(flatten(child, path))
    return out


def summarize(text: str) -> tuple[str, dict[str, str], list[str]]:
    """Return (root_tag, flattened_fields, flagged_field_names)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "<unparsable>", {}, []
    fields = flatten(root)
    flagged = [k for k in fields if any(s in k.lower() for s in _INTERESTING)]
    return root.tag, fields, flagged


def main() -> None:
    ap = argparse.ArgumentParser(description="N1MM+ External UDP broadcast listener.")
    ap.add_argument("--host", default="0.0.0.0",
                    help="local interface for bind / multicast join (default 0.0.0.0; "
                         "use the LAN IP when joining a multicast group)")
    ap.add_argument("--port", type=int, default=12060, help="N1MM broadcast port (default 12060)")
    ap.add_argument("--multicast", default=None,
                    help="join this multicast group (e.g. 224.0.0.73) for multi-host N1MM")
    ap.add_argument("--out", default="captures", help="output directory (default captures/)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"n1mm-{stamp}.jsonl"

    if args.multicast:
        from wims.udp.sink import open_socket
        sock = open_socket(args.host, args.port, args.multicast)
        where = f"{args.multicast} (multicast via {args.host})"
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.host, args.port))
        where = args.host

    print(f"listening for N1MM XML on {where}:{args.port}  ->  {out_path}")
    dest = f"{args.multicast or 'HOST_IP'}:12060"
    print(f"Enable N1MM Broadcast Data to {dest}, "
          "then type a call into the Entry Window and log a test QSO.")
    print("Ctrl-C to stop.\n")

    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                ts = time.time()
                text = data.decode("utf-8", "replace")
                root, fields, flagged = summarize(text)
                f.write(json.dumps({"ts": ts, "src": f"{addr[0]}:{addr[1]}",
                                    "len": len(data), "root": root, "text": text}) + "\n")
                f.flush()
                count += 1
                print(f"[{count:4d}] {addr[0]:<15} {len(data):4d}B  <{root}>")
                # Show a few identifying fields for context.
                for k in ("call", "dxcall", "mycall", "band", "mode", "contestname"):
                    for fk, fv in fields.items():
                        if fk.lower().endswith(k):
                            print(f"        {fk} = {fv}")
                            break
                if flagged:
                    print("   >>> DUPE/MULT FIELDS FOUND:")
                    for k in flagged:
                        print(f"        {k} = {fields[k]}")
                else:
                    print("        (no dupe/mult-looking fields in this message)")
        except KeyboardInterrupt:
            print(f"\nstopped — {count} datagrams written to {out_path}")


if __name__ == "__main__":
    main()
