# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Long-running Key agent stub (CTS sense → inhibit targets).

Product inhibit fan-out is later (wims_key_agent.md). This process stays up,
shows compact status, and reports whether a KEY/CTS source and inhibit
target list are configured.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time


def _check() -> tuple[str, str, list[str]]:
    """Return (severity, banner, detail lines)."""
    details: list[str] = []
    dev = (os.environ.get("WIMS_KEY_DEVICE") or "").strip()
    targets = (os.environ.get("WIMS_KEY_TARGETS") or "").strip()
    # Comma-separated host:port for inhibit UDP.
    target_list = [t.strip() for t in targets.split(",") if t.strip()]

    if not dev:
        details.append("[XX] No KEY/CTS source (set WIMS_KEY_DEVICE=/dev/tty… or COMx)")
        sev, banner = "err", "Key agent — no CTS source"
    else:
        details.append(f"[OK] KEY device configured: {dev}")
        # Presence only — full open/read is hardware bring-up.
        if not Path_exists(dev) and not dev.startswith("sim"):
            details.append(f"[! ] Device path not found yet: {dev}")
            sev, banner = "warn", "Key agent — device path missing"
        else:
            sev, banner = "ok", "Key agent — CTS source OK"

    if not target_list:
        details.append(
            "[XX] No inhibit targets (set WIMS_KEY_TARGETS=host:port,… "
            "WSJT-X inhibit sockets)"
        )
        if sev == "ok":
            sev, banner = "err", "Key agent — no inhibit targets"
        elif sev == "warn":
            banner = "Key agent — device/targets need work"
    else:
        details.append(f"[OK] Inhibit targets ({len(target_list)}): " + ", ".join(target_list[:6]))
        if sev == "ok":
            banner = f"Key agent ready — {len(target_list)} target(s)"

    details.append("Product KEY→inhibit fan-out still lab/spike; this agent watches config.")
    return sev, banner, details


def Path_exists(p: str) -> bool:
    try:
        from pathlib import Path
        return Path(p).exists()
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-gui", action="store_true")
    args = ap.parse_args(argv)

    stop = threading.Event()

    def refresh():
        from wims.agent_ui import AgentStatusModel
        sev, banner, details = _check()
        level = {"ok": "ok", "warn": "warn", "err": "err"}.get(sev, "warn")
        return AgentStatusModel(
            title="WIMS key agent",
            banner_level=level,
            banner_text=banner,
            fix_text=details[0] if details else "",
            fact_lines=details[1:4],
            detail_lines=details,
            hover_text="\n".join(details),
        )

    if args.no_gui:
        while not stop.is_set():
            sev, banner, details = _check()
            print(f"key-agent: {banner}", flush=True)
            for d in details:
                print(f"  {d}", flush=True)
            time.sleep(10)
        return 0

    try:
        from wims.agent_ui import AgentStatusWindow
        win = AgentStatusWindow(
            refresh=refresh,
            on_rescan=lambda: None,
            on_quit=lambda: stop.set(),
        )
        win.run()
    except Exception as e:
        print(f"key-agent: GUI failed ({e}); --no-gui", file=sys.stderr)
        return main(["--no-gui"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
