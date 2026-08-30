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
    # Local UI is always http://127.0.0.1:8790/ on THIS PC.
    # Site console URL comes from WIMS_SERVER or presence discovery — never assume
    # the site server is on localhost (Windows seat VMs usually are not the server).
    argv = ["-m", "wims.agent", "--daemon", "--local-port", "8790"]
    server = (os.environ.get("WIMS_SERVER") or "").strip()
    if server:
        argv += ["--server", server]
    return argv


def _log_agent_argv(*, band: str | None = None, gui: bool = True) -> list[str]:
    # Product module: compact Tk status UI by default (--no-gui for lab).
    # Live filter follows N1MM RadioInfo; --expect-band is optional warn-only.
    argv = ["-m", "wims.log"]
    b = (band or os.environ.get("WIMS_BAND") or "").strip()
    if b:
        argv += ["--expect-band", b]
    if not gui:
        argv.append("--no-gui")
    return argv


def _key_agent_argv() -> list[str]:
    # Long-running stub: CTS + inhibit-target config check (product fan-out later).
    return ["-m", "wims.key", "daemon"]


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
        summary="On the N1MM PC: join fleet mcast, filter by N1MM’s live band "
                "(RadioInfo), forward to local N1MM (TCP 52001 preferred).",
        tooltip=(
            "Required on each N1MM logger PC when WSJT-X is elsewhere on the LAN.\n\n"
            "Listens on 224.0.0.73:2237. Band filter follows N1MM RadioInfo "
            "(Broadcast Data → Radio to 127.0.0.1:12060). Drops QSOs until a "
            "band is heard; adapts if the operator changes band.\n\n"
            "Opens a small status window. "
            "See docs/decisions/2026-08-29-n1mm-live-band.md."
        ),
        button="Start log agent",
        recommended=True,
        long_running=True,
        build_argv=lambda band=None, gui=True, **_: _log_agent_argv(band=band, gui=gui),
    ),
    Role(
        id="key",
        title="Key agent",
        summary="KEY/CTS sense → inhibit targets. Checks device + target list; "
                "product fan-out still lab.",
        tooltip=(
            "Long-running Key agent. Set WIMS_KEY_DEVICE and WIMS_KEY_TARGETS.\n"
            "No companion desktop app — this agent is the KEY path."
        ),
        button="Start Key agent",
        recommended=False,
        advanced=False,
        long_running=True,
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
