#!/usr/bin/env python3
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
