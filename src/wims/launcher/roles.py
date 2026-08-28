# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Role catalog for the desktop launcher (pure data + argv builders)."""

from __future__ import annotations

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


def _check_argv() -> list[str]:
    return ["-m", "wims.agent", "--solo"]


def _agent_argv() -> list[str]:
    return ["-m", "wims.agent", "--daemon"]


def _key_selftest_argv() -> list[str]:
    # Prefer product module when present; fall back to lab spike path via -c.
    return ["-m", "wims.key", "selftest"]


ROLES: tuple[Role, ...] = (
    Role(
        id="solo",
        title="Solo console",
        summary="One PC: N1MM + WSJT-X + WIMS together. Opens the Operate page in your browser.",
        tooltip=(
            "Use this at home or on a single radio seat.\n\n"
            "Starts the WIMS console on this computer, watches your local WSJT-X "
            "over UDP, and seeds needed/dupe from your N1MM log.\n\n"
            "In WSJT-X → Settings → Reporting:\n"
            "  • UDP Server 224.0.0.73 and the band port below\n"
            "  • Accept UDP requests = ON\n\n"
            "Then click a roster line to Work; Halt TX is always available.\n"
            "Calling CQ stays in the WSJT-X window."
        ),
        button="Start Solo",
        recommended=True,
        long_running=True,
        build_argv=lambda port=DEFAULT_SOLO_PORT, **_: _solo_argv(port=port),
    ),
    Role(
        id="check",
        title="Check this PC",
        summary="Plain-language [OK] / [!] / [XX] report for WSJT-X and N1MM. Starts nothing.",
        tooltip=(
            "Safe first step. Reads your WSJT-X.ini and looks for N1MM, then prints "
            "what is wrong in everyday language.\n\n"
            "Does not start the console or change any settings."
        ),
        button="Run check",
        recommended=False,
        long_running=False,
        build_argv=lambda **_: _check_argv(),
    ),
    Role(
        id="server",
        title="Site server",
        summary="Fleet / multi-PC: one server for the whole contest LAN (all band ports).",
        tooltip=(
            "Run this on the site computer (or a lab PC), not usually on every radio seat.\n\n"
            "Joins every band stream (2237–2239, 2241–2243), builds the combined "
            "roster, and serves Operate / Status / Setup at http://<this-pc>:8787/\n\n"
            "Radio seats open that URL in a browser. Seat agents report into Status."
        ),
        button="Start server",
        recommended=False,
        long_running=True,
        build_argv=lambda **_: _server_argv(),
    ),
    Role(
        id="agent",
        title="Seat agent",
        summary="On a radio PC: keeps checking setup and reports to the site server.",
        tooltip=(
            "Leave this running on seats that also run WSJT-X / N1MM.\n\n"
            "Opens a small local page at http://127.0.0.1:8790/ and sends "
            "config health to the site WIMS server (discovered on the LAN, "
            "or set via WIMS_SERVER).\n\n"
            "Does not transmit. Does not replace Solo or the site server."
        ),
        button="Start agent",
        recommended=False,
        long_running=True,
        build_argv=lambda **_: _agent_argv(),
    ),
    Role(
        id="key",
        title="KEY agent (lab)",
        summary="SSB/CW key → TX-inhibit self-test. Not needed for normal FT8 Solo use.",
        tooltip=(
            "Advanced / lab only.\n\n"
            "Exercises the KEY → inhibit path used when an SSB/CW operator "
            "must stop WSJT-X on the same band.\n\n"
            "Home FT8 testers can ignore this. Requires the KEY role module "
            "or lab spike; see docs/plan/wims_key_agent.md."
        ),
        button="Run KEY selftest",
        recommended=False,
        advanced=True,
        long_running=False,
        build_argv=lambda **_: _key_selftest_argv(),
    ),
)


def role_by_id(role_id: str) -> Role | None:
    for role in ROLES:
        if role.id == role_id:
            return role
    return None


def console_urls(http_port: int = DEFAULT_HTTP_PORT) -> dict[str, str]:
    base = f"http://127.0.0.1:{http_port}"
    return {
        "operate": f"{base}/",
        "status": f"{base}/status",
        "setup": f"{base}/setup",
    }
