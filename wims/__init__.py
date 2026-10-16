# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checkout shim so `python -m wims` works from the repo without PYTHONPATH.

The implementation lives in ``src/wims``. This package only puts that folder
first on ``sys.path`` and loads it. Launchers are the way to start WIMS.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_REAL_INIT = _SRC / "wims" / "__init__.py"


def _load_real() -> None:
    if not _REAL_INIT.is_file():
        raise ImportError(
            "WIMS could not find its program files. "
            "Double-click the WIMS icon in this folder."
        )
    src = str(_SRC)
    # Drop the shim (and any submodule loaded from this folder) so the
    # implementation in src/ can take the name "wims".
    shim_root = str(_ROOT / "wims")
    for name in list(sys.modules):
        if name != "wims" and not name.startswith("wims."):
            continue
        mod = sys.modules.get(name)
        path = getattr(mod, "__file__", "") or ""
        if name == "wims" or path.startswith(shim_root):
            del sys.modules[name]
    while src in sys.path:
        sys.path.remove(src)
    sys.path.insert(0, src)
    importlib.import_module("wims")


_load_real()
