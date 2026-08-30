# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Desktop GUI launcher — peer to N1MM / WSJT-X / GridTracker.

Auto-detects **N1MM seat** vs **WSJT seat** home (tired-operator UX).
Role catalog / overrides under “Other PC types…”.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from wims import __version__
from wims.launcher.roles import (
    BAND_PORTS,
    DEFAULT_HTTP_PORT,
    DEFAULT_SOLO_PORT,
    ROLES,
    console_urls,
    primary_roles,
    role_by_id,
)
from wims.launcher.seat_detect import (
    SEAT_AMBIGUOUS,
    SEAT_N1MM,
    SEAT_WSJT,
    probe_seat,
    save_seat_type,
)
from wims.launcher.tooltips import ToolTip

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
_ICON_ICO = _REPO_ROOT / "scripts" / "windows" / "assets" / "wims.ico"
_DETAILS_LOG = _REPO_ROOT / "scratch" / "launcher-details.log"

_DEFAULT_SITE = "http://192.168.1.119:8787"


def details_log_path() -> Path:
    """Session transcript for the launcher Details pane (easy to open/paste)."""
    return _DETAILS_LOG


def _append_details_file(text: str) -> None:
    line = text if text.endswith("\n") else text + "\n"
    try:
        _DETAILS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _DETAILS_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _site_pref_path() -> Path:
    """Last known site console URL for this PC (host-local pref)."""
    env = (os.environ.get("WIMS_LAST_SITE") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "last_site.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "last_site.json"
    return Path.home() / ".config" / "wims" / "last_site.json"


def load_last_site_url() -> str | None:
    try:
        raw = json.loads(_site_pref_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    url = (raw.get("url") or "").strip().rstrip("/")
    return url or None


def save_last_site_url(url: str) -> None:
    url = (url or "").strip().rstrip("/")
    if not url:
        return
    path = _site_pref_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": 1, "url": url}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def resolve_site_url() -> str:
    """Env → last-known → built-in default. Discovery may refine later."""
    env = (os.environ.get("WIMS_SERVER") or "").strip().rstrip("/")
    if env:
        return env
    saved = load_last_site_url()
    if saved:
        return saved
    return _DEFAULT_SITE.rstrip("/")


def _ui_font(size: int = 12, weight: str = "normal") -> tuple:
    family = "TkDefaultFont"
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for name in ("Segoe UI", "Ubuntu", "DejaVu Sans", "Helvetica"):
            if name in available:
                family = name
                break
    except Exception:
        pass
    return (family, size, weight) if weight != "normal" else (family, size)


def _console_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


def _python_cmd() -> list[str]:
    return [_console_python(), "-u"]


def _role_env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(_SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else f"{src}{os.pathsep}{existing}"
    env["PYTHONUNBUFFERED"] = "1"
    # Child prints must not die on Windows cp1252 consoles (arrows, etc.).
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _wait_tcp(host: str, port: int, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def site_base_url() -> str:
    """Site console base — env / last-known / default (no home-screen typing)."""
    return resolve_site_url()


def site_reachable(base: str | None = None, timeout: float = 1.0) -> tuple[bool, str]:
    base = (base or site_base_url()).rstrip("/")
    url = f"{base}/healthz"
    try:
        with urlopen(url, timeout=timeout) as r:  # noqa: S310 — operator LAN URL
            raw = r.read(500)
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if data.get("ok") and data.get("role") == "wims-site-server":
            return True, base
        if data.get("ok"):
            return True, base
        return False, base
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        return False, base


def find_icon_path() -> Path | None:
    if _ICON_ICO.is_file():
        return _ICON_ICO
    return None


def desktop_dir() -> Path:
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return home / "Desktop"


def write_linux_desktop_shortcut() -> Path:
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    path = desk / "WIMS.desktop"
    icon = find_icon_path()
    icon_line = f"Icon={icon}" if icon else "Icon=utilities-terminal"
    exe = _console_python()
    content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=WIMS
GenericName=WSJT-X Instance Management
Comment=N1MM seat helpers + site console
Exec=env PYTHONPATH={_SRC} {exe} -m wims.launcher
Path={_REPO_ROOT}
{icon_line}
Terminal=false
Categories=HamRadio;Network;
StartupNotify=true
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def write_windows_shortcut() -> Path:
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    lnk = desk / "WIMS.lnk"
    icon = find_icon_path()
    starter = _REPO_ROOT / "scripts" / "windows" / "Start-WimsLauncher.cmd"
    target = str(starter if starter.is_file() else sys.executable)
    workdir = str(starter.parent if starter.is_file() else _REPO_ROOT)
    icon_ps = (
        f"if (Test-Path -LiteralPath '{icon}') {{ $s.IconLocation = '{icon},0' }}; "
        if icon else ""
    )
    if starter.is_file():
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{lnk}'); "
            f"$s.TargetPath = '{target}'; "
            f"$s.WorkingDirectory = '{workdir}'; "
            "$s.WindowStyle = 1; "
            "$s.Description = 'WIMS — N1MM seat Start / site console'; "
            f"{icon_ps}"
            "$s.Save()"
        )
    else:
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{lnk}'); "
            f"$s.TargetPath = '{sys.executable}'; "
            f"$s.Arguments = '-m wims.launcher'; "
            f"$s.WorkingDirectory = '{_REPO_ROOT}'; "
            "$s.WindowStyle = 1; "
            "$s.Description = 'WIMS — N1MM seat Start / site console'; "
            f"{icon_ps}"
            "$s.Save()"
        )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False, capture_output=True, text=True,
    )
    return lnk


class LauncherApp:
    """Auto seat home (N1MM or WSJT). Advanced: full role catalog."""

    def __init__(self, root: "tk.Tk") -> None:
        import tkinter as tk

        self.tk = tk
        self.root = root
        self._seat_probe = probe_seat()
        self._seat_type = (
            self._seat_probe.seat_type
            if self._seat_probe.seat_type != SEAT_AMBIGUOUS
            else SEAT_N1MM
        )
        label = "WSJT seat" if self._seat_type == SEAT_WSJT else "N1MM seat"
        self.root.title(f"WIMS  ·  {label}  ·  v{__version__}")
        self.root.minsize(520, 420)
        self.root.configure(bg="#f4f4f4")

        self._procs: dict[str, subprocess.Popen] = {}
        self._solo_port = tk.IntVar(value=DEFAULT_SOLO_PORT)
        self._show_advanced = tk.BooleanVar(value=False)
        self._also_server = tk.BooleanVar(value=False)
        self._seat_choice = tk.StringVar(value=self._seat_type)
        self._banner_text = tk.StringVar(value="Checking…")
        self._fix_text = tk.StringVar(value="")
        self._subtitle_var = tk.StringVar()
        self._blurb_var = tk.StringVar()
        self._site_var = tk.StringVar(value=site_base_url())
        self._card_widgets: dict[str, dict] = {}
        self._discovering = False
        self._last_wsjt_sev: str | None = None
        self._last_wsjt_msg: str = ""

        self._apply_icon()
        self._build()
        self._apply_seat_chrome()
        self.root.after(200, self._kick_site_discover)
        self.root.after(400, self._refresh_status)
        self.root.after(1000, self._poll_procs)
        if self._seat_probe.seat_type == SEAT_AMBIGUOUS:
            self.root.after(300, self._ask_seat_type)

    def _apply_icon(self) -> None:
        icon = find_icon_path()
        if not icon:
            return
        try:
            self.root.iconbitmap(default=str(icon))
        except Exception:
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass

    def _build(self) -> None:
        tk = self.tk
        pad = {"padx": 16, "pady": 6}

        # —— Seat home (N1MM or WSJT; chrome swapped by _apply_seat_chrome) ——
        home = tk.Frame(self.root, bg="#f4f4f4")
        home.pack(fill="x", **pad)
        self._home = home

        tk.Label(
            home, text="WIMS", font=_ui_font(22, "bold"),
            bg="#f4f4f4", fg="#1a1a1a",
        ).pack(anchor="w")
        tk.Label(
            home, textvariable=self._subtitle_var,
            font=_ui_font(12), bg="#f4f4f4", fg="#333333",
        ).pack(anchor="w")
        tk.Label(
            home, textvariable=self._blurb_var,
            font=_ui_font(11), bg="#f4f4f4", fg="#555555",
            wraplength=480, justify="left",
        ).pack(anchor="w", pady=(4, 8))

        self._banner = tk.Label(
            home, textvariable=self._banner_text,
            font=_ui_font(16, "bold"), bg="#eaeaea", fg="#333333",
            padx=12, pady=14, anchor="w", justify="left",
        )
        self._banner.pack(fill="x", pady=(0, 4))
        tk.Label(
            home, textvariable=self._fix_text,
            font=_ui_font(12), bg="#f4f4f4", fg="#444444",
            wraplength=480, justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 10))

        btns = tk.Frame(home, bg="#f4f4f4")
        btns.pack(fill="x", pady=4)
        self._start_btn = tk.Button(
            btns, text="Start seat", font=_ui_font(14, "bold"),
            command=self._start_seat, padx=16, pady=8,
        )
        self._start_btn.pack(side="left")
        self._start_tip = ToolTip(self._start_btn, "")
        self._stop_btn = tk.Button(
            btns, text="Stop", font=_ui_font(12),
            command=self._stop_seat, padx=12, pady=8,
        )
        self._stop_btn.pack(side="left", padx=(10, 0))
        open_btn = tk.Button(
            btns, text="Open site console", font=_ui_font(12),
            command=self._open_site_console, padx=12, pady=8,
        )
        open_btn.pack(side="left", padx=(10, 0))
        ToolTip(
            open_btn,
            "Opens the fleet Operate/Status pages in your browser.\n"
            "Uses discovered / remembered site server — no typing on this screen.",
        )
        self._local_btn = tk.Button(
            btns, text="Open local status", font=_ui_font(12),
            command=self._open_local_status, padx=12, pady=8,
        )
        ToolTip(
            self._local_btn,
            "Opens this PC’s WSJT seat monitor page (config check results).",
        )

        self._opts = tk.Frame(home, bg="#f4f4f4")
        self._opts.pack(fill="x", pady=(8, 4))
        cb = tk.Checkbutton(
            self._opts,
            text="Also run the site server on this PC",
            variable=self._also_server,
            font=_ui_font(11), bg="#f4f4f4", activebackground="#f4f4f4",
            highlightthickness=0,
            command=self._on_also_server_toggled,
        )
        cb.pack(anchor="w")
        ToolTip(
            cb,
            "Only one site server on the whole LAN. Check this if THIS PC "
            "is the designated WIMS server (often the trailer / central N1MM).",
        )

        # —— Advanced role catalog (hidden) ——
        adv_toggle = tk.Checkbutton(
            self.root,
            text="Other PC types / lab tools…",
            variable=self._show_advanced,
            command=self._toggle_advanced,
            font=_ui_font(10), bg="#f4f4f4", activebackground="#f4f4f4",
            highlightthickness=0,
        )
        adv_toggle.pack(anchor="w", padx=16, pady=(8, 0))
        ToolTip(
            adv_toggle,
            "Seat type override, site URL, Solo lab, individual role cards.",
        )

        self._adv_frame = tk.Frame(self.root, bg="#f4f4f4")

        seat_box = tk.LabelFrame(
            self._adv_frame, text="This PC is (override auto-detect)",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=10, pady=6,
        )
        seat_box.pack(fill="x", padx=14, pady=4)
        seat_row = tk.Frame(seat_box, bg="#f4f4f4")
        seat_row.pack(fill="x")
        for value, label in (
            (SEAT_N1MM, "N1MM seat"),
            (SEAT_WSJT, "WSJT seat"),
        ):
            tk.Radiobutton(
                seat_row, text=label, value=value,
                variable=self._seat_choice,
                font=_ui_font(11), bg="#f4f4f4", activebackground="#f4f4f4",
                highlightthickness=0,
                command=self._on_seat_choice,
            ).pack(side="left", padx=(0, 12))
        ToolTip(
            seat_box,
            "Saved on this PC. Use when auto-detect picks the wrong home screen.",
        )

        site_box = tk.LabelFrame(
            self._adv_frame, text="Site server URL (rare override)",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=10, pady=6,
        )
        site_box.pack(fill="x", padx=14, pady=4)
        site_row = tk.Frame(site_box, bg="#f4f4f4")
        site_row.pack(fill="x")
        ent = tk.Entry(
            site_row, textvariable=self._site_var, font=_ui_font(11), width=36,
        )
        ent.pack(side="left")
        ToolTip(
            ent,
            "Normally filled from WIMS_SERVER, last success, or LAN discovery.\n"
            "Override only if discovery fails.",
        )
        tk.Button(
            site_row, text="Find on LAN", font=_ui_font(10),
            command=self._kick_site_discover,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            site_row, text="Recheck", font=_ui_font(10),
            command=self._refresh_status,
        ).pack(side="left", padx=(8, 0))

        self._cards = tk.Frame(self._adv_frame, bg="#f4f4f4")
        self._cards.pack(fill="both", expand=True, padx=14, pady=4)
        for role in primary_roles():
            self._add_role_card(self._cards, role)

        band = tk.LabelFrame(
            self._adv_frame, text="Solo band port (lab only)",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=10, pady=6,
        )
        band.pack(fill="x", padx=14, pady=4)
        row = tk.Frame(band, bg="#f4f4f4")
        row.pack(fill="x")
        for label, port in BAND_PORTS:
            rb = tk.Radiobutton(
                row, text=f"{label}\n:{port}", variable=self._solo_port, value=port,
                font=_ui_font(10), bg="#f4f4f4", activebackground="#f4f4f4",
                highlightthickness=0, justify="center",
            )
            rb.pack(side="left", expand=True, padx=2)
        for role in ROLES:
            if role.advanced:
                self._add_role_card(self._adv_frame, role)

        # —— Quiet details log (selectable + mirrored to scratch file) ——
        self._details = tk.LabelFrame(
            self.root, text="Details (optional)", font=_ui_font(10),
            bg="#f4f4f4", fg="#666666", padx=6, pady=2,
        )
        self._details.pack(fill="both", expand=True, padx=16, pady=(8, 12))
        detail_btns = tk.Frame(self._details, bg="#f4f4f4")
        detail_btns.pack(fill="x", pady=2)
        tk.Button(
            detail_btns, text="Copy details", font=_ui_font(10),
            command=self._copy_details,
        ).pack(side="left")
        tk.Button(
            detail_btns, text="Open log file", font=_ui_font(10),
            command=self._open_details_log,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            detail_btns, text="Put WIMS on Desktop", font=_ui_font(10),
            command=self._install_shortcut,
        ).pack(side="right")
        self._log = tk.Text(
            self._details, height=6, font=_ui_font(10),
            bg="#ffffff", fg="#222222", wrap="word",
            relief="solid", borderwidth=1,
            # Keep state=normal so Windows can select + Ctrl+C (disabled blocks copy).
            exportselection=True,
        )
        self._log.pack(fill="both", expand=True)
        # Block typing; allow Ctrl+C / Ctrl+A / navigation.
        self._log.bind("<Key>", self._details_key)
        self._log.bind("<<Paste>>", lambda _e: "break")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _append_details_file(f"\n===== WIMS launcher v{__version__}  {stamp} =====\n")
        self._append_log(
            "Press Start seat. When the top bar is green, use Open site console.\n"
            f"Log also written to: {details_log_path()}"
        )

    def _toggle_advanced(self) -> None:
        if self._show_advanced.get():
            self._adv_frame.pack(
                fill="both", expand=False, padx=0, pady=0, before=self._details,
            )
        else:
            self._adv_frame.pack_forget()

    def _set_banner(self, level: str, title: str, fix: str) -> None:
        colors = {
            "ok": ("#d8f3dc", "#0a7a2f"),
            "warn": ("#fff3cd", "#7a5b00"),
            "err": ("#f8d7da", "#a4000f"),
            "busy": ("#e7f1ff", "#0b5cab"),
        }
        bg, fg = colors.get(level, ("#eaeaea", "#333333"))
        self._banner.configure(bg=bg, fg=fg)
        self._banner_text.set(title)
        self._fix_text.set(fix)

    def _proc_running(self, role_id: str) -> bool:
        p = self._procs.get(role_id)
        return p is not None and p.poll() is None

    def _apply_seat_chrome(self) -> None:
        """Swap home labels/actions for N1MM vs WSJT without rebuilding the tree."""
        if self._seat_type == SEAT_WSJT:
            self.root.title(f"WIMS  ·  WSJT seat  ·  v{__version__}")
            self._subtitle_var.set("WSJT seat — config check & monitor")
            self._blurb_var.set(
                "WSJT-X should already be running (WIMS uses it to recognize this "
                "seat). Start seat only runs the WIMS monitor — config check and "
                "health report. Decoding and TX stay in WSJT-X."
            )
            self._start_tip.set_text(
                "Runs a WSJT-X config check and starts the seat monitor "
                "(local status page + report to the site server). "
                "WSJT-X itself should already be open."
            )
            self._opts.pack_forget()
            if not self._local_btn.winfo_ismapped():
                self._local_btn.pack(side="left", padx=(10, 0))
        else:
            self.root.title(f"WIMS  ·  N1MM seat  ·  v{__version__}")
            self._subtitle_var.set("N1MM seat — logging helpers for this PC")
            self._blurb_var.set(
                "N1MM should already be running (band comes from RadioInfo). "
                "Start seat only runs the WIMS log helper for QSOs from WSJT-X "
                "on other PCs."
            )
            self._start_tip.set_text(
                "Starts the log helper on this PC (and the site server if you "
                "check the box below). N1MM itself should already be open."
            )
            if self._local_btn.winfo_ismapped():
                self._local_btn.pack_forget()
            if not self._opts.winfo_ismapped():
                self._opts.pack(fill="x", pady=(8, 4))
        self._seat_choice.set(self._seat_type)
        self._append_log(
            f"Seat home: {self._seat_type} "
            f"({self._seat_probe.source}: {self._seat_probe.detail})"
        )

    def _ask_seat_type(self) -> None:
        """One-time chooser when neither N1MM nor WSJT is detected."""
        import tkinter as tk

        win = tk.Toplevel(self.root)
        win.title("What is this PC?")
        win.transient(self.root)
        win.grab_set()
        tk.Label(
            win,
            text="Could not tell if this is an N1MM or WSJT seat.\n"
                 "Pick once — saved on this PC.",
            font=_ui_font(12), justify="left", padx=16, pady=12,
        ).pack()
        row = tk.Frame(win)
        row.pack(pady=(0, 12))

        def pick(kind: str) -> None:
            save_seat_type(kind)
            self._seat_type = kind
            self._seat_probe = probe_seat()
            win.destroy()
            self._apply_seat_chrome()
            self._refresh_status()

        tk.Button(row, text="N1MM seat", font=_ui_font(12),
                  command=lambda: pick(SEAT_N1MM), padx=10).pack(side="left", padx=6)
        tk.Button(row, text="WSJT seat", font=_ui_font(12),
                  command=lambda: pick(SEAT_WSJT), padx=10).pack(side="left", padx=6)

    def _on_seat_choice(self) -> None:
        kind = self._seat_choice.get()
        if kind not in (SEAT_N1MM, SEAT_WSJT):
            return
        save_seat_type(kind)
        self._seat_type = kind
        self._seat_probe = probe_seat()
        self._apply_seat_chrome()
        self._refresh_status()

    def _on_also_server_toggled(self) -> None:
        if self._also_server.get():
            local = f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
            self._site_var.set(local)
            os.environ["WIMS_SERVER"] = local
        self._refresh_status()

    def _kick_site_discover(self) -> None:
        if self._discovering:
            return
        # Env pin wins — do not override an explicit WIMS_SERVER.
        if (os.environ.get("WIMS_SERVER") or "").strip():
            self._site_var.set(site_base_url())
            return
        self._discovering = True
        self._append_log("Looking for site server on the LAN…")

        def work() -> None:
            beacon = None
            try:
                from wims.discovery import presence as P
                beacon = P.discover_site_server(duration_s=2.0, http_fallback=True)
            except Exception as e:
                self.root.after(0, self._append_log, f"(site discover: {e})")
            url = None
            if beacon:
                url = (beacon.get("console_base") or "").rstrip("/") or None
            self.root.after(0, self._apply_discovered_site, url)

        threading.Thread(target=work, daemon=True).start()

    def _apply_discovered_site(self, url: str | None) -> None:
        self._discovering = False
        if url:
            self._site_var.set(url)
            os.environ["WIMS_SERVER"] = url
            save_last_site_url(url)
            self._append_log(f"Site server: {url}")
        else:
            # Keep last-known / default already in _site_var.
            self._append_log(
                f"No site server heard — using {self._site_var.get() or site_base_url()}"
            )
        self._refresh_status()

    def _fetch_wsjt_report(self) -> None:
        """Pull last agent summary from local monitor (best-effort)."""
        try:
            with urlopen("http://127.0.0.1:8790/api/report", timeout=0.6) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            summary = data.get("summary") or {}
            self._last_wsjt_sev = summary.get("severity")
            self._last_wsjt_msg = str(summary.get("message") or "")
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            # Leave previous values; process liveness still drives red/green.
            pass

    def _refresh_status(self) -> None:
        base = self._site_var.get().strip() or site_base_url()
        self._site_var.set(base)
        ok_site, base = site_reachable(base)

        if ok_site:
            save_last_site_url(base)
            os.environ["WIMS_SERVER"] = base

        if self._seat_type == SEAT_WSJT:
            self._refresh_wsjt_status(ok_site, base)
        else:
            self._refresh_n1mm_status(ok_site, base)
        self.root.after(3000, self._refresh_status)

    def _refresh_n1mm_status(self, ok_site: bool, base: str) -> None:
        log_on = self._proc_running("log")
        # Don't offer "Also run site server" when a site console is already up
        # elsewhere (unless this PC is already running the server we started).
        if ok_site and not self._proc_running("server"):
            if self._opts.winfo_ismapped() and not self._also_server.get():
                self._opts.pack_forget()
        elif self._seat_type == SEAT_N1MM and not self._opts.winfo_ismapped():
            self._opts.pack(fill="x", pady=(8, 4))

        if ok_site and log_on:
            self._set_banner(
                "ok",
                "Ready — seat helpers are running",
                "Use Open site console for the roster. Leave this window open.",
            )
        elif log_on and not ok_site:
            self._set_banner(
                "warn",
                "Log helper is running — site console not reachable",
                f"Cannot reach {base}. Start the site server, or use "
                "Other PC types… → Find on LAN / URL override.",
            )
        elif ok_site and not log_on:
            self._set_banner(
                "warn",
                "Site console is up — press Start seat",
                "Logging from WSJT-X on other PCs needs the log helper on this N1MM PC.",
            )
        else:
            self._set_banner(
                "err",
                "Not ready — press Start seat",
                f"Site console ({base}) not reachable, and log helper is not running.",
            )

    def _refresh_wsjt_status(self, ok_site: bool, base: str) -> None:
        mon_on = self._proc_running("wsjt_agent")
        if mon_on:
            self._fetch_wsjt_report()
        sev = self._last_wsjt_sev
        msg = self._last_wsjt_msg or "See Open local status for the full check."

        if mon_on and ok_site and sev == "error":
            self._set_banner("err", "WSJT config needs fixing", msg)
        elif mon_on and ok_site and sev in ("warn", "ok", "busy", None):
            if sev == "warn":
                self._set_banner("warn", "Monitor running — config warnings", msg)
            elif sev == "busy":
                self._set_banner("busy", "Monitor starting — scanning WSJT-X", "One moment.")
            else:
                self._set_banner(
                    "ok",
                    "Ready — WSJT seat monitor running",
                    "Use Open site console for the fleet, or Open local status for this PC.",
                )
        elif mon_on and not ok_site:
            self._set_banner(
                "warn",
                "Monitor running — site console not reachable",
                f"Cannot reach {base}. Start the site server or Find on LAN under Advanced.",
            )
        elif ok_site and not mon_on:
            self._set_banner(
                "warn",
                "Site console is up — press Start seat",
                "Starts the WSJT config monitor for this PC.",
            )
        else:
            self._set_banner(
                "err",
                "Not ready — press Start seat",
                f"Site console ({base}) not reachable, and seat monitor is not running.",
            )

    def _start_seat(self) -> None:
        if self._seat_type == SEAT_WSJT:
            self._start_wsjt_seat()
        else:
            self._start_n1mm_seat()

    def _stop_seat(self) -> None:
        if self._seat_type == SEAT_WSJT:
            self._stop_wsjt_seat()
        else:
            self._stop_n1mm_seat()

    def _start_n1mm_seat(self) -> None:
        self._set_banner(
            "busy",
            "Starting seat…",
            "Log helper follows N1MM band (RadioInfo). Enable Broadcast Data > Radio if asked.",
        )
        base = self._site_var.get().strip() or site_base_url()
        if self._also_server.get():
            base = f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
            self._site_var.set(base)
        os.environ["WIMS_SERVER"] = base
        os.environ.pop("WIMS_BAND", None)
        if self._also_server.get() and not self._proc_running("server"):
            self._start_role(role_by_id("server"))
        if not self._proc_running("log"):
            self._start_role(role_by_id("log"))
        self.root.after(1500, self._refresh_status)

    def _stop_n1mm_seat(self) -> None:
        self._stop_role("log")
        if self._also_server.get() or self._proc_running("server"):
            self._stop_role("server")
        self.root.after(800, self._refresh_status)

    def _start_wsjt_seat(self) -> None:
        self._set_banner(
            "busy",
            "Starting WSJT seat…",
            "Running config check, then starting the seat monitor.",
        )
        base = self._site_var.get().strip() or site_base_url()
        os.environ["WIMS_SERVER"] = base
        # Config check is part of Start seat (results in Details + banner).
        self._run_wsjt_check_inline(then_start_monitor=True)

    def _stop_wsjt_seat(self) -> None:
        self._stop_role("wsjt_agent")
        self._last_wsjt_sev = None
        self._last_wsjt_msg = ""
        self.root.after(800, self._refresh_status)

    def _run_wsjt_check_inline(self, *, then_start_monitor: bool = False) -> None:
        """Run WSJT config check in-process so Details always shows the report."""
        self._append_log("— WSJT seat config check —")
        self._set_banner("busy", "Checking WSJT-X setup…", "Full report goes to Details.")

        def work() -> None:
            try:
                from wims.agent.report import build_report, format_report_text
                rep = build_report(fleet=True)
                text = format_report_text(rep)
                summary = rep.get("summary") or {}
                sev = summary.get("severity") or "unknown"
                msg = str(summary.get("message") or "")
            except Exception as e:
                self.root.after(0, self._on_wsjt_check_done, f"Check failed: {e}", "error", str(e), then_start_monitor)
                return
            self.root.after(0, self._on_wsjt_check_done, text, sev, msg, then_start_monitor)

        threading.Thread(target=work, daemon=True).start()

    def _on_wsjt_check_done(
        self, text: str, sev: str, msg: str, then_start_monitor: bool,
    ) -> None:
        for line in (text or "").splitlines():
            self._append_log(line)
        self._last_wsjt_sev = sev
        self._last_wsjt_msg = msg
        if sev == "error":
            self._set_banner("err", "WSJT config needs fixing", msg or "See Details.")
        elif sev == "warn":
            self._set_banner("warn", "WSJT config has warnings", msg or "See Details.")
        else:
            self._set_banner("ok", "WSJT config check OK", msg or "No config errors.")
        if then_start_monitor:
            if not self._proc_running("wsjt_agent"):
                self._append_log("Starting seat monitor…")
                self._start_role(role_by_id("wsjt_agent"))
            self.root.after(2000, self._refresh_status)

    def _open_local_status(self) -> None:
        url = "http://127.0.0.1:8790/"
        self._append_log(f"Open {url}")
        if not self._proc_running("wsjt_agent"):
            self._set_banner(
                "warn",
                "Seat monitor is not running",
                "Press Start seat first, then Open local status.",
            )
            return

        def _open() -> None:
            if _wait_tcp("127.0.0.1", 8790, 15.0):
                webbrowser.open(url)
            else:
                self.root.after(
                    0, self._append_log,
                    "ERROR: local status :8790 did not open. See Details.",
                )

        threading.Thread(target=_open, daemon=True).start()

    def _open_site_console(self) -> None:
        base = self._site_var.get().strip() or site_base_url()
        url = base.rstrip("/") + "/"
        self._append_log(f"Open {url}")
        ok, _ = site_reachable(base)
        if not ok:
            self._set_banner(
                "err",
                "Site console not reachable",
                f"Tried {url} — start the site server, or correct the address.",
            )
        try:
            webbrowser.open(url)
        except Exception as e:
            self._append_log(f"Browser error: {e}")

    def _add_role_card(self, parent, role) -> None:
        if role is None:
            return
        tk = self.tk
        card = tk.Frame(
            parent, bg="#ffffff", highlightbackground="#cccccc",
            highlightthickness=1, padx=10, pady=8,
        )
        card.pack(fill="x", pady=4)
        top = tk.Frame(card, bg="#ffffff")
        top.pack(fill="x")
        title = role.title + ("  ★" if role.recommended else "")
        tk.Label(
            top, text=title, font=_ui_font(12, "bold"),
            bg="#ffffff", fg="#1a1a1a",
        ).pack(side="left", anchor="w")
        state_lbl = tk.Label(top, text="", font=_ui_font(10), bg="#ffffff", fg="#0a7a2f")
        state_lbl.pack(side="right")
        tk.Label(
            card, text=role.summary, font=_ui_font(11),
            bg="#ffffff", fg="#444444", wraplength=480, justify="left",
        ).pack(anchor="w", pady=(2, 6))
        btn_row = tk.Frame(card, bg="#ffffff")
        btn_row.pack(fill="x")
        start = tk.Button(
            btn_row, text=role.button, font=_ui_font(11),
            command=lambda r=role: self._start_role(r),
        )
        start.pack(side="left")
        ToolTip(start, role.tooltip)
        stop = tk.Button(
            btn_row, text="Stop", font=_ui_font(10),
            command=lambda r=role: self._stop_role(r.id), state="disabled",
        )
        if role.long_running:
            stop.pack(side="left", padx=(8, 0))
        self._card_widgets[role.id] = {
            "start": start, "stop": stop, "state": state_lbl, "role": role,
        }

    def _details_key(self, event) -> str | None:
        # Allow copy / select-all / movement; swallow other keypresses (read-only).
        if event.state & 0x4:  # Control
            key = (event.keysym or "").lower()
            if key in ("c", "a", "insert"):
                return None
        if event.keysym in (
            "Left", "Right", "Up", "Down", "Home", "End",
            "Prior", "Next", "Shift_L", "Shift_R", "Control_L", "Control_R",
        ):
            return None
        return "break"

    def _append_log(self, text: str) -> None:
        line = text if text.endswith("\n") else text + "\n"
        self._log.insert("end", line)
        self._log.see("end")
        _append_details_file(line.rstrip("\n"))

    def _copy_details(self) -> None:
        try:
            body = self._log.get("1.0", "end-1c")
        except Exception as e:
            self._append_log(f"Copy failed: {e}")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(body)
            self.root.update_idletasks()
            self._append_log("(Details copied to clipboard — paste anywhere with Ctrl+V.)")
        except Exception as e:
            self._append_log(f"Clipboard error: {e}. Use Open log file instead.")

    def _open_details_log(self) -> None:
        path = details_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.write_text("(empty — start the seat to capture output)\n", encoding="utf-8")
        except OSError as e:
            self._append_log(f"Cannot write log file: {e}")
            return
        self._append_log(f"Opening {path}")
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            self._append_log(f"Open log failed: {e}. Path: {path}")

    def _start_role(self, role, **kwargs) -> None:
        if role is None:
            return
        if role.id in self._procs and self._procs[role.id].poll() is None:
            self._append_log(f"{role.title} already running.")
            return
        # One-shot WSJT check: run in-process so Details always shows the report
        # (subprocess discovery was easy to miss / looked like "no output").
        if role.id == "wsjt_check":
            self._run_wsjt_check_inline(then_start_monitor=False)
            return
        if role.id == "solo":
            kwargs.setdefault("port", int(self._solo_port.get()))
        if role.id == "log":
            # Live band from N1MM RadioInfo — do not pass a launcher pin.
            kwargs.pop("band", None)
            os.environ.pop("WIMS_BAND", None)
        try:
            py_argv = role.build_argv(**kwargs)
        except TypeError:
            py_argv = role.build_argv()
        cmd = _python_cmd() + py_argv
        self._append_log(f"$ {' '.join(cmd)}")
        popen_kw: dict = {
            "cwd": str(_REPO_ROOT),
            "env": _role_env(),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        # Log helper has its own Tk window — hide the extra black console on Windows.
        if role.id == "log" and sys.platform.startswith("win"):
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._append_log("Log helper status window should open on this PC.")
        try:
            proc = subprocess.Popen(cmd, **popen_kw)
        except Exception as e:
            self._append_log(f"ERROR: {e}")
            self._set_banner("err", "Could not start", str(e))
            return
        self._procs[role.id] = proc
        self._update_card_state(role.id)
        threading.Thread(target=self._reader, args=(role.id, proc), daemon=True).start()

        if role.id == "key":
            self._append_log(
                "NOTE: KEY selftest exits in about one second — "
                "it is not a resident process (yet).",
            )
        elif role.id == "solo":
            self.root.after(1800, lambda: webbrowser.open(console_urls()["operate"]))
        elif role.id == "wsjt_agent":
            self._append_log("Seat monitor UI: http://127.0.0.1:8790/")

            def _open() -> None:
                if _wait_tcp("127.0.0.1", 8790, 25.0):
                    webbrowser.open("http://127.0.0.1:8790/")
                else:
                    self.root.after(
                        0, self._append_log,
                        "ERROR: seat UI :8790 did not open. See Details.",
                    )

            threading.Thread(target=_open, daemon=True).start()
        elif role.id == "server":
            def _open_srv() -> None:
                if _wait_tcp("127.0.0.1", DEFAULT_HTTP_PORT, 20.0):
                    webbrowser.open(console_urls()["status"])

            threading.Thread(target=_open_srv, daemon=True).start()

    def _reader(self, role_id: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.root.after(0, self._append_log, line.rstrip("\n"))
        except Exception as e:
            self.root.after(0, self._append_log, f"({role_id} reader: {e})")
        self.root.after(0, self._on_proc_exit, role_id, proc.poll())

    def _on_proc_exit(self, role_id: str, code: int | None) -> None:
        role = role_by_id(role_id)
        title = role.title if role else role_id
        if role_id == "log":
            # Any exit means it is not a resident helper (Task Manager empty).
            self._set_banner(
                "err",
                "Log helper stopped",
                "It exited instead of staying running. Pick the band, check Details, "
                "then press Start seat again. (Task Manager will not show it if it quit.)",
            )
            self._append_log(f"{title} exited with code {code}.")
        elif role_id == "key":
            self._append_log(
                f"{title} finished (exit {code}) — expected; not a long-running agent yet."
            )
        elif code == 0:
            self._append_log(f"{title} finished OK.")
        elif code is not None:
            self._append_log(f"{title} exited with code {code}.")
        self._procs.pop(role_id, None)
        self._update_card_state(role_id)
        self._refresh_status()

    def _stop_role(self, role_id: str) -> None:
        proc = self._procs.get(role_id)
        if not proc or proc.poll() is not None:
            self._update_card_state(role_id)
            return
        self._append_log(f"Stopping {role_id}…")
        try:
            proc.terminate()
        except Exception as e:
            self._append_log(f"Stop error: {e}")
        self.root.after(800, lambda: self._kill_if_needed(role_id))

    def _kill_if_needed(self, role_id: str) -> None:
        proc = self._procs.get(role_id)
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def _poll_procs(self) -> None:
        for role_id in list(self._procs):
            self._update_card_state(role_id)
        self.root.after(1000, self._poll_procs)

    def _update_card_state(self, role_id: str) -> None:
        widgets = self._card_widgets.get(role_id)
        if not widgets:
            return
        role = widgets.get("role") or role_by_id(role_id)
        alive = self._proc_running(role_id)
        if alive and role is not None and role.long_running:
            widgets["state"].configure(text="Running", fg="#0a7a2f")
            widgets["stop"].configure(state="normal")
        elif alive:
            # One-shot (selftest / check) — do not claim "Running".
            widgets["state"].configure(text="…", fg="#7a5b00")
            widgets["stop"].configure(state="disabled")
        else:
            widgets["state"].configure(text="")
            widgets["stop"].configure(state="disabled")

    def _install_shortcut(self) -> None:
        try:
            path = (
                write_windows_shortcut()
                if sys.platform.startswith("win")
                else write_linux_desktop_shortcut()
            )
            self._append_log(f"Desktop shortcut: {path}")
        except Exception as e:
            self._append_log(f"Shortcut failed: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m wims.launcher",
        description="WIMS desktop launcher — N1MM seat home by default.",
    )
    ap.add_argument(
        "--install-shortcut", action="store_true",
        help="create Desktop shortcut and exit (no GUI)",
    )
    args = ap.parse_args(argv)

    if args.install_shortcut:
        path = (
            write_windows_shortcut()
            if sys.platform.startswith("win")
            else write_linux_desktop_shortcut()
        )
        print(f"Created: {path}")
        return 0

    try:
        import tkinter as tk
    except ImportError:
        print(
            "ERROR: tkinter is not available. On Debian/Ubuntu: sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 2

    root = tk.Tk()
    root.geometry("560x640")
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
