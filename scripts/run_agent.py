#!/usr/bin/env python3

# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Run the seat agent without requiring PYTHONPATH.

Usage (from any cwd):
  python scripts/run_agent.py
  python scripts/run_agent.py --daemon
  python scripts/run_agent.py --server http://192.168.1.119:8787

Prefer this over bare ``python -m wims.agent`` on seats — ``-m`` needs
``PYTHONPATH=<repo>/src`` (the Windows .cmd wrappers set that for you).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from wims.agent.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
