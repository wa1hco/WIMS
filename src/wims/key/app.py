# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""KEY / TX-inhibit role entrypoint.

Product surface for the desktop launcher. Today this wraps the lab spike
(``testbed/inhibit_spike.py``) so Solo testers have one place to discover KEY
tools. Fleet target-list assignment (docs/plan/wims_key_agent.md) is later.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPIKE = _REPO_ROOT / "testbed" / "inhibit_spike.py"


def _load_spike():
    if not _SPIKE.is_file():
        raise FileNotFoundError(
            f"KEY lab spike not found at {_SPIKE}. "
            "Clone the full WIMS tree (include testbed/)."
        )
    spec = importlib.util.spec_from_file_location("wims_inhibit_spike", _SPIKE)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_SPIKE}")
    mod = importlib.util.module_from_spec(spec)
    # Spike expects repo src on path for wims.interlock.inhibit — already true
    # when launched via python -m wims.key.
    sys.modules["wims_inhibit_spike"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m wims.key",
        description="WIMS KEY agent (lab). SSB/CW key → TX-inhibit path. "
                    "Not required for Solo FT8.",
    )
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser(
        "selftest",
        help="UDP loopback gate+agent assertions (same as testbed/inhibit_spike.py selftest)",
    )
    sub.add_parser("gate", help="lab gate stand-in (pass remaining flags after --)")
    sub.add_parser("agent", help="lab key agent (pass remaining flags after --)")
    sub.add_parser(
        "daemon",
        help="long-running Key agent UI/stub (CTS source + inhibit target check)",
    )
    args, rest = ap.parse_known_args(argv)

    cmd = args.cmd or "selftest"
    if cmd == "daemon":
        from wims.key.daemon import main as daemon_main
        return int(daemon_main(rest) or 0)

    try:
        spike = _load_spike()
    except (FileNotFoundError, ImportError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Re-dispatch through the spike CLI so gate/agent flags stay in one place.
    return int(spike.main([cmd, *rest]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
