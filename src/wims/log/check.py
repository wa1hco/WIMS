# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scoped config checks for the log helper (N1MM PC only).

Checks only what this helper talks to: band pin, multicast join target,
local N1MM delivery (TCP 52001 preferred / UDP 2333), and light N1MM presence.
ASCII-only messages (Windows cp1252 consoles).
"""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from typing import Callable

# Hostname suffix MHz -> band label (TRAILER-50, wims-test-50).
_MHZ_PIN = {
    50: "6m",
    144: "2m",
    222: "1.25m",
    432: "70cm",
    902: "33cm",
    1296: "23cm",
}

VALID_PINS = frozenset(_MHZ_PIN.values())


@dataclass(frozen=True)
class CheckItem:
    id: str
    severity: str  # ok | warn | error
    message: str


@dataclass
class CheckReport:
    items: list[CheckItem] = field(default_factory=list)
    pin: str | None = None

    @property
    def severity(self) -> str:
        order = {"ok": 0, "warn": 1, "error": 2}
        worst = "ok"
        for it in self.items:
            if order.get(it.severity, 0) > order.get(worst, 0):
                worst = it.severity
        return worst

    def lines(self) -> list[str]:
        mark = {"ok": "[OK]", "warn": "[! ]", "error": "[XX]"}
        return [
            f"{mark.get(it.severity, '[??]')} {it.message}"
            for it in self.items
        ]


def pin_from_hostname(name: str) -> str | None:
    host = name.split(".")[0]
    m = re.search(r"(?:^|[-_])(\d+)$", host)
    if not m:
        return None
    return _MHZ_PIN.get(int(m.group(1)))


def resolve_pin(
    band: str | None = None,
    *,
    env: dict[str, str] | None = None,
    hostname: str | None = None,
) -> str | None:
    env = env if env is not None else os.environ
    pin = (band or env.get("WIMS_BAND") or "").strip() or None
    if not pin:
        pin = pin_from_hostname(hostname or socket.gethostname())
    if pin and pin not in VALID_PINS:
        # Allow unknown labels but normalize common aliases later if needed.
        pass
    return pin


def probe_tcp(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _n1mm_presence() -> CheckItem:
    try:
        from wims.agent.n1mm_probe import probe_n1mm
        from wims.agent.report import _process_running
        info = probe_n1mm()
        running = _process_running(
            ("n1mmlogger.net.exe", "n1mmlogger.net", "n1mm logger+.exe",
             "n1mmlogger+.exe", "n1mm logger.exe"),
            substrings=("n1mmlogger",),
        )
    except Exception as e:
        return CheckItem(
            "n1mm", "warn",
            f"N1MM probe failed ({e}); delivery may still work if Logger is open.",
        )
    if running:
        return CheckItem("n1mm", "ok", "N1MM looks running on this PC.")
    if info.get("found") or info.get("open_databases"):
        return CheckItem(
            "n1mm", "warn",
            "N1MM data found but process not detected — start Logger+.",
        )
    return CheckItem(
        "n1mm", "warn",
        "N1MM not detected on this PC. Start Logger+ before expecting inserts.",
    )


def run_checks(
    *,
    pin: str | None,
    group: str = "224.0.0.73",
    mcast_port: int = 2237,
    delivery_host: str = "127.0.0.1",
    delivery_udp_port: int = 2333,
    delivery_tcp_port: int = 52001,
    joined: bool | None = None,
    dry_run: bool = False,
    tcp_probe: Callable[[str, int], bool] | None = None,
) -> CheckReport:
    """Build a scoped check report for the log helper."""
    rep = CheckReport(pin=pin)
    tcp_probe = tcp_probe or probe_tcp

    if not pin:
        rep.items.append(CheckItem(
            "band", "error",
            "No band pin. Pass --band 6m, set WIMS_BAND, or name PC ...-50.",
        ))
    elif pin not in VALID_PINS:
        rep.items.append(CheckItem(
            "band", "warn",
            f"Band pin {pin!r} is unusual (expected 6m/2m/1.25m/70cm/33cm/23cm).",
        ))
    else:
        rep.items.append(CheckItem("band", "ok", f"Band pin {pin}."))

    if joined is True:
        rep.items.append(CheckItem(
            "mcast", "ok",
            f"Joined multicast {group}:{mcast_port}.",
        ))
    elif joined is False:
        rep.items.append(CheckItem(
            "mcast", "error",
            f"Multicast join failed for {group}:{mcast_port}.",
        ))
    else:
        rep.items.append(CheckItem(
            "mcast", "warn",
            f"Multicast {group}:{mcast_port} not joined yet.",
        ))

    if dry_run:
        rep.items.append(CheckItem(
            "delivery", "ok",
            "Dry-run: not sending to N1MM.",
        ))
    else:
        tcp_ok = tcp_probe(delivery_host, delivery_tcp_port)
        if tcp_ok:
            rep.items.append(CheckItem(
                "delivery", "ok",
                f"N1MM TCP {delivery_host}:{delivery_tcp_port} accepts connections "
                f"(preferred JTDX/Others path). UDP {delivery_udp_port} still used "
                f"until TCP send lands.",
            ))
        else:
            rep.items.append(CheckItem(
                "delivery", "warn",
                f"TCP {delivery_host}:{delivery_tcp_port} not open. "
                f"Using UDP {delivery_host}:{delivery_udp_port} for now. "
                f"In N1MM enable Config > Broadcast Data > JTDX/Others (TCP 52001).",
            ))

    rep.items.append(_n1mm_presence())
    rep.items.append(CheckItem(
        "conflict", "warn",
        "Turn OFF N1MM's WSJT UDP reader on this PC (do not bind fleet :2237 here).",
    ))
    return rep
