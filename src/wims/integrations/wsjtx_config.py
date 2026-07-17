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

"""Read & validate a WSJT-X.ini for WIMS setup guidance (plan §3.3 / §3.14 / networking §12).

WSJT-X stores each named configuration's settings in `WSJT-X.ini`
(`%LOCALAPPDATA%\\WSJT-X\\` on Windows; `~/.config/WSJT-X*.ini` on Linux, including
`WSJT-X - <rig-name>.ini` for `--rig-name` instances). The keys WIMS cares about for
fleet networking are the UDP reporting settings — especially:

  * UDP Server = multicast group (e.g. 224.0.0.73), not 127.0.0.1
  * **Outgoing interface = contest LAN NIC** (never blank / @Invalid / loopback)

A multicast *address* with a missing/invalid interface is a common silent failure:
the instance decodes locally but WIMS (and other hosts) never see Heartbeat/Status/
Decode. The setup wizard and continuous readiness board must flag this in plain
language.

Run (on a WSJT-X host):
    python src/wims/integrations/wsjtx_config.py
    python src/wims/integrations/wsjtx_config.py "C:/path/to/WSJT-X.ini"
    python src/wims/integrations/wsjtx_config.py --all   # every known ini on this host
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The reporting/UDP keys we extract (WSJT-X stores many others we ignore).
_WANTED = {
    "UDPServer", "UDPServerPort", "UDPInterface", "UDPTTL",
    "AcceptUDPRequests", "BroadcastToN1MM", "N1MMServer", "N1MMServerPort",
    "MyCall", "MyGrid",
}

# Qt/WSJT-X "no interface selected" markers we have seen in the wild.
_INVALID_IFACE = frozenset({
    "", "@invalid()", "@invalid", "none", "n/a", "0.0.0.0",
})


@dataclass
class WsjtxConfig:
    name: str                      # configuration name, or "(active/default)"
    settings: dict[str, str] = field(default_factory=dict)
    source: str = ""               # path of the .ini this came from (optional)

    def g(self, k: str, default: str = "") -> str:
        return self.settings.get(k, default)

    @property
    def is_multicast(self) -> bool:
        first = self.g("UDPServer").split(".")[0]
        return first.isdigit() and 224 <= int(first) <= 239

    @property
    def is_loopback_server(self) -> bool:
        s = self.g("UDPServer").strip().lower()
        return s in ("127.0.0.1", "localhost", "::1")

    @property
    def is_loopback_iface(self) -> bool:
        iface = self.g("UDPInterface").strip().lower()
        return iface.startswith("loopback") or iface in ("127.0.0.1", "lo", "lo0")

    @property
    def iface_unset(self) -> bool:
        """True when WSJT-X has no usable outgoing interface selection."""
        iface = self.g("UDPInterface").strip().lower()
        return iface in _INVALID_IFACE or iface.startswith("@invalid")


def default_ini_path() -> Path | None:
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "WSJT-X" / "WSJT-X.ini"
            if p.exists():
                return p
    # Linux / XDG — default config (no --rig-name)
    p = Path.home() / ".config" / "WSJT-X.ini"
    if p.exists():
        return p
    return None


def discover_ini_paths() -> list[Path]:
    """All WSJT-X.ini files this host is likely to use (Windows + Linux + rig-name)."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp in seen or not p.is_file():
            return
        seen.add(rp)
        found.append(p)

    d = default_ini_path()
    if d:
        add(d)
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            root = Path(base) / "WSJT-X"
            if root.is_dir():
                for p in sorted(root.glob("**/WSJT-X*.ini")):
                    add(p)
    cfg = Path.home() / ".config"
    if cfg.is_dir():
        for p in sorted(cfg.glob("WSJT-X*.ini")):
            add(p)
        # Symlinked share dirs sometimes hold copies; prefer .config names above.
    return found


def parse_ini(path: str | Path) -> list[WsjtxConfig]:
    """Tolerant parse of WSJT-X.ini -> one WsjtxConfig per named configuration.

    Named-config keys look like `WSJTX_Flex_B\\Configuration\\UDPServer=...`;
    bare keys (`UDPServer=...`) belong to the currently active/default config.
    On Linux, each `--rig-name` instance usually has its own file
    (`WSJT-X - flex.ini`) with bare keys only.
    """
    path = Path(path)
    configs: dict[str, WsjtxConfig] = {}
    for raw in path.open(encoding="utf-8", errors="replace"):
        line = raw.rstrip("\r\n")
        if line.startswith("[") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if "\\Configuration\\" in key:
            name, sub = key.split("\\Configuration\\", 1)
        else:
            # Prefer a stable name from the filename for --rig-name instances.
            stem = path.stem  # e.g. "WSJT-X - flex"
            if stem.startswith("WSJT-X - "):
                name = stem[len("WSJT-X - "):]
            elif stem == "WSJT-X":
                name = "(active/default)"
            else:
                name = "(active/default)"
            sub = key
        if sub in _WANTED:
            c = configs.setdefault(name, WsjtxConfig(name, source=str(path)))
            c.settings[sub] = val
            c.source = str(path)
    return list(configs.values())


def validate(cfg: WsjtxConfig, *, fleet: bool = True) -> list[tuple[str, str]]:
    """Return [(severity, message)] for a config, for the fleet-networking lens.

    `fleet=True` (default) treats loopback-only / unset LAN interface as **errors** —
    the contest multi-host and multi-consumer setup. Set `fleet=False` for a
    single-PC lab where 127.0.0.1 unicast to a local WIMS is intentional.
    """
    issues: list[tuple[str, str]] = []
    server = cfg.g("UDPServer")
    iface = cfg.g("UDPInterface")

    if not server:
        issues.append(("error", "no UDP Server set - WSJT-X is not reporting over UDP"))
        return issues

    if cfg.is_loopback_server:
        sev = "error" if fleet else "warn"
        issues.append((
            sev,
            f"UDP Server is {server} (loopback) - only this PC receives; "
            "set UDP Server to the fleet multicast (e.g. 224.0.0.73) and "
            "Outgoing interface to the contest LAN NIC so WIMS/N1MM on the LAN see it",
        ))
    elif not cfg.is_multicast:
        issues.append((
            "warn",
            f"UDP Server {server} is unicast - only one app receives; "
            "use multicast (e.g. 224.0.0.73) so N1MM + WIMS + GridTracker all get it",
        ))

    # Outgoing interface — first-class requirement (networking §4 / §12).
    if cfg.is_loopback_iface:
        issues.append((
            "error",
            "UDP Outgoing interface is loopback - traffic stays on this PC; "
            "other vehicles / central WIMS will NOT see it. "
            "Settings → Reporting → set interface to the contest LAN NIC",
        ))
    elif cfg.iface_unset:
        if cfg.is_multicast or fleet:
            issues.append((
                "error",
                "UDP Outgoing interface is blank/invalid (@Invalid) - "
                "multicast/UDP often never reaches WIMS even when this instance decodes. "
                "Settings → Reporting → select the contest LAN NIC explicitly "
                f"(current value: {iface or '(empty)'})",
            ))
        else:
            issues.append((
                "warn",
                "UDP Outgoing interface is unset - set it to the LAN NIC before multi-host use",
            ))
    elif fleet and cfg.is_multicast:
        # Has a non-loopback value — still remind it must be the contest LAN, not Wi‑Fi.
        issues.append((
            "info",
            f"UDP Outgoing interface is '{iface}' - confirm this is the contest LAN NIC "
            "(not Wi‑Fi / VPN / Starlink) for multi-vehicle multicast",
        ))

    if cfg.g("AcceptUDPRequests").lower() != "true":
        issues.append((
            "warn",
            "Accept UDP requests is off - WIMS can read decodes but cannot send "
            "Reply/Halt to control this instance",
        ))

    port = cfg.g("UDPServerPort")
    if port and port != "2237" and fleet:
        issues.append((
            "info",
            f"UDP port is {port} (not 2237) - OK if this matches the band stream in the "
            "contest profile / networking map; WIMS must join this port",
        ))

    return issues


def report(configs: list[WsjtxConfig], *, fleet: bool = True) -> str:
    out: list[str] = []
    groups = {
        c.g("UDPServer") + ":" + c.g("UDPServerPort")
        for c in configs if c.g("UDPServer")
    }
    for c in configs:
        src = f"  ({c.source})" if c.source else ""
        out.append(f"[{c.name}]{src}")
        out.append(
            f"  UDP  : {c.g('UDPServer', '-')}:{c.g('UDPServerPort', '-')} "
            f"iface={c.g('UDPInterface', '-') or '(empty)'} "
            f"ttl={c.g('UDPTTL', '-')} acceptUDP={c.g('AcceptUDPRequests', '-')}"
        )
        out.append(f"  Stn  : {c.g('MyCall', '-')} / {c.g('MyGrid', '-')}")
        for sev, msg in validate(c, fleet=fleet):
            mark = {"error": "!!", "warn": " ~", "info": "  "}.get(sev, "  ")
            out.append(f"  {mark} [{sev}] {msg}")
    if len(groups) > 1:
        out.append("")
        out.append(
            f"!! configs use DIFFERENT groups/ports {sorted(groups)} - "
            "for a single-band lab they must match; for multi-band fleet they must "
            "match the per-band map (networking.md) and each N1MM reader"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate WSJT-X UDP settings for WIMS fleet use.")
    ap.add_argument("path", nargs="?", help="path to WSJT-X.ini (default: discover)")
    ap.add_argument(
        "--all", action="store_true",
        help="validate every WSJT-X*.ini found on this host",
    )
    ap.add_argument(
        "--lab", action="store_true",
        help="lab mode: loopback unicast is a warning, not an error",
    )
    args = ap.parse_args()
    fleet = not args.lab

    paths: list[Path]
    if args.path:
        paths = [Path(args.path)]
    elif args.all:
        paths = discover_ini_paths()
        if not paths:
            sys.exit("no WSJT-X.ini found on this host")
    else:
        d = default_ini_path()
        if not d:
            # Fall back to all discovered named instances (Linux multi --rig-name).
            paths = discover_ini_paths()
            if not paths:
                sys.exit("WSJT-X.ini not found (pass its path explicitly or use --all)")
        else:
            paths = [d]
            # If only the default exists, still OK; if named instances exist too, include them.
            extra = [p for p in discover_ini_paths() if p.resolve() != d.resolve()]
            if extra:
                paths = discover_ini_paths()

    fleet_label = "lab (loopback tolerated)" if not fleet else "fleet (LAN required)"
    print(f"WIMS WSJT-X config check  [{fleet_label}]\n")
    all_cfgs: list[WsjtxConfig] = []
    for p in paths:
        if not p.exists():
            print(f"(missing) {p}", file=sys.stderr)
            continue
        print(f"--- {p} ---")
        cfgs = parse_ini(p)
        all_cfgs.extend(cfgs)
        print(report(cfgs, fleet=fleet))
        print()

    errors = sum(1 for c in all_cfgs for sev, _ in validate(c, fleet=fleet) if sev == "error")
    if errors:
        print(f"{errors} error(s) — fix before relying on WIMS multi-host ingest.")
        sys.exit(1)


if __name__ == "__main__":
    main()
