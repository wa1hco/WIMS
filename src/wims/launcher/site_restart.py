# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restart the WIMS site server on this PC, and leave every other PC alone.

A launcher only starts or restarts a server on its own machine. Restart may
stop a process only when both of these are true:

* ``/healthz`` answers with role ``wims-site-server``
* the process id is a local process, from the pid file in the WIMS state
  directory or from the local port owner, and that process is WIMS

A server on another PC is refused. The window names that PC and leaves
Restart needed up. A process that is not WIMS is left alone. After a stop
that did happen, the window starts the site server the usual way and waits
until ``server_rev`` matches the checkout.

Plane E (one announcing site server on the LAN), the port check in Operate,
and the launcher handoff are separate and are not changed here.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wims.launcher.server_rev import RESTART_NEEDED_MARK, revision_token

# Same directory as the other per-user WIMS files (last log, launcher lock).
PID_FILENAME = "site-server.pid"
SITE_ROLE = "wims-site-server"

RESTARTING_TITLE = "Restarting site server"
RESTARTING_DETAIL = (
    "Stopping the copy on this PC, then starting the installed one."
)
RESTARTED_DETAIL = "The site server is running the installed copy."
FAILED_DETAIL = (
    "Try Restart site server again. The previous copy was left as it was."
)

NOT_WIMS_MESSAGE = (
    "That port is not the WIMS site server, so it was left running."
)
NOT_WIMS_PROCESS_MESSAGE = (
    "The process on this port did not look like WIMS, so it was left running."
)
NOT_IDENTIFIED_MESSAGE = (
    "The site server answered, but its process could not be identified, "
    "so it was left running."
)
STILL_RUNNING_MESSAGE = (
    "The site server did not stop. It is still the previous copy."
)
DID_NOT_COME_UP_MESSAGE = (
    "The site server stopped, but the new one did not come up."
)
STILL_OLD_MESSAGE = (
    "The site server came back, but it is still not the installed copy."
)


def other_pc_message(host: str) -> str:
    """What to say when the site server is not on this PC."""
    name = (host or "").strip() or "another PC"
    return f"The site server is running on {name}. Restart it on that PC."

_SERVER_MODULES = frozenset({
    "wims.server",
    "wims.server.app",
    "wims.solo",
})
_SERVER_ROLES = frozenset({"server", "solo"})


def restarted_message(rev: str) -> str:
    """Status line after ``server_rev`` matches the checkout."""
    return f"Restarted on {rev}"


def client_is_loopback(host: str | None) -> bool:
    """True for a connection that arrived from this machine."""
    text = (host or "").strip().lower()
    if text.startswith("::ffff:"):
        text = text[7:]
    if text in {"::1", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def shutdown_status(client_host: str | None) -> int:
    """HTTP status for ``/shutdown``. Only loopback is accepted."""
    if client_is_loopback(client_host):
        return 200
    return 403


def handle_shutdown_request(handler) -> bool:
    """Answer ``/shutdown``. Return True when this process should exit.

    A browser on another PC is refused. The console there reconnects after
    a restart that this PC asked for; it cannot ask on its own.
    """
    host = ""
    try:
        addr = handler.client_address
        if addr:
            host = addr[0]
    except Exception:
        host = ""
    if shutdown_status(host) != 200:
        handler._send_json(403, {"ok": False})
        return False
    handler._send_json(200, {"ok": True})
    return True


def site_server_pid_path(path: Path | str | None = None) -> Path:
    """Pid file in the WIMS state directory, unless ``path`` is given.

    ``WIMS_SITE_SERVER_PID`` overrides the directory lookup for tests.
    An explicit ``path`` wins over the environment variable.
    """
    if path is not None and str(path).strip():
        return Path(path)
    env = (os.environ.get("WIMS_SITE_SERVER_PID") or "").strip()
    if env:
        return Path(env)
    from wims.rules.choice import config_dir
    return config_dir() / PID_FILENAME


def write_site_server_pid(
    pid: int,
    port: int,
    path: Path | str | None = None,
) -> Path:
    """Record the listening site server. Replaced atomically."""
    dest = site_server_pid_path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid),
        "port": int(port),
        "role": SITE_ROLE,
    }
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def read_site_server_pid(
    path: Path | str | None = None,
) -> tuple[int, int] | None:
    """Return ``(pid, port)`` or None when the file is missing or not ours."""
    dest = site_server_pid_path(path)
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("role") != SITE_ROLE:
        return None
    try:
        pid = int(data["pid"])
        port = int(data["port"])
    except (KeyError, TypeError, ValueError):
        return None
    if pid <= 0 or port <= 0:
        return None
    return pid, port


def clear_site_server_pid(
    path: Path | str | None = None,
    *,
    pid: int | None = None,
) -> None:
    """Remove the pid file. A different pid is left in place.

    The process that is exiting must not delete a file a newer server has
    already written.
    """
    dest = site_server_pid_path(path)
    if pid is not None:
        current = read_site_server_pid(dest)
        if current is None or current[0] != int(pid):
            return
    try:
        dest.unlink()
    except OSError:
        pass


def is_wims_site_server_argv(argv: list[str] | None) -> bool:
    """True for the site server process (``wims.server`` or ``wims.solo``)."""
    args = [a for a in (argv or []) if a]
    if not args:
        return False
    mod = None
    mod_at = -1
    for i, arg in enumerate(args):
        if arg == "-m" and i + 1 < len(args):
            mod = args[i + 1]
            mod_at = i
            break
    if mod in _SERVER_MODULES:
        return True
    if mod == "wims" and mod_at >= 0 and mod_at + 2 < len(args):
        return args[mod_at + 2] in _SERVER_ROLES
    low = " ".join(args).lower().replace("\\", "/")
    if "wims.server" in low or "wims.solo" in low:
        return True
    if "/wims/server/" in low or low.rstrip().endswith("/wims/server"):
        return True
    if "/wims/solo.py" in low or low.rstrip().endswith("/wims/solo.py"):
        return True
    return False


def parse_proc_net_inodes(text: str, port: int) -> list[str]:
    """Inode numbers of LISTEN rows for ``port`` in ``/proc/net/tcp`` text."""
    want = f"{int(port):04X}"
    found: list[str] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[0].endswith(":"):
            # Header, or ``sl`` column like ``0:``.
            if len(parts) < 10:
                continue
        local = parts[1]
        state = parts[3]
        if ":" not in local:
            continue
        hexport = local.rsplit(":", 1)[1]
        if hexport.upper() != want or state.upper() != "0A":
            continue
        inode = parts[9]
        if inode.isdigit() and inode not in found:
            found.append(inode)
    return found


def _local_port_is(local: str, port: int) -> bool:
    text = (local or "").strip()
    if text.startswith("["):
        if "]:" not in text:
            return False
        got = text.rsplit("]:", 1)[1]
    else:
        if ":" not in text:
            return False
        got = text.rsplit(":", 1)[1]
    return got == str(int(port))


def parse_netstat_listeners(text: str, port: int) -> list[int]:
    """PIDs from ``netstat -ano`` lines that are LISTENING on ``port``."""
    found: list[int] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or "LISTENING" not in raw.upper():
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        if not _local_port_is(parts[1], port):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in found:
            found.append(pid)
    return found


def _linux_listening_pids(port: int) -> list[int]:
    inodes: list[str] = []
    for name in ("tcp", "tcp6"):
        try:
            text = Path(f"/proc/net/{name}").read_text(
                encoding="utf-8", errors="replace",
            )
        except OSError:
            continue
        for inode in parse_proc_net_inodes(text, port):
            if inode not in inodes:
                inodes.append(inode)
    if not inodes:
        return []
    want = {f"socket:[{inode}]" for inode in inodes}
    found: list[int] = []
    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        matched = False
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target in want:
                matched = True
                break
        if matched:
            pid = int(entry.name)
            if pid not in found:
                found.append(pid)
    return found


def _windows_powershell_listeners(port: int) -> list[int]:
    script = (
        f"Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
        "-ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.OwningProcess }"
    )
    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-Command", script,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    found: list[int] = []
    for line in out.splitlines():
        text = line.strip()
        if not text.isdigit():
            continue
        pid = int(text)
        if pid > 0 and pid not in found:
            found.append(pid)
    return found


def _windows_netstat_listeners(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return parse_netstat_listeners(out, port)


def listening_pids(port: int) -> list[int]:
    """Process ids listening on TCP ``port`` on this machine.

    Linux reads ``/proc``. Windows asks PowerShell, then ``netstat``.
    An empty list means the lookup did not find one (the pid file is the
    other way to identify the server).
    """
    try:
        if os.name == "nt":
            found = _windows_powershell_listeners(port)
            if found:
                return found
            return _windows_netstat_listeners(port)
        if Path("/proc/net/tcp").is_file():
            return _linux_listening_pids(port)
    except Exception:
        return []
    return []


def read_process_argv(pid: int) -> list[str] | None:
    """Command line for ``pid``, or None when it cannot be read."""
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            from wims.launcher.process_replace import list_process_table
            for found, argv in list_process_table(fresh=True):
                if int(found) == int(pid):
                    return list(argv)
        except Exception:
            return None
        return None
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    parts = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
    return parts or None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            from wims.launcher.process_replace import _pid_alive
            return bool(_pid_alive(int(pid)))
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tcp_open(port: int, *, timeout: float = 0.4) -> bool:
    """True when something accepts TCP on ``127.0.0.1:port``."""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


@dataclass(frozen=True)
class IdentifyResult:
    """Process ids that are safe to stop, or a reason there are none."""

    pids: tuple[int, ...] = ()
    source: str = ""
    reason: str = ""


def _accept_pid(
    pid: int,
    *,
    from_port: bool,
    argv_of: Callable[[int], list[str] | None],
) -> bool | None:
    """True = WIMS site server, False = some other program, None = unknown.

    A listener whose command line cannot be read is still the process that
    answered ``/healthz``. A pid-file number with no command line is not
    trusted: the id may have been reused.
    """
    try:
        argv = argv_of(int(pid))
    except Exception:
        argv = None
    if argv is None:
        return True if from_port else None
    if is_wims_site_server_argv(argv):
        return True
    return False


def identify_site_server(
    *,
    health: dict | None,
    port: int,
    listener_pids: list[int] | None = None,
    pid_file: tuple[int, int] | None = None,
    argv_of: Callable[[int], list[str] | None] | None = None,
    alive: Callable[[int], bool] | None = None,
) -> IdentifyResult:
    """PID of the WIMS site server on ``port``, or a refusal.

    ``health`` is the ``/healthz`` body. ``listener_pids`` is who owns the
    port (injected in tests; otherwise pass None and the OS is asked).
    ``pid_file`` is ``(pid, port)`` from the state directory.
    """
    if not _is_site_health(health):
        return IdentifyResult(reason="not-wims")
    argv_lookup = argv_of or read_process_argv
    is_alive = alive or pid_alive
    if listener_pids is None:
        try:
            listeners = list(listening_pids(int(port)))
        except Exception:
            listeners = []
    else:
        listeners = list(listener_pids)

    accepted: list[int] = []
    saw_other = False
    saw_port = False
    for raw in listeners:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        saw_port = True
        try:
            living = bool(is_alive(pid))
        except Exception:
            living = True
        if not living:
            continue
        verdict = _accept_pid(pid, from_port=True, argv_of=argv_lookup)
        if verdict is True and pid not in accepted:
            accepted.append(pid)
        elif verdict is False:
            saw_other = True
    claimed = _claimed_pid(health)
    if accepted:
        if claimed and claimed not in accepted:
            # /healthz named a different process than the port owner.
            # Do not kill either one.
            return IdentifyResult(reason="no-pid")
        if claimed:
            accepted = [pid for pid in accepted if pid == claimed]
        return IdentifyResult(pids=tuple(accepted), source="port")
    if saw_port and saw_other:
        # The port lookup named a process, and it is not WIMS. Do not fall
        # through to a pid file that might name something else.
        return IdentifyResult(reason="not-wims-process")
    if saw_port and not accepted:
        # Listeners were listed and none of them could be confirmed.
        return IdentifyResult(reason="no-pid")

    file_pid = 0
    if pid_file is not None:
        try:
            file_pid = int(pid_file[0])
            file_port = int(pid_file[1])
        except (TypeError, ValueError, IndexError):
            file_pid = 0
            file_port = 0
        if file_port != int(port):
            file_pid = 0
    if file_pid <= 0:
        return IdentifyResult(reason="no-pid")
    if claimed and file_pid != claimed:
        return IdentifyResult(reason="no-pid")
    try:
        living = bool(is_alive(file_pid))
    except Exception:
        living = False
    if not living:
        return IdentifyResult(reason="no-pid")
    verdict = _accept_pid(file_pid, from_port=False, argv_of=argv_lookup)
    if verdict is True:
        return IdentifyResult(pids=(file_pid,), source="pidfile")
    if verdict is False:
        return IdentifyResult(reason="not-wims-process")
    return IdentifyResult(reason="no-pid")


def _claimed_pid(health: dict | None) -> int:
    """PID the server reported, or 0 when this build did not say."""
    if not isinstance(health, dict):
        return 0
    try:
        pid = int(health.get("pid"))
    except (TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


def _is_site_health(health: dict | None) -> bool:
    return (
        isinstance(health, dict)
        and bool(health.get("ok"))
        and health.get("role") == SITE_ROLE
    )


def health_server_rev(health: dict | None) -> str:
    if not _is_site_health(health):
        return ""
    raw = health.get("server_rev") if isinstance(health, dict) else None
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def revisions_match(disk_rev: str | None, server_rev: str | None) -> bool:
    disk = revision_token(disk_rev)
    server = revision_token(server_rev)
    return bool(disk and server and disk == server)


def _until(
    pred: Callable[[], bool],
    *,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> bool:
    deadline = monotonic() + max(0.0, timeout_s)
    while True:
        try:
            done = bool(pred())
        except Exception:
            done = False
        if done:
            return True
        if monotonic() >= deadline:
            return False
        sleep(interval_s)


def request_shutdown(port: int, *, timeout: float = 2.0) -> bool:
    """POST ``/shutdown`` on loopback. False when the server declines or is gone."""
    url = f"http://127.0.0.1:{int(port)}/shutdown"
    req = Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — loopback only
            raw = resp.read(4096)
            code = getattr(resp, "status", 200)
    except HTTPError:
        return False
    except (URLError, OSError, TimeoutError, ValueError):
        return False
    if int(code) != 200:
        return False
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and bool(data.get("ok"))


def _default_stop(pid: int) -> None:
    from wims.launcher.process_replace import stop_pid
    stop_pid(int(pid), grace_s=2.0)


def _say(on_log: Callable[[str], None] | None, text: str) -> None:
    if on_log is None:
        return
    try:
        on_log(text)
    except Exception:
        pass


@dataclass(frozen=True)
class RestartOutcome:
    ok: bool
    message: str
    rev: str = ""
    stopped: bool = False


def banner_for_restart(
    *,
    in_progress: bool,
    message: str | None,
    ok: bool,
    stale: bool,
) -> tuple[str, str, str] | None:
    """Banner while a restart is in flight or has a result to show.

    None lets the ordinary status line (including Restart needed) show.
    A finished attempt owns the line so the old mark is not the only thing
    left on screen.
    """
    if in_progress:
        return ("busy", RESTARTING_TITLE, RESTARTING_DETAIL)
    text = (message or "").strip()
    if not text:
        return None
    if ok and not stale:
        return ("ok", text, RESTARTED_DETAIL)
    if not ok and stale:
        # The mark stays. The sentence says why this window did not restart.
        return ("warn", RESTART_NEEDED_MARK, text)
    if not ok:
        return ("err", text, FAILED_DETAIL)
    return None


def perform_site_restart(
    *,
    port: int,
    disk_rev: str | None,
    fetch_health: Callable[[], dict | None],
    start_server: Callable[[], None],
    request_stop: Callable[[], bool] | None = None,
    stop_pid: Callable[[int], None] | None = None,
    listener_pids: list[int] | None = None,
    pid_file: tuple[int, int] | None = None,
    read_pid_file: Callable[[], tuple[int, int] | None] | None = None,
    argv_of: Callable[[int], list[str] | None] | None = None,
    alive: Callable[[int], bool] | None = None,
    port_open: Callable[[], bool] | None = None,
    on_log: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    stop_timeout_s: float = 3.0,
    rev_timeout_s: float = 25.0,
    interval_s: float = 0.2,
    on_this_pc: bool = True,
    other_host: str = "",
) -> RestartOutcome:
    """Stop the local site server, start it again, and check the revision.

    ``on_this_pc`` is false when the console URL is another machine. Nothing
    is stopped or started in that case. Callers inject the OS and HTTP edges
    in tests. The defaults talk to ``127.0.0.1``.
    """
    if not on_this_pc:
        message = other_pc_message(other_host)
        _say(on_log, message)
        return RestartOutcome(False, message)
    pause = sleep or time.sleep
    clock = monotonic or time.monotonic
    ask_stop = request_stop or (lambda: request_shutdown(int(port)))
    terminate = stop_pid or _default_stop
    is_open = port_open or (lambda: tcp_open(int(port)))
    if pid_file is None and read_pid_file is not None:
        try:
            pid_file = read_pid_file()
        except Exception:
            pid_file = None
    elif pid_file is None and read_pid_file is None:
        pid_file = read_site_server_pid()

    def health_up() -> bool:
        try:
            return _is_site_health(fetch_health())
        except Exception:
            return False

    def wait_until_down() -> bool:
        return _until(
            lambda: not health_up(),
            timeout_s=stop_timeout_s,
            interval_s=interval_s,
            sleep=pause,
            monotonic=clock,
        )

    def wait_until_closed() -> bool:
        return _until(
            lambda: not _call_open(is_open),
            timeout_s=stop_timeout_s,
            interval_s=interval_s,
            sleep=pause,
            monotonic=clock,
        )

    if not health_up():
        if _call_open(is_open):
            _say(on_log, NOT_WIMS_MESSAGE)
            return RestartOutcome(False, NOT_WIMS_MESSAGE)
        _say(on_log, "No site server on this port. Starting one.")
        return _start_and_confirm(
            disk_rev=disk_rev,
            fetch_health=fetch_health,
            start_server=start_server,
            on_log=on_log,
            pause=pause,
            clock=clock,
            rev_timeout_s=rev_timeout_s,
            interval_s=interval_s,
            stopped=False,
        )

    found = identify_site_server(
        health=fetch_health(),
        port=int(port),
        listener_pids=listener_pids,
        pid_file=pid_file,
        argv_of=argv_of,
        alive=alive,
    )
    if not found.pids:
        message = (
            NOT_WIMS_PROCESS_MESSAGE
            if found.reason == "not-wims-process"
            else NOT_IDENTIFIED_MESSAGE
        )
        _say(on_log, message)
        return RestartOutcome(False, message)
    _say(on_log, "Asking the site server to stop.")
    try:
        ask_stop()
    except Exception as exc:
        _say(on_log, f"Shutdown request failed: {exc}")
    if not wait_until_down() or not wait_until_closed():
        for pid in found.pids:
            _say(on_log, f"Stopping site server pid={pid}.")
            try:
                terminate(int(pid))
            except Exception as exc:
                _say(on_log, f"Stop pid {pid} failed: {exc}")
        if not wait_until_down() or not wait_until_closed():
            _say(on_log, STILL_RUNNING_MESSAGE)
            return RestartOutcome(False, STILL_RUNNING_MESSAGE, stopped=False)

    return _start_and_confirm(
        disk_rev=disk_rev,
        fetch_health=fetch_health,
        start_server=start_server,
        on_log=on_log,
        pause=pause,
        clock=clock,
        rev_timeout_s=rev_timeout_s,
        interval_s=interval_s,
        stopped=True,
    )


def _call_open(is_open: Callable[[], bool]) -> bool:
    try:
        return bool(is_open())
    except Exception:
        return False


def _start_and_confirm(
    *,
    disk_rev: str | None,
    fetch_health: Callable[[], dict | None],
    start_server: Callable[[], None],
    on_log: Callable[[str], None] | None,
    pause: Callable[[float], None],
    clock: Callable[[], float],
    rev_timeout_s: float,
    interval_s: float,
    stopped: bool,
) -> RestartOutcome:
    _say(on_log, "Starting the site server.")
    try:
        start_server()
    except Exception as exc:
        _say(on_log, f"Start failed: {exc}")
        return RestartOutcome(False, DID_NOT_COME_UP_MESSAGE, stopped=stopped)

    state = {"saw_other": False, "rev": ""}

    def matched() -> bool:
        try:
            health = fetch_health()
        except Exception:
            return False
        rev = health_server_rev(health)
        if not rev:
            return False
        if revisions_match(disk_rev, rev):
            state["rev"] = revision_token(rev)
            return True
        state["saw_other"] = True
        state["rev"] = revision_token(rev)
        return False

    ok = _until(
        matched,
        timeout_s=rev_timeout_s,
        interval_s=interval_s,
        sleep=pause,
        monotonic=clock,
    )
    if ok and state["rev"]:
        message = restarted_message(state["rev"])
        _say(on_log, message)
        return RestartOutcome(True, message, state["rev"], stopped=stopped)
    if state["saw_other"]:
        _say(on_log, STILL_OLD_MESSAGE)
        return RestartOutcome(
            False, STILL_OLD_MESSAGE, state["rev"], stopped=stopped,
        )
    _say(on_log, DID_NOT_COME_UP_MESSAGE)
    return RestartOutcome(False, DID_NOT_COME_UP_MESSAGE, stopped=stopped)
