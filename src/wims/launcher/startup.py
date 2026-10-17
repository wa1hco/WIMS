# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One start path for the WIMS window and for Operate.

The desktop icon, ``scripts/start-wims.sh``, and the Windows shortcuts open
the WIMS window (``wims.launcher``). Operate, whether the window starts it
or a script starts it, comes through :func:`guard_console` and
:func:`operate_banner` so the port check, seat reading, network default,
log and rules, browser, messages, and log file match.

Shell files only choose Python and the module. They do not reimplement the
port check.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# Modules the entry scripts must reach. Tests compare scripts to these names.
LAUNCHER_MODULE = "wims.launcher"
SOLO_MODULE = "wims.solo"

# Operate joins WSJT-X on this PC. The site server uses the process default
# (automatic contest LAN) because its argv does not pass an interface.
SOLO_IFACE = "127.0.0.1"
CONSOLE_PORT = 8787

_SEAT_WORDS = {
    "n1mm": "an N1MM seat",
    "wsjt": "a WSJT-X seat",
    "site": "the site server",
    "ambiguous": "this PC",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def startup_log_path(repo: Path | None = None) -> Path:
    """Same file the WIMS window writes its Details log to."""
    root = Path(repo) if repo is not None else repo_root()
    return root / "scratch" / "launcher-details.log"


def log_startup(message: str, *, repo: Path | None = None) -> None:
    """Print a start line and append it to the shared log.

    When the WIMS window starts Operate, it captures the child's output and
    writes the log itself (``WIMS_CAPTURED_LOG=1``), so this does not write
    the file a second time.
    """
    text = (message or "").rstrip("\n")
    print(text, flush=True)
    if (os.environ.get("WIMS_CAPTURED_LOG") or "").strip() == "1":
        return
    path = startup_log_path(repo)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def probe_console(port: int = CONSOLE_PORT, *, timeout: float = 0.8) -> str:
    """Return ``free``, ``wims``, or ``busy`` for ``127.0.0.1:port``."""
    sock = socket.socket()
    sock.settimeout(min(0.4, timeout))
    try:
        sock.connect(("127.0.0.1", int(port)))
    except OSError:
        return "free"
    finally:
        sock.close()
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/healthz", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        data = {}
    if isinstance(data, dict) and data.get("ok") and data.get("role") == "wims-site-server":
        return "wims"
    return "busy"


def console_action(probe: str, *, port: int = CONSOLE_PORT) -> tuple[str, str]:
    """Map a probe result to ``start``, ``reuse``, or ``busy`` plus a message.

    Pure: tests do not open a socket. ``start`` has an empty message; the
    caller logs :func:`operate_banner` instead.
    """
    if probe == "free":
        return "start", ""
    if probe == "wims":
        return "reuse", "WIMS is already open. Showing the console."
    return (
        "busy",
        f"Port {int(port)} is in use, but it is not WIMS.\n"
        "Close the other program, or open the WIMS window if it is already running.\n"
        f"The console, when WIMS is up, is http://localhost:{int(port)}/",
    )


def solo_iface(explicit: str | None) -> str:
    """Operate network default. An explicit value (the window's lab choice) wins."""
    text = (explicit or "").strip()
    return text or SOLO_IFACE


def seat_sentence(seat_type: str, detail: str = "") -> str:
    """Plain reading of this PC. Both Operate starts log the same sentence."""
    kind = _SEAT_WORDS.get((seat_type or "").strip().lower(), "this PC")
    extra = (detail or "").strip()
    if extra:
        return f"This PC looks like {kind} ({extra})."
    return f"This PC looks like {kind}."


def read_seat_sentence() -> str:
    try:
        from wims.launcher.seat_detect import probe_seat
        probe = probe_seat()
    except Exception:
        return seat_sentence("ambiguous")
    return seat_sentence(probe.seat_type, probe.detail)


def operate_banner(
    *,
    http_port: int,
    iface: str,
    seed: bool,
    seat: str,
) -> str:
    """One sentence logged before Operate loads the log and rules."""
    if seed:
        loaded = "The log and contest rules are loaded."
    else:
        loaded = "Starting with an empty log."
    return (
        f"Operate on this PC. Console http://localhost:{int(http_port)}/. "
        f"Network {iface}. {loaded} {seat}"
    )


def guard_console(port: int, *, open_browser: bool) -> int | None:
    """Reuse an existing console, or refuse a foreign listener.

    Returns ``None`` when Operate should continue (port free). Returns ``0``
    when the console was already WIMS, ``1`` when something else has the port.
    """
    action, message = console_action(probe_console(port), port=port)
    if action == "start":
        return None
    log_startup(message)
    if action == "reuse" and open_browser:
        try:
            from wims.launcher.app import open_wims_url
            open_wims_url(f"http://localhost:{int(port)}/")
        except Exception:
            log_startup(
                f"The console is already up at http://localhost:{int(port)}/ ."
            )
    return 0 if action == "reuse" else 1
