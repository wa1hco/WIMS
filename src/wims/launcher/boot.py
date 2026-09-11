# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Logon boot: start WSJT-X / N1MM / WIMS from this PC's saved seat intent.

Reads ``%APPDATA%\\wims\\seat_intent.json`` (launcher checkboxes). If none is
saved, seeds from apps detected on the PC. Then starts:

* WSJT-X when intent ``wsjt`` (``--rig-name`` from seat cmd files or named configs)
* N1MM when intent ``n1mm``
* Desktop WIMS launcher always (it starts agents / site server from the same intent)

Does not start radio middleware (SmartSDR / wfview); use the seat packs for that.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from wims.launcher.assets import (
    INTENT_N1MM,
    INTENT_SERVER,
    INTENT_SSB_CW,
    INTENT_WSJT,
    detect_assets,
    load_seat_intent,
    seat_intent_saved,
    seed_intent_from_assets,
)

_SET_RE = re.compile(
    r'(?im)^\s*set\s+"([A-Za-z0-9_]+)=(.*?)"\s*$'
)
_WIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "windows"
_DEFAULT_WSJTX = Path(r"C:\WSJT\wsjtx\bin\wsjtx.exe")
_DEFAULT_N1MM = Path(r"C:\Program Files (x86)\N1MM Logger+\N1MMLogger.net.exe")
# Default install first; wsjtx-inhibit only when that exe is missing.
_WSJTX_SEARCH = (
    str(_DEFAULT_WSJTX),
    r"C:\WSJT\wsjtx-inhibit\bin\wsjtx.exe",
    r"C:\Program Files\WSJT\wsjtx\bin\wsjtx.exe",
)


@dataclass
class BootPlan:
    intent: dict[str, bool]
    intent_source: str
    start_wims: bool = True
    start_wsjtx: bool = False
    start_n1mm: bool = False
    wsjtx_exe: str = ""
    n1mm_exe: str = ""
    rig_names: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_cmd_sets(path: Path) -> dict[str, str]:
    """Parse ``set "NAME=value"`` lines from a seat .cmd file."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for m in _SET_RE.finditer(text):
        out[m.group(1)] = m.group(2)
    return out


def load_seat_cmd_env(scripts: Path | None = None) -> dict[str, str]:
    """Merge gitignored seat cmd files (common → radio pack → local)."""
    here = Path(scripts) if scripts is not None else _WIN_SCRIPTS
    env: dict[str, str] = {}
    for name in ("seat-common.cmd", "seat-local.cmd"):
        env.update(parse_cmd_sets(here / name))
    pack = (env.get("SEAT_DEFAULT_RADIO") or "").strip().lower()
    radio = {
        "flex50": "radio-flex50.cmd",
        "flex": "radio-flex50.cmd",
        "ic9700-144": "radio-ic9700-144.cmd",
        "ic9700": "radio-ic9700-144.cmd",
    }.get(pack)
    if radio:
        env.update(parse_cmd_sets(here / radio))
    else:
        for name in ("radio-flex50.cmd", "radio-ic9700-144.cmd"):
            extra = parse_cmd_sets(here / name)
            if extra.get("WSJTX_RIG_NAME"):
                env.update(extra)
                break
    env.update(parse_cmd_sets(here / "seat-local.cmd"))
    return env


def named_wsjtx_rigs() -> list[str]:
    """Rig-names from ``%LOCALAPPDATA%\\WSJT-X - <name>`` folders."""
    base = os.environ.get("LOCALAPPDATA") or ""
    if not base:
        return []
    names: list[str] = []
    try:
        for p in sorted(Path(base).glob("WSJT-X - *")):
            if p.is_dir():
                name = p.name[len("WSJT-X - "):].strip()
                if name:
                    names.append(name)
    except OSError:
        return []
    return names


def find_wsjtx_exe(
    cmd_env: dict[str, str] | None = None,
    *,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> Path | None:
    """First existing wsjtx.exe: override, default ``C:\\WSJT\\wsjtx``, then inhibit."""
    env = cmd_env or {}
    ordered: list[str] = []
    for raw in (env.get("WSJTX_EXE"), os.environ.get("WSJTX_EXE")):
        if raw and raw.strip():
            ordered.append(raw.strip())
    ordered.extend(search_paths if search_paths is not None else _WSJTX_SEARCH)
    seen: set[str] = set()
    for raw in ordered:
        p = Path(raw)
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            return p
    return None


def find_n1mm_exe(cmd_env: dict[str, str] | None = None) -> Path | None:
    env = cmd_env or {}
    candidates = [
        env.get("N1MM_EXE"),
        os.environ.get("N1MM_EXE"),
        str(_DEFAULT_N1MM),
    ]
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw)
        if p.is_file():
            return p
    return None


def resolve_boot_plan(
    *,
    scripts: Path | None = None,
    cmd_env: dict[str, str] | None = None,
) -> BootPlan:
    snap = detect_assets()
    if seat_intent_saved():
        intent = load_seat_intent()
        source = "saved seat intent"
    else:
        intent = seed_intent_from_assets(snap)
        source = "detected apps (no saved intent)"

    env = dict(cmd_env or load_seat_cmd_env(scripts))
    notes: list[str] = [source]
    rig = (os.environ.get("WSJTX_RIG_NAME") or env.get("WSJTX_RIG_NAME") or "").strip()
    rigs = [rig] if rig else named_wsjtx_rigs()
    if not rigs and intent.get(INTENT_WSJT):
        host = socket.gethostname().split(".")[0].strip()
        if host:
            rigs = [host]
            notes.append(f"WSJT-X --rig-name defaulted to hostname {host}")

    wsjtx = find_wsjtx_exe(env)
    n1mm = find_n1mm_exe(env)
    start_wsjt = bool(intent.get(INTENT_WSJT))
    start_n1mm = bool(intent.get(INTENT_N1MM))
    if start_wsjt and not wsjtx:
        notes.append("WSJT-X intent is on but wsjtx.exe was not found")
        start_wsjt = False
    if start_wsjt and not rigs:
        notes.append("WSJT-X intent is on but no --rig-name (edit seat-local.cmd)")
        start_wsjt = False
    if start_n1mm and not n1mm:
        notes.append("N1MM intent is on but N1MMLogger.net.exe was not found")
        start_n1mm = False
    if intent.get(INTENT_SERVER):
        notes.append("Site server intent on — WIMS launcher will start it")
    if intent.get(INTENT_SSB_CW):
        notes.append("SSB/CW KEY intent on — WIMS launcher starts N1MM agent --key")

    return BootPlan(
        intent=intent,
        intent_source=source,
        start_wims=True,
        start_wsjtx=start_wsjt,
        start_n1mm=start_n1mm,
        wsjtx_exe=str(wsjtx) if wsjtx else "",
        n1mm_exe=str(n1mm) if n1mm else "",
        rig_names=rigs,
        notes=notes,
    )


def _running(image: str) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return image.lower() in (proc.stdout or "").lower()


def _start_detached(argv: list[str], *, cwd: Path | None = None) -> None:
    kw: dict = {"cwd": str(cwd) if cwd else None}
    if sys.platform.startswith("win"):
        kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        kw["close_fds"] = True
    subprocess.Popen(argv, **{k: v for k, v in kw.items() if v is not None})


def _launcher_pythonw() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")
        if w.is_file():
            return str(w)
    return str(exe)


def apply_boot_plan(plan: BootPlan, *, dry_run: bool = False) -> list[str]:
    """Start the planned apps. Returns log lines."""
    lines: list[str] = [
        f"Intent ({plan.intent_source}): "
        + ", ".join(k for k, v in plan.intent.items() if v) or "(none)",
    ]
    lines.extend(plan.notes)
    if dry_run:
        if plan.start_wsjtx:
            lines.append(
                f"would start WSJT-X {plan.wsjtx_exe} --rig-name="
                + ",".join(plan.rig_names)
            )
        if plan.start_n1mm:
            lines.append(f"would start N1MM {plan.n1mm_exe}")
        if plan.start_wims:
            lines.append("would start WIMS launcher")
        return lines

    if plan.start_wsjtx and plan.wsjtx_exe:
        if _running("wsjtx.exe"):
            lines.append("WSJT-X already running — leave it")
        else:
            for name in plan.rig_names:
                _start_detached([plan.wsjtx_exe, f"--rig-name={name}"])
                lines.append(f"started WSJT-X --rig-name={name}")

    if plan.start_n1mm and plan.n1mm_exe:
        if _running("N1MMLogger.net.exe"):
            lines.append("N1MM already running — leave it")
        else:
            _start_detached([plan.n1mm_exe])
            lines.append("started N1MM")

    if plan.start_wims:
        if _wims_launcher_running():
            lines.append("WIMS launcher already running — leave it")
        else:
            root = Path(__file__).resolve().parents[3]
            env = os.environ.copy()
            src = str(root / "src")
            env["PYTHONPATH"] = (
                src if not env.get("PYTHONPATH")
                else f"{src}{os.pathsep}{env['PYTHONPATH']}"
            )
            pyw = _launcher_pythonw()
            subprocess.Popen(
                [pyw, "-m", "wims.launcher"],
                cwd=str(root),
                env=env,
                **(
                    {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                    if sys.platform.startswith("win") else {}
                ),
            )
            lines.append("started WIMS launcher")
    return lines


def _wims_launcher_running() -> bool:
    try:
        from wims.launcher.process_replace import list_process_table
        me = os.getpid()
        for pid, argv in list_process_table():
            if pid == me:
                continue
            joined = " ".join(argv).lower().replace("\\", "/")
            if "wims.launcher.boot" in joined:
                continue
            if "wims.launcher" in joined:
                return True
    except Exception:
        return False
    return False


def main(argv: list[str] | None = None) -> int:
    try:
        from wims.launcher.process_replace import hide_own_console_if_redirected
        hide_own_console_if_redirected()
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--delay", type=int, default=None,
        help="Seconds to wait before starting (logon: default 15, else 0)",
    )
    ap.add_argument(
        "--logon", action="store_true",
        help="Logon mode: wait, then start (no console prompts)",
    )
    args = ap.parse_args(argv)
    delay = args.delay
    if delay is None:
        delay = 15 if args.logon else 0
    if delay > 0 and not args.dry_run:
        time.sleep(delay)
    plan = resolve_boot_plan()
    for line in apply_boot_plan(plan, dry_run=args.dry_run):
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
