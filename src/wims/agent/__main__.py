"""python -m wims.agent

Requires the ``src`` directory on sys.path, e.g.::

    set PYTHONPATH=C:\\path\\to\\WIMS\\src
    python -m wims.agent

Or use the path-safe launcher (preferred on seats)::

    python scripts/run_agent.py
    scripts\\windows\\Start-WimsAgent.cmd
"""

from __future__ import annotations

import sys
from pathlib import Path

# If someone runs this file directly, put src on the path.
_src = Path(__file__).resolve().parents[2]
if _src.name == "src" and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    from wims.agent.app import main
except ModuleNotFoundError as e:
    if e.name == "wims" or (e.name and e.name.startswith("wims")):
        print(
            "ERROR: cannot import wims — PYTHONPATH must include the repo's src/ folder.\n"
            "  Windows cmd:  set PYTHONPATH=%CD%\\src\n"
            "  Then:         python -m wims.agent\n"
            "  Or:           python scripts\\run_agent.py\n"
            "  Or double-click: scripts\\windows\\Start-WimsAgent.cmd",
            file=sys.stderr,
        )
        raise SystemExit(3) from e
    raise

raise SystemExit(main())