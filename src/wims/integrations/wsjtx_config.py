"""Read & validate a WSJT-X.ini for WIMS setup guidance (plan §3.3 / §3.14).

WSJT-X stores each named configuration's settings in `WSJT-X.ini`
(`%LOCALAPPDATA%\\WSJT-X\\` on Windows). The keys WIMS cares about for fleet
networking are the UDP reporting settings. This module extracts them per
configuration and flags the misconfigs that break a multi-host multicast fleet -
so the setup wizard can say "Roy-432's WSJT-X is on loopback, other vehicles
won't see it" instead of the operator reaching for Wireshark.

Run (on a WSJT-X host):
    python src/wims/integrations/wsjtx_config.py
    python src/wims/integrations/wsjtx_config.py "C:/path/to/WSJT-X.ini"
"""

from __future__ import annotations

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


@dataclass
class WsjtxConfig:
    name: str                      # configuration name, or "(active/default)"
    settings: dict[str, str] = field(default_factory=dict)

    def g(self, k: str, default: str = "") -> str:
        return self.settings.get(k, default)

    @property
    def is_multicast(self) -> bool:
        first = self.g("UDPServer").split(".")[0]
        return first.isdigit() and 224 <= int(first) <= 239

    @property
    def is_loopback_iface(self) -> bool:
        return self.g("UDPInterface").lower().startswith("loopback")


def default_ini_path() -> Path | None:
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "WSJT-X" / "WSJT-X.ini"
            if p.exists():
                return p
    return None


def parse_ini(path: str | Path) -> list[WsjtxConfig]:
    """Tolerant parse of WSJT-X.ini -> one WsjtxConfig per named configuration.

    Named-config keys look like `WSJTX_Flex_B\\Configuration\\UDPServer=...`;
    bare keys (`UDPServer=...`) belong to the currently active/default config.
    """
    configs: dict[str, WsjtxConfig] = {}
    for raw in Path(path).open(encoding="utf-8", errors="replace"):
        line = raw.rstrip("\r\n")
        if line.startswith("[") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if "\\Configuration\\" in key:
            name, sub = key.split("\\Configuration\\", 1)
        else:
            name, sub = "(active/default)", key
        if sub in _WANTED:
            configs.setdefault(name, WsjtxConfig(name)).settings[sub] = val
    return list(configs.values())


def validate(cfg: WsjtxConfig) -> list[tuple[str, str]]:
    """Return [(severity, message)] for a config, for the fleet-networking lens."""
    issues: list[tuple[str, str]] = []
    if not cfg.g("UDPServer"):
        issues.append(("error", "no UDP Server set - WSJT-X is not reporting over UDP"))
    elif not cfg.is_multicast:
        issues.append(("warn", f"UDP Server {cfg.g('UDPServer')} is unicast - only one app receives; "
                               "use multicast (e.g. 224.0.0.73) so N1MM + WIMS both get it"))
    if cfg.is_loopback_iface:
        issues.append(("error", "UDP interface is loopback - multicast stays on this PC; "
                                "other vehicles / central WIMS will NOT see it. Set it to the LAN NIC."))
    if cfg.g("AcceptUDPRequests").lower() != "true":
        issues.append(("warn", "Accept UDP requests is off - WIMS can read decodes but cannot send "
                               "Reply/Halt to control this instance"))
    return issues


def report(configs: list[WsjtxConfig]) -> str:
    out: list[str] = []
    groups = {c.g("UDPServer") + ":" + c.g("UDPServerPort") for c in configs if c.g("UDPServer")}
    for c in configs:
        out.append(f"[{c.name}]")
        out.append(f"  UDP  : {c.g('UDPServer','-')}:{c.g('UDPServerPort','-')} "
                   f"iface={c.g('UDPInterface','-')} ttl={c.g('UDPTTL','-')} "
                   f"acceptUDP={c.g('AcceptUDPRequests','-')}")
        out.append(f"  Stn  : {c.g('MyCall','-')} / {c.g('MyGrid','-')}")
        for sev, msg in validate(c):
            out.append(f"  {'!!' if sev == 'error' else ' ~'} {msg}")
    if len(groups) > 1:
        out.append("")
        out.append(f"!! configs use DIFFERENT groups/ports {sorted(groups)} - "
                   "all fleet instances should share one multicast group:port")
    return "\n".join(out)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_ini_path()
    if not path or not Path(path).exists():
        sys.exit("WSJT-X.ini not found (pass its path explicitly)")
    print(f"WSJT-X config: {path}\n")
    print(report(parse_ini(path)))


if __name__ == "__main__":
    main()
