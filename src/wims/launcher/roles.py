# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Role catalog for the desktop launcher (pure data + argv builders).

Contest-first catalog: docs/decisions/2026-08-29-contest-pc-roles.md
Solo is lab-only (advanced), not a primary contest bring-up path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


BAND_PORTS: tuple[tuple[str, int], ...] = (
    ("50 MHz", 2237),
    ("144 MHz", 2238),
    ("222 MHz", 2239),
    ("432 MHz", 2241),
    ("902 MHz", 2242),
    ("1296 MHz", 2243),
)

DEFAULT_SOLO_PORT = 2237
DEFAULT_HTTP_PORT = 8787


@dataclass(frozen=True)
class Role:
    """One startable WIMS role shown in the launcher."""

    id: str
    title: str
    summary: str
    tooltip: str
    button: str
    recommended: bool = False
    advanced: bool = False
    # True = long-running process managed by the launcher (Stop button).
    long_running: bool = True
    # Builds python -m … argv *after* the interpreter (no python.exe).
    build_argv: Callable[..., list[str]] = lambda **_: []


def _solo_argv(*, port: int = DEFAULT_SOLO_PORT, no_open: bool = False) -> list[str]:
    argv = ["-m", "wims.solo", "--port", str(port), "--no-check"]
    if no_open:
        argv.append("--no-open")
    return argv


def _server_argv() -> list[str]:
    return ["-m", "wims.server.app"]


def _wsjt_check_argv() -> list[str]:
    # Seat config audit for local WSJT-X (+ N1MM if present). Not --solo contest path.
    return ["-m", "wims.agent", "--once"]


def _wsjt_agent_argv() -> list[str]:
    # Local UI http://127.0.0.1:8790/ — pin server when WIMS_SERVER unset so export
    # has a default on single-site lab boxes; discovery still updates presence.
    argv = ["-m", "wims.agent", "--daemon", "--local-port", "8790"]
    if not os.environ.get("WIMS_SERVER"):
        argv += ["--server", "http://127.0.0.1:8787"]
    return argv


def _log_agent_argv() -> list[str]:
    # Repo-root relative; launcher sets cwd to repo.
    return ["testbed/log_agent.py"]


def _key_agent_argv() -> list[str]:
    return ["-m", "wims.key", "selftest"]


ROLES: tuple[Role, ...] = (
    Role(
        id="server",
        title="Site server",
        summary="One per contest LAN: roster, inventory, Work/Halt, Status/Setup. "
                "May run on the same PC as an N1MM seat.",
        tooltip=(
            "Central WIMS console for the fleet.\n\n"
            "Joins the fleet WSJT UDP stream(s), seeds/mirrors the log, and serves "
            "Operate / Status / Setup in the browser.\n\n"
            "Typical: one server for the site. It can share a box with N1MM + "
            "log/key agents. Seats open http://<server>:8787/ — they do not each "
            "run another server."
        ),
        button="Start server",
        recommended=True,
        long_running=True,
        build_argv=lambda **_: _server_argv(),
    ),
    Role(
        id="log",
        title="Log agent (N1MM PC)",
        summary="On the band’s N1MM PC: join fleet mcast, keep this band’s QSOs, "
                "forward to local N1MM (TCP 52001 preferred).",
        tooltip=(
            "Required on each N1MM logger PC when WSJT-X is elsewhere on the LAN.\n\n"
            "Listens on 224.0.0.73:2237, filters to this seat’s band, delivers the "
            "Log envelope to N1MM on localhost. Prefer TCP 52001 (JTDX/Others); "
            "UDP 2333 is a fallback — remote 2333 is untrusted.\n\n"
            "Includes a scoped config check for multicast join, band pin, and "
            "N1MM delivery. See docs/decisions/2026-08-22-remote-n1mm-logging.md."
        ),
        button="Start log agent",
        recommended=True,
        long_running=True,
        build_argv=lambda **_: _log_agent_argv(),
    ),
    Role(
        id="key",
        title="Key agent (SSB/CW PC)",
        summary="On the SSB/CW / N1MM seat: KEY sense → inhibit to WSJT-X on that band.",
        tooltip=(
            "Usually the same PC as N1MM (SSB/CW op logs there).\n\n"
            "Reads KEY/CTS and sends tx_inhibit to assigned WSJT gates. Time-critical "
            "path stays seat-local — not through the site server.\n\n"
            "Scoped config check: KEY device, inhibit targets, band policy "
            "(interlock vs coordinated). Lab entry today runs selftest; full GUI later."
        ),
        button="Start key agent",
        recommended=True,
        long_running=False,  # selftest for now; product daemon later
        build_argv=lambda **_: _key_agent_argv(),
    ),
    Role(
        id="wsjt_check",
        title="WSJT seat check",
        summary="On a WSJT-X PC: verify UDP/iface/--rig-name for local instances. "
                "Does not start radios.",
        tooltip=(
            "WSJT-X PCs often have no N1MM. This check only audits what WIMS needs "
            "from those seats: multicast group/port, outgoing interface, Accept UDP, "
            "unique --rig-name per instance, Secondary UDP off when log agent owns logging.\n\n"
            "One PC may host several WSJT-X instances; many instances exist on the LAN. "
            "RF/CQ stay in WSJT-X — this role is config + readiness only."
        ),
        button="Run WSJT check",
        recommended=False,
        long_running=False,
        build_argv=lambda **_: _wsjt_check_argv(),
    ),
    Role(
        id="wsjt_agent",
        title="WSJT seat monitor",
        summary="Optional continuous config/monitor on a WSJT-X PC; reports to site server.",
        tooltip=(
            "Not required for decode or TX. Exists so the fleet can see seat health "
            "and so settings drift is caught.\n\n"
            "Daemon + local UI (http://127.0.0.1:8790/) + optional export to the "
            "site server. Same scoped WSJT checks as “WSJT seat check,” repeated."
        ),
        button="Start WSJT monitor",
        recommended=False,
        long_running=True,
        build_argv=lambda **_: _wsjt_agent_argv(),
    ),
    Role(
        id="solo",
        title="Solo console (lab)",
        summary="Single-PC home/lab path. Not used for W2SZ contest bring-up.",
        tooltip=(
            "Low priority while driving the contest fleet.\n\n"
            "Starts server + browser with single-PC defaults. Prefer Site server + "
            "agents on the real multi-PC layout.\n\n"
            "CLI: python -m wims solo"
        ),
        button="Start Solo",
        recommended=False,
        advanced=True,
        long_running=True,
        build_argv=lambda port=DEFAULT_SOLO_PORT, **_: _solo_argv(port=port),
    ),
)


def role_by_id(role_id: str) -> Role | None:
    for role in ROLES:
        if role.id == role_id:
            return role
    return None


def primary_roles() -> tuple[Role, ...]:
    return tuple(r for r in ROLES if not r.advanced)


def console_urls(http_port: int = DEFAULT_HTTP_PORT) -> dict[str, str]:
    base = f"http://127.0.0.1:{http_port}"
    return {
        "operate": f"{base}/",
        "status": f"{base}/status",
        "setup": f"{base}/setup",
    }
