# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Log helper/agent — fleet mcast Logged QSO → local N1MM (N1MM PC)."""

from __future__ import annotations

__all__ = ["GROUP", "PORT"]

GROUP = "224.0.0.73"
PORT = 2237
