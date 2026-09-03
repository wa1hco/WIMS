# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""KEY / TX-inhibit role entrypoint.

Product surface for the desktop launcher. Lab modes wrap the inhibit bench
(``testbed/inhibit_bench.py``). Fleet target-list assignment
(docs/plan/wims_key_agent.md) is later; ``daemon`` is still a config stub.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BENCH = _REPO_ROOT / "testbed" / "inhibit_bench.py"


def _load_bench():
    if not _BENCH.is_file():
        raise FileNotFoundError(
            f"KEY inhibit bench not found at {_BENCH}. "
            "Clone the full WIMS tree (include testbed/)."
        )
    spec = importlib.util.spec_from_file_location("wims_inhibit_bench", _BENCH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_BENCH}")
    mod = importlib.util.module_from_spec(spec)
    # Bench expects repo src on path for wims.interlock.inhibit — already true
    # when launched via python -m wims.key.
    sys.modules["wims_inhibit_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m wims.key",
        description="WIMS KEY agent. Lab: inhibit bench (gate/agent/selftest). "
                    "Daemon: long-running stub. Not required for Solo FT8.",
    )
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser(
        "selftest",
        help="UDP loopback gate+agent assertions "
             "(same as testbed/inhibit_bench.py selftest)",
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
        bench = _load_bench()
    except (FileNotFoundError, ImportError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Re-dispatch through the bench CLI so gate/agent flags stay in one place.
    return int(bench.main([cmd, *rest]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
