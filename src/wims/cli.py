# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-level ``python -m wims`` entry.

Default (no args): open the **desktop GUI launcher**.
Optional role subcommands remain for scripts and .cmd wrappers.
"""

from __future__ import annotations

import argparse
import sys

from wims import __version__

_ROLES = ("gui", "solo", "server", "agent", "log", "key", "version")


def _dispatch(role: str, role_argv: list[str]) -> int:
    if role in ("gui", "launcher"):
        from wims.launcher.app import main as gui_main
        return int(gui_main(role_argv) or 0)

    if role == "version":
        print(__version__)
        return 0

    if role == "solo":
        # solo.main reads sys.argv
        sys.argv = ["wims.solo", *role_argv]
        from wims.solo import main as solo_main
        solo_main()
        return 0

    if role == "server":
        sys.argv = ["wims.server.app", *role_argv]
        from wims.server.app import main as server_main
        server_main()
        return 0

    if role == "agent":
        from wims.agent.app import main as agent_main
        return int(agent_main(role_argv) or 0)

    if role == "log":
        from wims.log.app import main as log_main
        return int(log_main(role_argv) or 0)

    if role == "key":
        from wims.key.app import main as key_main
        return int(key_main(role_argv) or 0)

    print(f"unknown role: {role}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # No args → GUI (desktop peer experience).
    if not argv:
        return _dispatch("gui", [])

    # Allow `wims --install-shortcut` etc. straight into the GUI parser.
    if argv[0].startswith("-"):
        return _dispatch("gui", argv)

    role = argv[0]
    rest = argv[1:]
    if role in ("-h", "--help", "help"):
        print(
            "WIMS — WSJT-X Instance Management System\n\n"
            "Usage:\n"
            "  python -m wims                 Open the desktop GUI launcher\n"
            "  python -m wims gui             Same as above\n"
            "  python -m wims solo [opts]     Single-PC console\n"
            "  python -m wims server [opts]   Site / fleet server\n"
            "  python -m wims agent [opts]    Seat agent\n"
            "  python -m wims log [opts]      Log agent (N1MM PC)\n"
            "  python -m wims key [cmd]       Key agent / inhibit tools\n"
            "  python -m wims version         Print version\n\n"
            "Desktop: use Put WIMS on Desktop inside the GUI, or\n"
            "  python -m wims --install-shortcut\n"
        )
        return 0

    if role not in _ROLES and role != "launcher":
        print(
            f"Unknown role {role!r}. Try: python -m wims help\n"
            f"Roles: {', '.join(_ROLES)}",
            file=sys.stderr,
        )
        return 2

    return _dispatch(role, rest)


if __name__ == "__main__":
    raise SystemExit(main())
