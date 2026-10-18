# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ask the running WIMS window to come forward.

The process that owns the launcher lock listens on 127.0.0.1 and writes
``launcher.raise`` next to ``launcher.lock`` (port and a token). A second
start connects, sends the token, and exits. The window is un-minimized,
raised, and focused on the Tk thread. No site console is opened.

If nothing answers, the caller shows a plain-language message.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from pathlib import Path

# How long a second start waits for the window to answer.
REQUEST_TIMEOUT_S = 4.0
# No port file yet: the owner is still starting, or this is an older copy.
_MISSING_FILE_S = 0.8
# The listener waits longer than the client so a slow Tk thread can still ack.
_HANDSHAKE_WAIT_S = 8.0
# The window polls this often. A double-click feels immediate.
RAISE_POLL_MS = 150
_TOPMOST_MS = 200
_CMD = "raise"


class _Ticket:
    def __init__(self) -> None:
        self._done = threading.Event()
        self._lock = threading.Lock()
        self.ok = False

    def finish(self, ok: bool) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self.ok = bool(ok)
            self._done.set()

    def wait(self, timeout: float) -> bool:
        self._done.wait(timeout)
        return self.ok


class _RaiseServer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.token = secrets.token_hex(16)
        self._sock: socket.socket | None = None
        self._port = 0
        self._lock = threading.Lock()
        self._pending: list[_Ticket] = []
        self._clients: list[socket.socket] = []
        self._handlers: list[threading.Thread] = []
        self._stopped = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            sock.listen(8)
            sock.settimeout(0.3)
            _set_nodelay(sock)
        except OSError:
            sock.close()
            return False
        self._sock = sock
        self._port = int(sock.getsockname()[1])
        try:
            _publish(self.path, self._port, self.token)
        except OSError:
            sock.close()
            self._sock = None
            return False
        self._thread = threading.Thread(
            target=self._accept_loop, name="wims-launcher-raise", daemon=True,
        )
        self._thread.start()
        return True

    def address(self) -> tuple[str, int] | None:
        sock = self._sock
        if sock is None:
            return None
        host, port = sock.getsockname()[:2]
        return str(host), int(port)

    def submit(self, ticket: _Ticket) -> None:
        with self._lock:
            if self._stopped:
                ticket.finish(False)
                return
            self._pending.append(ticket)

    def drain(self) -> list[_Ticket]:
        with self._lock:
            items = self._pending
            self._pending = []
        return items

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            pending = self._pending
            self._pending = []
            clients = list(self._clients)
            sock = self._sock
            self._sock = None
        for ticket in pending:
            ticket.finish(False)
        for conn in clients:
            _close(conn)
        if sock is not None:
            _close(sock)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        for handler in list(self._handlers):
            if handler is not threading.current_thread():
                handler.join(timeout=0.5)
        _remove_if_ours(self.path, self.token)

    def _accept_loop(self) -> None:
        while True:
            with self._lock:
                if self._stopped:
                    return
                sock = self._sock
            if sock is None:
                return
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            host = addr[0] if isinstance(addr, tuple) and addr else ""
            if host != "127.0.0.1":
                _close(conn)
                continue
            _set_nodelay(conn)
            with self._lock:
                if self._stopped:
                    _close(conn)
                    return
                self._clients.append(conn)
                worker = threading.Thread(
                    target=self._handle, args=(conn,), daemon=True,
                )
                self._handlers.append(worker)
            worker.start()

    def _handle(self, conn: socket.socket) -> None:
        ticket: _Ticket | None = None
        try:
            conn.settimeout(1.0)
            data = b""
            while b"\n" not in data and len(data) < 80:
                chunk = conn.recv(80)
                if not chunk:
                    return
                data += chunk
            line = data.decode("ascii", "replace").strip()
            if line != f"{_CMD} {self.token}":
                return
            ticket = _Ticket()
            self.submit(ticket)
            if ticket.wait(_HANDSHAKE_WAIT_S) and ticket.ok:
                conn.sendall(b"ok\n")
            else:
                ticket.finish(False)
        except OSError:
            if ticket is not None:
                ticket.finish(False)
        finally:
            _close(conn)
            with self._lock:
                try:
                    self._clients.remove(conn)
                except ValueError:
                    pass


_guard = threading.Lock()
_server: _RaiseServer | None = None


def raise_endpoint_path() -> Path:
    """``launcher.raise`` beside the launcher lock file."""
    from wims.launcher.singleton import _lock_path

    return _lock_path().with_name("launcher.raise")


def start_raise_server() -> bool:
    """Listen on localhost and publish the port. Idempotent.

    False means this process could not listen. The window still opens;
    a later double-click then says the window did not answer.
    """
    global _server
    with _guard:
        if _server is not None:
            return _server.address() is not None
        server = _RaiseServer(raise_endpoint_path())
        if not server.start():
            return False
        _server = server
        return True


def stop_raise_server() -> None:
    """Close the listener and remove the port file if it is still ours."""
    global _server
    with _guard:
        server = _server
        _server = None
    if server is not None:
        server.stop()


def raise_server_address() -> tuple[str, int] | None:
    """``(host, port)`` of this process's listener, if it is up."""
    with _guard:
        server = _server
    if server is None:
        return None
    return server.address()


def pending_raise_count() -> int:
    with _guard:
        server = _server
    if server is None:
        return 0
    return server.pending()


def request_running_launcher(*, timeout: float = REQUEST_TIMEOUT_S) -> bool:
    """Ask the running launcher to show its window.

    True when it answered ``ok``. False when no listener is published, the
    connection fails, or the window does not answer before ``timeout``.
    """
    deadline = time.monotonic() + max(0.05, float(timeout))
    miss_deadline = time.monotonic() + min(_MISSING_FILE_S, float(timeout))
    seen = False
    while True:
        now = time.monotonic()
        if now >= deadline:
            return False
        if not seen and now >= miss_deadline:
            return False
        found = _read_endpoint()
        if found is None:
            _pause(deadline)
            continue
        seen = True
        port, token = found
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            conn = socket.create_connection(
                ("127.0.0.1", port), timeout=max(0.05, min(0.5, remaining)),
            )
        except OSError:
            _pause(deadline)
            continue
        try:
            _set_nodelay(conn)
            conn.settimeout(max(0.05, deadline - time.monotonic()))
            conn.sendall(f"{_CMD} {token}\n".encode("ascii"))
            buf = b""
            while b"\n" not in buf and len(buf) < 32:
                chunk = conn.recv(32)
                if not chunk:
                    break
                buf += chunk
            if buf.strip() == b"ok":
                return True
        except socket.timeout:
            return False
        except OSError:
            pass
        finally:
            _close(conn)
        _pause(deadline)


def service_raise_requests(root) -> int:
    """Present ``root`` for every queued request and acknowledge them.

    Call from the Tk thread. Returns how many requests were acknowledged.
    """
    with _guard:
        server = _server
    if server is None:
        return 0
    tickets = server.drain()
    if not tickets:
        return 0
    try:
        present_launcher_window(root)
    except Exception:
        for ticket in tickets:
            ticket.finish(False)
        return 0
    for ticket in tickets:
        ticket.finish(True)
    return len(tickets)


def present_launcher_window(root, *, topmost_ms: int = _TOPMOST_MS) -> None:
    """Un-minimize, raise, and focus. Topmost is only a brief toggle."""
    root.deiconify()
    root.lift()
    try:
        root.focus_force()
    except Exception:
        pass
    try:
        root.attributes("-topmost", True)
    except Exception:
        return
    update = getattr(root, "update_idletasks", None)
    if callable(update):
        try:
            update()
        except Exception:
            pass

    def _drop_topmost() -> None:
        try:
            root.attributes("-topmost", False)
        except Exception:
            pass
        try:
            root.lift()
        except Exception:
            pass
        try:
            root.focus_force()
        except Exception:
            pass

    try:
        root.after(max(0, int(topmost_ms)), _drop_topmost)
    except Exception:
        _drop_topmost()


def _read_endpoint() -> tuple[int, str] | None:
    path = raise_endpoint_path()
    try:
        text = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    parts = text.split()
    if len(parts) != 2 or not parts[0].isdigit():
        return None
    port = int(parts[0])
    token = parts[1]
    if not 1 <= port <= 65535:
        return None
    if not token or len(token) > 80 or any(ch not in "0123456789abcdef" for ch in token):
        return None
    return port, token


def _publish(path: Path, port: int, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = f"{port} {token}\n".encode("ascii")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _remove_if_ours(path: Path, token: str) -> None:
    try:
        text = path.read_text(encoding="ascii")
    except OSError:
        return
    if token and token in text.split():
        try:
            path.unlink()
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.unlink()
    except OSError:
        pass


def _pause(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(0.05, remaining))


def _set_nodelay(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass


def _close(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass
