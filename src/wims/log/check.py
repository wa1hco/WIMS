# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scoped config checks for the log agent (N1MM PC only).

Primary band source is live N1MM RadioInfo (see 2026-08-29-n1mm-live-band.md).
ASCII-only messages (Windows cp1252 consoles).
"""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from typing import Callable

# Hostname suffix MHz -> band label (TRAILER-50, wims-test-50) — lab bootstrap only.
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
    """Optional expect-band / lab override — not the live filter source."""
    env = env if env is not None else os.environ
    pin = (band or env.get("WIMS_BAND") or "").strip() or None
    if not pin:
        pin = pin_from_hostname(hostname or socket.gethostname())
    return pin


def probe_tcp(host: str, port: int, timeout: float = 0.4) -> bool:
    """True if N1MM's JTDX/Others TCP port accepts a connection.

    Close with FIN (shutdown) rather than a Windows RST — N1MM's
    LoggingTCPListening treats an abortive close as a popup error.
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass
    return True


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
    live_band: str | None,
    expect_band: str | None = None,
    radio_port: int = 12060,
    radio_group: str | None = "224.0.0.73",
    group: str = "224.0.0.73",
    mcast_port: int = 2237,
    delivery_host: str = "127.0.0.1",
    delivery_udp_port: int = 2333,
    delivery_tcp_port: int = 52001,
    joined: bool | None = None,
    dry_run: bool = False,
    tcp_probe: Callable[[str, int], bool] | None = None,
    # Backward-compat alias used by older callers/tests.
    pin: str | None = None,
) -> CheckReport:
    """Build a scoped check report for the log agent."""
    if live_band is None and pin is not None:
        live_band = pin
    rep = CheckReport(pin=live_band)
    tcp_probe = tcp_probe or probe_tcp

    radio_dest = f"{radio_group}:{radio_port}" if radio_group else f"this host:{radio_port}"
    if not live_band:
        rep.items.append(CheckItem(
            "band", "warn",
            f"Waiting for N1MM RadioInfo on UDP :{radio_port}. "
            f"Enable Config > Broadcast Data > Radio to {radio_dest}. "
            f"QSOs are dropped until a band is heard.",
        ))
    elif live_band not in VALID_PINS:
        rep.items.append(CheckItem(
            "band", "warn",
            f"N1MM band {live_band!r} is unusual (expected 6m/2m/1.25m/70cm/33cm/23cm).",
        ))
    else:
        rep.items.append(CheckItem(
            "band", "ok",
            f"Filtering Logged QSOs for {live_band} (from N1MM RadioInfo).",
        ))

    if expect_band and live_band and expect_band != live_band:
        rep.items.append(CheckItem(
            "expect", "warn",
            f"Expected band {expect_band} but N1MM reports {live_band}.",
        ))

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
                f"(preferred JTDX/Others path). Log agent sends here first.",
            ))
        else:
            rep.items.append(CheckItem(
                "delivery", "warn",
                f"TCP {delivery_host}:{delivery_tcp_port} not open — "
                f"UDP {delivery_host}:{delivery_udp_port} is fallback only "
                f"(sendto can 'succeed' with no N1MM insert). "
                f"Enable Configurer > WSJT/JTDX Setup > JTDX/Others TCP, then restart N1MM.",
            ))

    rep.items.append(_n1mm_presence())
    rep.items.append(_wsjt_udp_reader_conflict())
    return rep


def _wsjt_udp_reader_conflict() -> CheckItem:
    """Warn only when Logger.ini says the fleet UDP reader is ON."""
    try:
        from wims.agent.n1mm_probe import probe_wsjt_udp_reader
        info = probe_wsjt_udp_reader()
    except Exception as e:
        return CheckItem(
            "conflict", "warn",
            f"Could not read N1MM Logger.ini for WSJT UDP reader ({e}).",
        )
    if not info.get("found_ini"):
        # Stay quiet — do not nag when we cannot prove a conflict.
        return CheckItem(
            "conflict", "ok",
            "N1MM Logger.ini not found here; skipped WSJT UDP reader check.",
        )
    if info.get("fleet_conflict"):
        return CheckItem("conflict", "warn", info.get("summary") or "WSJT UDP reader conflict.")
    # Off, or enabled only on 2333 / non-fleet — not a yellow warning.
    return CheckItem(
        "conflict", "ok",
        info.get("summary") or "N1MM WSJT/JTDX UDP reader OK for log agent.",
    )
