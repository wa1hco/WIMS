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


# Plane A is a single port (decision 2026-09-05). Label is for solo UI only.
BAND_PORTS: tuple[tuple[str, int], ...] = (
    ("All bands (plane A)", 2237),
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
    # Escape: log-only seat process (same RadioInfo band path).
    argv = ["-m", "wims.seat", "--log"]
    b = (band or os.environ.get("WIMS_BAND") or "").strip()
    if b:
        argv += ["--expect-band", b]
    if not gui:
        argv.append("--no-gui")
    return argv


def _key_agent_argv() -> list[str]:
    # Escape: Key-only seat process.
    return ["-m", "wims.seat", "--key"]


def _n1mm_seat_argv(*, want_log: bool = True, want_key: bool = False,
                    band: str | None = None, gui: bool = True) -> list[str]:
    """Combined N1MM/SSB-CW seat: shared live band, optional log + Key."""
    argv = ["-m", "wims.seat"]
    if want_log:
        argv.append("--log")
    if want_key:
        argv.append("--key")
    if not want_log and not want_key:
        argv.append("--log")  # should not happen; keep process meaningful
    b = (band or os.environ.get("WIMS_BAND") or "").strip()
    if b:
        argv += ["--expect-band", b]
    if not gui:
        argv.append("--no-gui")
    return argv


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
        id="n1mm_seat",
        title="N1MM agent",
        summary="On the N1MM PC: Broadcast + Log + optional KEY (one process).",
        tooltip=(
            "N1MM agent — three sections:\n"
            "  Broadcast — hear N1MM Broadcast Data (RadioInfo) on 127.0.0.1:12060; "
            "report presence to the site server\n"
            "  Log — fleet digi Logged QSOs → local N1MM (:52001/:2333)\n"
            "  KEY — CTS → same-band type-18 holds\n\n"
            "Launcher intents N1MM and SSB/CW KEY start this with the right flags."
        ),
        button="Start N1MM agent",
        recommended=True,
        long_running=True,
        build_argv=lambda want_log=True, want_key=False, band=None, gui=True, **_: (
            _n1mm_seat_argv(want_log=want_log, want_key=want_key, band=band, gui=gui)
        ),
    ),
    Role(
        id="log",
        title="N1MM agent Log-only (escape)",
        summary="Log-only (--log). Prefer N1MM intent in the launcher.",
        tooltip="Escape hatch: python -m wims.seat --log (or wims.log).",
        button="Start Log-only",
        recommended=False,
        advanced=True,
        long_running=True,
        build_argv=lambda band=None, gui=True, **_: _log_agent_argv(band=band, gui=gui),
    ),
    Role(
        id="key",
        title="N1MM agent KEY-only (escape)",
        summary="KEY-only (--key). Prefer SSB/CW KEY intent in the launcher.",
        tooltip=(
            "Escape hatch: python -m wims.seat --key.\n"
            "KEY device from launcher (WIMS_KEY_DEVICE); targets from discovery "
            "or WIMS_KEY_TARGETS."
        ),
        button="Start KEY-only",
        recommended=False,
        advanced=True,
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
