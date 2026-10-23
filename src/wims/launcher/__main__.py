# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""python -m wims.launcher"""

from __future__ import annotations

import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[2]
if _src.name == "src" and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    from wims.launcher.app import main
except ModuleNotFoundError as exc:
    from wims.launcher.plain_message import (
        WINDOW_LIBRARY_MESSAGE,
        is_missing_window_library,
    )

    if not is_missing_window_library(exc):
        raise
    # The double-click script shows the dialog. This path is a direct start.
    sys.stderr.write(WINDOW_LIBRARY_MESSAGE + "\n")
    raise SystemExit(2) from None

raise SystemExit(main())
