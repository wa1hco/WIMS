# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSB/CW seat agent — log ± Key on the N1MM PC (shared live band)."""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from wims.seat.app import main as _main
    return _main(argv)
