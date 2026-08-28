# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""python -m wims — desktop GUI by default; role subcommands for scripts."""

from __future__ import annotations

import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[1]
if _src.name == "src" and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from wims.cli import main

raise SystemExit(main())
