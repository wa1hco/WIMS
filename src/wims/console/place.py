# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Where the site console window opens on this PC.

The launcher and ``wims.solo`` open one console window on the machine they
are running on. A browser on another PC still opens the console URL itself
and is not part of this placement.

Geometry is one saved spot for this PC. A report is stored only when it
comes from a loopback (or this PC's own address) page that the launcher
marked as the placed console. A remote report cannot replace that spot.

Reuse counts only pages connected from this PC. A remote viewer being
connected does not stop this PC from opening its window. A reload signal
is attached only to those local live updates, so a remote page does not
reload when this PC's console does.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

# A local page that pinged more recently than this is still open.
PING_WINDOW_S = 5.0

# Marker on the URL the launcher opens. The app window hides the address
# bar. The page copies it into sessionStorage so later pages in that
# window keep reporting geometry. Remote URLs do not carry it.
PLACE_QUERY = "wims_place"

DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 640
DEFAULT_X = 40
DEFAULT_Y = 40
MIN_WIDTH = 480
MIN_HEIGHT = 360
UNKNOWN_MAX_WIDTH = 1280
UNKNOWN_MAX_HEIGHT = 800

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_CONNECTED_RE = re.compile(
    r" connected(?: primary)? (\d+)x(\d+)\+(-?\d+)\+(-?\d+)"
)
_LIST_RE = re.compile(
    r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)"
)

_own_ips_cache: dict = {"at": 0.0, "ips": frozenset()}
_hub: "ConsoleHub | None" = None
_hub_lock = threading.Lock()


@dataclass(frozen=True)
class Screen:
    """One visible display, in the same coordinates the browser reports."""

    x: int
    y: int
    width: int
    height: int


def normalize_ip(ip: str) -> str:
    text = (ip or "").strip().lower()
    if text.startswith("::ffff:"):
        text = text[7:]
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def _remember_ip(ips: set[str], value: object) -> None:
    text = normalize_ip(str(value or ""))
    if not text or text.startswith("("):
        return
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return
    if text in {"0.0.0.0", "::"}:
        return
    ips.add(text)


def own_ips() -> frozenset[str]:
    """Addresses that mean "this PC" when they show up as a client.

    Cached. A browser on another PC has that PC's address, not one of these.
    """
    now = time.monotonic()
    cached = _own_ips_cache.get("ips") or frozenset()
    if cached and (now - float(_own_ips_cache.get("at") or 0.0)) < 30.0:
        return cached
    ips: set[str] = set()
    _remember_ip(ips, "127.0.0.1")
    _remember_ip(ips, "::1")
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0] if info and info[4] else ""
            _remember_ip(ips, addr)
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect does not send a packet. It records the outbound address.
            sock.connect(("192.0.2.1", 9))
            _remember_ip(ips, sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        from wims.agent.report import _lan_ips
        for ip in _lan_ips() or []:
            _remember_ip(ips, ip)
    except Exception:
        pass
    frozen = frozenset(ips)
    _own_ips_cache["at"] = now
    _own_ips_cache["ips"] = frozen
    return frozen


def client_is_local(ip: str, own: frozenset[str] | set[str] | None = None) -> bool:
    """True when the TCP client is this PC, not a remote viewer."""
    host = normalize_ip(ip)
    if host in _LOOPBACK:
        return True
    known = own if own is not None else own_ips()
    return host in {normalize_ip(item) for item in known}


def console_host(url: str) -> str:
    try:
        host = urlsplit((url or "").strip()).hostname or ""
    except ValueError:
        return ""
    return normalize_ip(host)


def console_is_on_this_pc(
    url: str,
    own: frozenset[str] | set[str] | None = None,
) -> bool:
    """True when *url* is the site server on this PC.

    A launcher on a seat must not treat the server PC's own console as the
    window on the seat. That check is what keeps a remote viewer from
    blocking Open site console here, and what keeps a reload from being
    sent at the other PC's pages.
    """
    host = console_host(url)
    if not host:
        return False
    if host in _LOOPBACK:
        return True
    known = own if own is not None else own_ips()
    return host in {normalize_ip(item) for item in known}


def console_origin(url: str) -> str:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        parts = urlsplit("")
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return "http://127.0.0.1:8787"


def placed_console_url(url: str) -> str:
    """URL the local app window loads. Remote viewers never get this query."""
    try:
        parts = urlsplit((url or "").strip() or "http://127.0.0.1:8787/")
    except ValueError:
        parts = urlsplit("http://127.0.0.1:8787/")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[PLACE_QUERY] = "1"
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))


def settings_dir() -> Path:
    """Same directory as the other per-PC settings (last log, goal)."""
    env = (os.environ.get("WIMS_CONSOLE_WINDOW") or "").strip()
    if env:
        return Path(env).parent
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims"
    if sys.platform.startswith("win"):
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims"
    return Path.home() / ".config" / "wims"


def geometry_settings_path() -> Path:
    env = (os.environ.get("WIMS_CONSOLE_WINDOW") or "").strip()
    if env:
        return Path(env)
    return settings_dir() / "console_window.json"


def state_dir() -> Path:
    """Per-PC state. The console's browser profile lives under here.

    Windows uses LocalAppData. Linux and macOS use ``$XDG_STATE_HOME/wims``
    or ``~/.local/state/wims``.
    """
    if sys.platform.startswith("win"):
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "WIMS"
    xdg = (os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims"
    return Path.home() / ".local" / "state" / "wims"


def console_profile_dir() -> Path:
    """Chromium profile for the console window, separate from everyday browsing."""
    return state_dir() / "console-browser"


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number != int(number):
            return None
        return int(number)
    return None


def parse_geometry(body: object) -> dict | None:
    """Return ``{x, y, width, height}`` or None when the report is unusable."""
    if not isinstance(body, dict):
        return None
    x = _as_int(body.get("x"))
    y = _as_int(body.get("y"))
    width = _as_int(body.get("width"))
    height = _as_int(body.get("height"))
    if x is None or y is None or width is None or height is None:
        return None
    if not (-32000 <= x <= 32000 and -32000 <= y <= 32000):
        return None
    if not (100 <= width <= 16000 and 100 <= height <= 16000):
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def load_geometry(path: Path | str | None = None) -> dict | None:
    """Saved console spot, or None when the file is missing or unusable."""
    p = Path(path) if path is not None else geometry_settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return parse_geometry(data if isinstance(data, dict) else None)


def save_geometry(geom: dict, path: Path | str | None = None) -> Path:
    """Write the local console spot. Caller has already decided it may."""
    parsed = parse_geometry(geom)
    if parsed is None:
        raise ValueError("console geometry is not usable")
    p = Path(path) if path is not None else geometry_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, **parsed}
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def geometry_applies(
    *,
    client_local: bool,
    placed: bool,
) -> bool:
    """True only for the console window this PC's launcher opened.

    A remote browser, and a local tab that was not opened as that window,
    must not replace the saved spot.
    """
    return bool(client_local and placed)


def parse_xrandr(text: str) -> list[Screen]:
    """Displays from ``xrandr --query`` or ``xrandr --listmonitors`` text."""
    screens: list[Screen] = []
    seen: set[tuple[int, int, int, int]] = set()
    patterns = (_CONNECTED_RE, _LIST_RE)
    for index, pattern in enumerate(patterns):
        found = False
        for match in pattern.finditer(text or ""):
            width = int(match.group(1))
            height = int(match.group(2))
            x = int(match.group(3))
            y = int(match.group(4))
            if width <= 0 or height <= 0:
                continue
            key = (x, y, width, height)
            if key in seen:
                continue
            seen.add(key)
            screens.append(Screen(x, y, width, height))
            found = True
        if found and index == 0:
            break
    return screens


def _windows_screens() -> list[Screen]:
    if not sys.platform.startswith("win"):
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    screens: list[Screen] = []
    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )

    def _callback(monitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcMonitor
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width > 0 and height > 0:
                screens.append(Screen(int(rect.left), int(rect.top), width, height))
        return 1

    callback = enum_proc(_callback)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return screens


def visible_screens() -> list[Screen]:
    """Displays WIMS can see right now. Empty when the OS will not say."""
    if sys.platform.startswith("win"):
        return _windows_screens()
    for args in (["xrandr", "--query"], ["xrandr", "--listmonitors"]):
        try:
            proc = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        found = parse_xrandr(proc.stdout or "")
        if found:
            return found
    return []


def _fit_on_screen(x: int, y: int, width: int, height: int, screen: Screen) -> dict:
    width = min(max(MIN_WIDTH, width), screen.width)
    height = min(max(MIN_HEIGHT, height), screen.height)
    # A display smaller than the minimum still has to hold the window.
    width = min(width, screen.width)
    height = min(height, screen.height)
    max_x = screen.x + screen.width - width
    max_y = screen.y + screen.height - height
    x = min(max(x, screen.x), max_x)
    y = min(max(y, screen.y), max_y)
    return {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}


def _contained(x: int, y: int, width: int, height: int, screen: Screen) -> bool:
    return (
        x >= screen.x
        and y >= screen.y
        and x + width <= screen.x + screen.width
        and y + height <= screen.y + screen.height
    )


def clamp_geometry(geom: dict | None, screens: list[Screen] | None) -> dict | None:
    """Move *geom* so the window is fully on a visible display.

    With no display list, the spot is the default corner and the size is
    kept inside a modest primary screen. That is still on-screen at the
    origin instead of off to a missing monitor.
    """
    parsed = parse_geometry(geom) if geom else None
    if parsed is None:
        return None
    x = parsed["x"]
    y = parsed["y"]
    width = max(MIN_WIDTH, parsed["width"])
    height = max(MIN_HEIGHT, parsed["height"])
    displays = list(screens or [])
    if not displays:
        width = min(width, UNKNOWN_MAX_WIDTH)
        height = min(height, UNKNOWN_MAX_HEIGHT)
        return {
            "x": DEFAULT_X,
            "y": DEFAULT_Y,
            "width": int(width),
            "height": int(height),
        }
    if any(_contained(x, y, width, height, screen) for screen in displays):
        return {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}
    cx = x + width / 2.0
    cy = y + height / 2.0

    def _distance(screen: Screen) -> float:
        sx = screen.x + screen.width / 2.0
        sy = screen.y + screen.height / 2.0
        return (cx - sx) ** 2 + (cy - sy) ** 2

    nearest = min(displays, key=_distance)
    return _fit_on_screen(x, y, width, height, nearest)


def default_geometry(screens: list[Screen] | None = None) -> dict:
    """The spot Reset console window stores."""
    geom = clamp_geometry(
        {
            "x": DEFAULT_X,
            "y": DEFAULT_Y,
            "width": DEFAULT_WIDTH,
            "height": DEFAULT_HEIGHT,
        },
        screens,
    )
    assert geom is not None
    return geom


def build_chromium_command(
    executable: str,
    url: str,
    user_data_dir: str,
    geometry: dict | None,
) -> list[str]:
    """Chromium app window, its own profile, optional saved spot.

    ``--user-data-dir`` is what stops Chromium from handing the URL to the
    everyday browser ("Opening in existing browser session."). The profile
    also remembers the window on its own. ``--window-size`` and
    ``--window-position`` apply the spot WIMS saved.
    """
    cmd = [
        executable,
        f"--app={url}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    parsed = parse_geometry(geometry) if geometry else None
    if parsed is not None:
        cmd.append(f"--window-size={parsed['width']},{parsed['height']}")
        cmd.append(f"--window-position={parsed['x']},{parsed['y']}")
    return cmd


def decide_reuse(
    *,
    local_sse: int,
    ping_age_s: float | None,
    remote_sse: int = 0,
    window_s: float = PING_WINDOW_S,
) -> str:
    """``reuse`` when a console page on this PC is already up, else ``open``.

    *remote_sse* is the number of browsers on other PCs. It does not change
    the decision. A remote viewer must not stop this PC from opening its
    window, and must not count as the window to reload.
    """
    del remote_sse
    if int(local_sse) > 0:
        return "reuse"
    if ping_age_s is not None and float(ping_age_s) <= float(window_s):
        return "reuse"
    return "open"


def console_open_message(mode: str) -> str:
    """One plain sentence for the Details log. No flags, no variables."""
    if mode == "reuse":
        return "Console is already open. Reloading that window."
    if mode == "app":
        return "Opened the site console."
    return (
        "The console opened in the usual browser. "
        "That window cannot be placed. "
        "The spot is remembered only for Chrome, Chromium, or Edge."
    )


class ConsoleHub:
    """In-memory view of console pages on this PC.

    Remote connections are not recorded. The live-update payload for a
    remote browser is left unchanged.
    """

    def __init__(self, boot: str | None = None) -> None:
        self.boot = boot or _new_boot()
        self.reload_gen = 0
        self.reset_gen = 0
        self.reset_to: dict | None = None
        self._local_sse = 0
        self._last_ping: float | None = None
        self._lock = threading.Lock()

    def sse_enter(self) -> None:
        """A local console page opened its live update."""
        with self._lock:
            self._local_sse += 1

    def sse_exit(self) -> None:
        with self._lock:
            self._local_sse = max(0, self._local_sse - 1)

    def note_ping(self, now: float | None = None) -> None:
        with self._lock:
            self._last_ping = time.monotonic() if now is None else float(now)

    def mark_closed(self) -> None:
        """The placed window said it is going away. Drop the recent ping."""
        with self._lock:
            self._last_ping = None

    def request_reload(self) -> int:
        with self._lock:
            self.reload_gen += 1
            return self.reload_gen

    def request_reset(self, geom: dict) -> int:
        parsed = parse_geometry(geom) or default_geometry([])
        with self._lock:
            self.reset_gen += 1
            self.reset_to = dict(parsed)
            return self.reset_gen

    def local_counts(self, now: float) -> tuple[int, float | None]:
        with self._lock:
            age = None
            if self._last_ping is not None:
                age = max(0.0, float(now) - float(self._last_ping))
            return self._local_sse, age

    def presence(self, now: float, window_s: float = PING_WINDOW_S) -> dict:
        local_sse, age = self.local_counts(now)
        decision = decide_reuse(
            local_sse=local_sse,
            ping_age_s=age,
            remote_sse=0,
            window_s=window_s,
        )
        return {
            "ok": True,
            "local_open": decision == "reuse",
            "local_sse": local_sse,
            "ping_age_s": None if age is None else round(age, 3),
        }

    def control(self) -> dict:
        """Reload / reset for a local live update. Not sent to remote pages."""
        with self._lock:
            ctrl = {
                "local": True,
                "boot": self.boot,
                "reload": self.reload_gen,
                "reset": self.reset_gen,
            }
            if self.reset_to:
                ctrl["reset_to"] = dict(self.reset_to)
            return ctrl


def _new_boot() -> str:
    return f"{time.time():.0f}-{os.getpid()}"


def get_hub() -> ConsoleHub:
    """The site server's one hub. Tests build their own ``ConsoleHub``."""
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = ConsoleHub()
        return _hub


def attach_console_ctrl(snapshot: dict, ctrl: dict | None) -> dict:
    """Add the local-only reload signal.

    *ctrl* None leaves *snapshot* as it is, which is what a remote browser
    receives. The state contract keys are unchanged either way; the extra
    field is only on the local live update.
    """
    if not ctrl:
        return snapshot
    out = dict(snapshot)
    out["console_ctrl"] = dict(ctrl)
    return out


def handle_geometry_post(
    body: object,
    *,
    client_local: bool,
    settings: Path,
    hub: ConsoleHub,
    now: float,
) -> dict:
    """Save a geometry report, or ignore it.

    Remote reports return ``saved: false`` and do not touch the file or the
    local ping. The same is true for a local page that is not the placed
    console window.
    """
    data = body if isinstance(body, dict) else {}
    placed = bool(data.get("placed"))
    if not geometry_applies(client_local=client_local, placed=placed):
        return {"ok": True, "saved": False}
    if data.get("closed"):
        geom = parse_geometry(data)
        saved = False
        if geom is not None:
            save_geometry(geom, settings)
            saved = True
        hub.mark_closed()
        return {"ok": True, "saved": saved}
    geom = parse_geometry(data)
    if geom is None:
        return {"ok": True, "saved": False}
    save_geometry(geom, settings)
    hub.note_ping(now)
    return {"ok": True, "saved": True}


def handle_ping_post(
    body: object,
    *,
    client_local: bool,
    hub: ConsoleHub,
    now: float,
) -> dict:
    """Count a ping from the placed window on this PC. Ignore every other."""
    data = body if isinstance(body, dict) else {}
    placed = bool(data.get("placed"))
    if client_local and placed and not data.get("closed"):
        hub.note_ping(now)
        return {"ok": True, "counted": True}
    return {"ok": True, "counted": False}


def handle_reload_post(*, client_local: bool, hub: ConsoleHub) -> tuple[bool, dict]:
    """Ask local console pages to reload. A remote request does nothing."""
    if not client_local:
        return False, {"ok": False}
    hub.request_reload()
    return True, {"ok": True}


def handle_reset_post(
    body: object,
    *,
    client_local: bool,
    hub: ConsoleHub,
) -> tuple[bool, dict]:
    """Move the local console window. A remote request does nothing."""
    if not client_local:
        return False, {"ok": False}
    data = body if isinstance(body, dict) else {}
    gen = hub.request_reset(data)
    return True, {"ok": True, "reset": gen}


def _read_json(url: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read(65536)
        data = json.loads(raw.decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        return None
    return data if isinstance(data, dict) else None


def _post_json(url: str, body: dict, timeout: float) -> dict | None:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(65536)
        data = json.loads(raw.decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        return None
    return data if isinstance(data, dict) else None


def local_console_is_open(
    url: str,
    timeout: float = 0.4,
    *,
    own: frozenset[str] | set[str] | None = None,
    fetch=None,
) -> bool:
    """True when a console page on this PC is connected to a server on this PC.

    A URL on another PC is never "open here", even when that server has its
    own console. *fetch* is for tests.
    """
    if not console_is_on_this_pc(url, own):
        return False
    reader = fetch or _read_json
    data = reader(console_origin(url) + "/api/console/presence", timeout)
    if not isinstance(data, dict):
        return False
    return bool(data.get("local_open"))


def request_console_reload(
    url: str,
    timeout: float = 0.6,
    *,
    own: frozenset[str] | set[str] | None = None,
    post=None,
) -> bool:
    """Tell this PC's console pages to reload. Never posts to another PC."""
    if not console_is_on_this_pc(url, own):
        return False
    sender = post or _post_json
    data = sender(console_origin(url) + "/api/console/reload", {}, timeout)
    return bool(isinstance(data, dict) and data.get("ok"))


def request_console_reset(
    url: str,
    geom: dict,
    timeout: float = 0.6,
    *,
    own: frozenset[str] | set[str] | None = None,
    post=None,
) -> bool:
    """Tell this PC's open console to move. Never posts to another PC."""
    if not console_is_on_this_pc(url, own):
        return False
    sender = post or _post_json
    data = sender(console_origin(url) + "/api/console/reset", geom, timeout)
    return bool(isinstance(data, dict) and data.get("ok"))
