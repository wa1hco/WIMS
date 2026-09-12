# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Safe replace of local seat agents on launcher start.

Seat agents (log / seat daemon / key daemon) are stopped so a new launcher can
own them. The site server is never killed here — only listed. Never touches
WSJT-X, N1MM, or the current launcher process.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["log", "seat", "key", "n1mm_seat", "server", "other"]

# Only these are replaced on launcher start.
# n1mm_seat = combined log±key on the N1MM/SSB-CW PC (wims.seat).
# "seat" remains the WSJT monitor (wims.agent --daemon).
_SEAT_KINDS = frozenset({"log", "seat", "key", "n1mm_seat"})


def windows_hidden_popen_kwargs() -> dict:
    """Flags so a Windows console child (python.exe) does not open a terminal.

    ``CREATE_NO_WINDOW`` is the real switch; STARTUPINFO/SW_HIDE is backup for
    hosts that still flash a console. No-op on non-Windows.
    """
    if os.name != "nt":
        return {}
    kw: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kw["startupinfo"] = si
    except Exception:
        pass
    return kw


def _conhost_child_pids(parent_pids: set[int]) -> set[int]:
    """PIDs of conhost.exe processes whose parent is in ``parent_pids``."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return set()
    th32cs_snapprocess = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if snap in (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        return set()
    out: set[int] = set()
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return set()
        while True:
            if (
                pe.szExeFile.lower() == "conhost.exe"
                and int(pe.th32ParentProcessID) in parent_pids
            ):
                out.add(int(pe.th32ProcessID))
            if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                break
        return out
    finally:
        kernel32.CloseHandle(snap)


def hide_console_windows_for_pids(pids: Iterable[int]) -> int:
    """Hide ConsoleWindowClass windows owned by ``pids`` (or their conhost).

    1.0.1 hid *new* launcher children with CREATE_NO_WINDOW, but a site server
    left running from before that still keeps its python.exe terminal. Call this
    for leftover server PIDs (and after spawn, in case a console still appears).
    Returns how many windows were hidden. No-op on non-Windows.
    """
    if os.name != "nt":
        return 0
    want = {int(p) for p in pids if p}
    if not want:
        return 0
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return 0

    want |= _conhost_child_pids(want)
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    sw_hide = 0
    hidden: list[int] = []
    wnd_enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @wnd_enum_proc
    def _enum(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in want:
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "ConsoleWindowClass":
            user32.ShowWindow(hwnd, sw_hide)
            hidden.append(int(hwnd))
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        pass

    # Fallback: attach to the child's console and hide it (pythonw parent only;
    # a process can have at most one console).
    if not hidden and kernel32.GetConsoleWindow() == 0:
        for pid in list(want):
            try:
                if not kernel32.AttachConsole(pid):
                    continue
                hwnd = kernel32.GetConsoleWindow()
                if hwnd:
                    user32.ShowWindow(hwnd, sw_hide)
                    hidden.append(int(hwnd))
                kernel32.FreeConsole()
            except Exception:
                try:
                    kernel32.FreeConsole()
                except Exception:
                    pass
    return len(hidden)


def hide_own_console_if_redirected() -> bool:
    """Detach this process from a Windows console when stdout is not a TTY.

    Launcher children have stdout piped into Details, so hiding is safe.
    Interactive ``Start-WimsServer.cmd`` keeps the console (isatty).
    Set WIMS_KEEP_CONSOLE=1 to force a visible terminal.
    """
    if os.name != "nt":
        return False
    flag = (os.environ.get("WIMS_KEEP_CONSOLE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return False
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            return False
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.kernel32.FreeConsole()
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    argv: list[str]
    kind: Kind
    cmdline: str = ""


@dataclass
class ReplaceReport:
    found: list[ProcInfo] = field(default_factory=list)
    stopped: list[ProcInfo] = field(default_factory=list)
    failed: list[tuple[ProcInfo, str]] = field(default_factory=list)
    skipped_server: list[ProcInfo] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        out: list[str] = []
        for p in self.stopped:
            out.append(f"Stopped {p.kind} agent pid={p.pid}")
        for p, err in self.failed:
            out.append(f"FAILED to stop {p.kind} pid={p.pid}: {err}")
        for p in self.skipped_server:
            out.append(f"Left site server running pid={p.pid} (not auto-killed)")
        if not self.found:
            out.append("No leftover WIMS seat agents on this PC.")
        elif not self.stopped and not self.failed and self.skipped_server:
            out.append("Seat agents clear; site server left alone.")
        return out


def classify_argv(argv: Iterable[str]) -> Kind:
    """Classify a process argv as a WIMS long-running role (or other)."""
    args = [a for a in argv if a]
    if not args:
        return "other"
    # Join for simple token search; also walk -m MODULE.
    joined = " ".join(args)
    low = joined.lower()

    # Module form: python -m wims.log / wims.agent / wims.key / wims.server[.app]
    mod = None
    for i, a in enumerate(args):
        if a == "-m" and i + 1 < len(args):
            mod = args[i + 1]
            break
    if mod is None:
        # Scripts like "python …/wims/log/app.py" — rare; skip rather than guess.
        if "wims.server" in low or "/wims/server" in low.replace("\\", "/"):
            return "server"
        return "other"

    # Top-level CLI: python -m wims <role> …
    if mod == "wims":
        # Find the role token after -m wims.
        role = None
        for i, a in enumerate(args):
            if a == "-m" and i + 1 < len(args) and args[i + 1] == "wims":
                if i + 2 < len(args):
                    role = args[i + 2]
                break
        if role in (None, "gui", "launcher", "help", "version", "-h", "--help"):
            return "other"  # this is the desktop launcher / meta
        if role == "log":
            return "log"
        if role == "seat":
            return "n1mm_seat"
        if role == "agent" and "--daemon" in args:
            return "seat"
        if role == "key" and "daemon" in args:
            return "key"
        if role == "server":
            return "server"
        return "other"

    if mod in ("wims.seat", "wims.seat.app"):
        return "n1mm_seat"
    if mod in ("wims.log", "wims.log.app"):
        return "log"
    if mod in ("wims.agent", "wims.agent.app"):
        # Long-running seat monitor only — not one-shot checks.
        if "--daemon" in args:
            return "seat"
        return "other"
    if mod in ("wims.key", "wims.key.app"):
        # Product daemon / seat --key wrapper; not selftest/gate/lab agent.
        if "daemon" in args or "--key" in args:
            return "key"
        return "other"
    if mod in ("wims.server", "wims.server.app"):
        return "server"
    if mod in ("wims.launcher", "wims.launcher.app"):
        return "other"
    return "other"


def _linux_proc_table() -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    proc = "/proc"
    try:
        names = os.listdir(proc)
    except OSError:
        return rows
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            raw = open(f"{proc}/{pid}/cmdline", "rb").read()  # noqa: SIM115
        except OSError:
            continue
        if not raw:
            continue
        parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
        if parts:
            rows.append((pid, parts))
    return rows


def _linux_ps_table() -> list[tuple[int, list[str]]]:
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid=,args="],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[int, list[str]]] = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            pid_s, args = s.split(None, 1)
            pid = int(pid_s)
        except ValueError:
            continue
        rows.append((pid, args.split()))
    return rows


def _windows_wmic_table() -> list[tuple[int, list[str]]]:
    # Prefer WMIC for CommandLine; fall back empty if unavailable.
    try:
        out = subprocess.check_output(
            [
                "wmic", "process", "where",
                "name='python.exe' or name='pythonw.exe' or name='python3.exe'",
                "get", "ProcessId,CommandLine", "/FORMAT:CSV",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return _windows_powershell_table()
    rows: list[tuple[int, list[str]]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("NODE,") or "CommandLine" in line and "ProcessId" in line:
            # header-ish
            if line.upper().startswith("NODE,"):
                continue
        # CSV: Node,CommandLine,ProcessId  (order can vary)
        # WMIC CSV often: Node,CommandLine,ProcessId
        parts = _csv_split(line)
        if len(parts) < 3:
            continue
        # Last field is usually ProcessId
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        cmdline = parts[-2] if len(parts) >= 2 else ""
        if not cmdline or cmdline.lower() == "commandline":
            continue
        rows.append((pid, _split_cmdline(cmdline)))
    return rows


def _windows_powershell_table() -> list[tuple[int, list[str]]]:
    ps = (
        "Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' OR Name='pythonw.exe' OR Name='python3.exe'\" | "
        "ForEach-Object { '{0}\t{1}' -f $_.ProcessId, $_.CommandLine }"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[int, list[str]]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        pid_s, cmdline = line.split("\t", 1)
        try:
            pid = int(pid_s.strip())
        except ValueError:
            continue
        cmdline = cmdline.strip()
        if not cmdline:
            continue
        rows.append((pid, _split_cmdline(cmdline)))
    return rows


def _csv_split(line: str) -> list[str]:
    """Minimal CSV split for WMIC (handles quoted commas)."""
    out: list[str] = []
    cur: list[str] = []
    in_q = False
    for ch in line:
        if ch == '"':
            in_q = not in_q
            continue
        if ch == "," and not in_q:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur))
    return out


def _split_cmdline(cmdline: str) -> list[str]:
    """Best-effort argv split (Windows CommandLine is one string)."""
    try:
        import shlex
        # shlex handles quotes; on Windows paths with spaces need posix=False.
        return shlex.split(cmdline, posix=os.name != "nt")
    except ValueError:
        return cmdline.split()


_PROC_TABLE_TTL_S = 4.0
_proc_table_ts: float = 0.0
_proc_table: list[tuple[int, list[str]]] | None = None


def list_process_table(*, fresh: bool = False) -> list[tuple[int, list[str]]]:
    """Return (pid, argv) for candidate processes on this host.

    Cached briefly: the launcher used to spawn wmic/PowerShell on every
    Running-list refresh (UI thread), which made start + idle feel frozen.
    """
    global _proc_table_ts, _proc_table
    now = time.monotonic()
    if (
        not fresh
        and _proc_table is not None
        and (now - _proc_table_ts) < _PROC_TABLE_TTL_S
    ):
        return _proc_table
    if os.name == "nt":
        # PowerShell CIM first — WMIC is missing/slow on many Win11 images.
        rows = _windows_powershell_table()
        if not rows:
            rows = _windows_wmic_table()
    else:
        rows = _linux_proc_table()
        if not rows:
            rows = _linux_ps_table()
    _proc_table = rows
    _proc_table_ts = now
    return rows


def iter_wims_procs(
    table: Iterable[tuple[int, list[str]]] | None = None,
    *,
    exclude_pids: Iterable[int] | None = None,
) -> list[ProcInfo]:
    """All classifiable WIMS-related python processes (including server)."""
    excl = {os.getpid(), *(exclude_pids or ())}
    # Also exclude parent if we are a child (rare for launcher).
    try:
        excl.add(os.getppid())
    except OSError:
        pass
    raw = list(table) if table is not None else list_process_table()
    out: list[ProcInfo] = []
    for pid, argv in raw:
        if pid in excl:
            continue
        kind = classify_argv(argv)
        if kind == "other":
            continue
        out.append(ProcInfo(
            pid=pid,
            argv=list(argv),
            kind=kind,
            cmdline=" ".join(argv)[:200],
        ))
    return out


def find_procs_by_kind(
    kind: Kind,
    *,
    table: Iterable[tuple[int, list[str]]] | None = None,
    exclude_pids: Iterable[int] | None = None,
) -> list[ProcInfo]:
    """Return processes of one kind (log / seat / key / server)."""
    return [
        p for p in iter_wims_procs(table, exclude_pids=exclude_pids)
        if p.kind == kind
    ]


def other_agent_running(kind: Kind) -> ProcInfo | None:
    """Return another process of ``kind`` if any (excludes this PID / parent)."""
    found = find_procs_by_kind(kind)
    return found[0] if found else None


def _terminate_pid(pid: int) -> None:
    if os.name == "nt":
        # taskkill is clearer than os.kill on Windows python services.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    os.kill(pid, signal.SIGTERM)


def _kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    os.kill(pid, signal.SIGKILL)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid) in out and "INFO:" not in out.upper()
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def stop_pid(
    pid: int,
    *,
    grace_s: float = 1.5,
    terminate: Callable[[int], None] | None = None,
    force_kill: Callable[[int], None] | None = None,
    alive: Callable[[int], bool] | None = None,
) -> None:
    """SIGTERM/taskkill, wait, then force if needed."""
    term = terminate or _terminate_pid
    kill = force_kill or _kill_pid
    is_alive = alive or _pid_alive
    try:
        term(pid)
    except ProcessLookupError:
        return
    except OSError as e:
        # Still try force below.
        if not is_alive(pid):
            return
        raise OSError(f"terminate failed: {e}") from e
    deadline = time.monotonic() + max(0.2, grace_s)
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return
        time.sleep(0.1)
    if is_alive(pid):
        kill(pid)
        time.sleep(0.2)


def replace_seat_agents(
    *,
    table: Iterable[tuple[int, list[str]]] | None = None,
    exclude_pids: Iterable[int] | None = None,
    stop: Callable[..., None] | None = None,
    grace_s: float = 1.5,
    dry_run: bool = False,
) -> ReplaceReport:
    """Stop leftover log/seat/key agents; never stop site server.

    ``table`` / ``stop`` are injectable for unit tests.
    """
    procs = iter_wims_procs(table, exclude_pids=exclude_pids)
    report = ReplaceReport(found=list(procs))
    stopper = stop or (lambda pid, **kw: stop_pid(pid, grace_s=grace_s, **kw))

    for p in procs:
        if p.kind == "server":
            report.skipped_server.append(p)
            continue
        if p.kind not in _SEAT_KINDS:
            continue
        if dry_run:
            report.stopped.append(p)
            continue
        try:
            stopper(p.pid)
            report.stopped.append(p)
        except Exception as e:  # noqa: BLE001 — surface per-pid failure
            report.failed.append((p, str(e)))
    return report


def format_replace_banner(report: ReplaceReport) -> tuple[str, str]:
    """Return (banner_level, short message) for the launcher."""
    if report.failed:
        return "warn", "Could not replace some seat agents — see Details"
    n = len(report.stopped)
    if n:
        return "busy", f"Replaced {n} leftover seat agent(s)"
    return "busy", "Seat agents clear"
