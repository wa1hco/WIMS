# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Key-only seat escape: ``python -m wims.key daemon`` → ``wims.seat --key``.

Prefer the launcher SSB/CW KEY intent (combined seat with log) on contest PCs.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-gui", action="store_true")
    # Accept and forward unknown key/seat flags.
    args, rest = ap.parse_known_args(argv)
    seat_argv = ["--key", *rest]
    if args.no_gui:
        seat_argv.append("--no-gui")
    from wims.seat.app import main as seat_main
    return int(seat_main(seat_argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
