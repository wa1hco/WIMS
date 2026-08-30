# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Desktop GUI launcher — peer to N1MM / WSJT-X / GridTracker.

Checkbox asset/agent console (no fixed seat role). Role catalog under
“Other PC types…”. Always say **agent**, not helper.
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
from wims.launcher.assets import (
    AGENT_KEY,
    AGENT_LOG,
    AGENT_SERVER,
    AGENT_WSJT,
    detect_assets,
    load_wanted_agents,
    save_wanted_agents,
    suggested_checks,
)
from wims.launcher.home_panel import AgentHomePanel
from wims.launcher.tooltips import ToolTip

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
_ICON_ICO = _REPO_ROOT / "scripts" / "windows" / "assets" / "wims.ico"
_DETAILS_LOG = _REPO_ROOT / "scratch" / "launcher-details.log"

_DEFAULT_SITE = "http://192.168.1.119:8787"


def _git_rev() -> str:
    """Short git SHA for the running tree (so ops can see if the launcher is current)."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return out.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


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
Comment=WIMS agents + site console
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
            "$s.Description = 'WIMS — agents + site console'; "
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
            "$s.Description = 'WIMS — agents + site console'; "
            f"{icon_ps}"
            "$s.Save()"
        )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False, capture_output=True, text=True,
    )
    return lnk


class LauncherApp:
    """Checkbox agent console. Advanced: full role catalog."""

    def __init__(self, root: "tk.Tk") -> None:
        import tkinter as tk

        self.tk = tk
        self.root = root
        self._rev = _git_rev()
        self.root.title(f"WIMS  ·  agents  ·  v{__version__} ({self._rev})")
        self.root.minsize(540, 480)
        self.root.configure(bg="#f4f4f4")

        self._procs: dict[str, subprocess.Popen] = {}
        self._solo_port = tk.IntVar(value=DEFAULT_SOLO_PORT)
        self._show_advanced = tk.BooleanVar(value=False)
        self._banner_text = tk.StringVar(value="Checking…")
        self._fix_text = tk.StringVar(value="")
        self._site_var = tk.StringVar(value=site_base_url())
        self._card_widgets: dict[str, dict] = {}
        self._discovering = False
        self._last_wsjt_sev: str | None = None
        self._last_wsjt_msg: str = ""
        self._wanted = load_wanted_agents()
        self._user_override: set[str] = set()
        self._agent_vars = {
            AGENT_LOG: tk.BooleanVar(value=bool(self._wanted.get(AGENT_LOG))),
            AGENT_WSJT: tk.BooleanVar(value=bool(self._wanted.get(AGENT_WSJT))),
            AGENT_KEY: tk.BooleanVar(value=bool(self._wanted.get(AGENT_KEY))),
            AGENT_SERVER: tk.BooleanVar(value=bool(self._wanted.get(AGENT_SERVER))),
        }
        self._agent_status = {
            AGENT_LOG: tk.StringVar(value=""),
            AGENT_WSJT: tk.StringVar(value=""),
            AGENT_KEY: tk.StringVar(value=""),
            AGENT_SERVER: tk.StringVar(value=""),
        }
        # role_id mapping for _procs / _start_role
        self._agent_role = {
            AGENT_LOG: "log",
            AGENT_WSJT: "wsjt_agent",
            AGENT_KEY: "key",
            AGENT_SERVER: "server",
        }

        self._apply_icon()
        self._build()
        self.root.after(200, self._kick_site_discover)
        self.root.after(300, self._sync_detect_and_agents)
        self.root.after(400, self._refresh_status)
        self.root.after(1000, self._poll_procs)
        self.root.after(4000, self._pulse_detect)

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

        home = tk.Frame(self.root, bg="#f4f4f4")
        home.pack(fill="x", **pad)
        self._home = home

        tk.Label(
            home, text="WIMS", font=_ui_font(22, "bold"),
            bg="#f4f4f4", fg="#1a1a1a",
        ).pack(anchor="w")
        tk.Label(
            home,
            text="Agents for apps on this PC — check a box to start",
            font=_ui_font(12), bg="#f4f4f4", fg="#333333",
        ).pack(anchor="w", pady=(0, 6))

        self._banner = tk.Label(
            home, textvariable=self._banner_text,
            font=_ui_font(16, "bold"), bg="#eaeaea", fg="#333333",
            padx=12, pady=14, anchor="w", justify="left",
        )
        self._banner.pack(fill="x", pady=(0, 4))
        tk.Label(
            home, textvariable=self._fix_text,
            font=_ui_font(12), bg="#f4f4f4", fg="#444444",
            wraplength=500, justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 8))

        self._home_panel = AgentHomePanel(
            home,
            tk=tk,
            vars_by_id=self._agent_vars,
            status_vars=self._agent_status,
            on_toggle=self._on_agent_toggle,
            on_open_site=self._open_site_console,
            on_open_local=self._open_local_status,
        )

        # —— Advanced role catalog (hidden) ——
        adv_toggle = tk.Checkbutton(
            self.root,
            text="Other tools…",
            variable=self._show_advanced,
            command=self._toggle_advanced,
            font=_ui_font(10), bg="#f4f4f4", activebackground="#f4f4f4",
            highlightthickness=0,
        )
        adv_toggle.pack(anchor="w", padx=16, pady=(8, 0))
        ToolTip(
            adv_toggle,
            "Site URL override, Solo lab, individual role cards.",
        )

        self._adv_frame = tk.Frame(self.root, bg="#f4f4f4")

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
        _append_details_file(
            f"\n===== WIMS launcher v{__version__} ({self._rev})  {stamp} =====\n"
        )
        self._append_log(
            f"Launcher v{__version__} ({self._rev}).\n"
            "Check boxes to start agents (N1MM→Log, WSJT-X→Seat, Key, Site server).\n"
            "When the top bar is green, use Open site console.\n"
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

    def _pulse_detect(self) -> None:
        self._sync_detect_and_agents()
        self.root.after(5000, self._pulse_detect)

    def _sync_detect_and_agents(self) -> None:
        """Detect apps → auto-check boxes (unless user overrode) → start if checked."""
        snap = detect_assets()
        self._home_panel.update_asset_labels(snap)
        # Clear overrides when asset disappears so a later start can auto-check again.
        if not snap.n1mm_present:
            self._user_override.discard(AGENT_LOG)
        if not snap.wsjt_present:
            self._user_override.discard(AGENT_WSJT)

        suggested = suggested_checks(snap, self._wanted)
        for aid, want in suggested.items():
            if aid in self._user_override:
                continue
            cur = bool(self._agent_vars[aid].get())
            if want and not cur:
                self._agent_vars[aid].set(True)
                self._start_agent(aid)
            elif want and cur and not self._agent_running(aid):
                self._start_agent(aid)

        # Local status button only when seat agent is up.
        if self._agent_running(AGENT_WSJT):
            if not self._home_panel.local_btn.winfo_ismapped():
                self._home_panel.local_btn.pack(side="left", padx=(10, 0))
        elif self._home_panel.local_btn.winfo_ismapped():
            self._home_panel.local_btn.pack_forget()

        self._persist_wanted()

    def _persist_wanted(self) -> None:
        self._wanted = {k: bool(v.get()) for k, v in self._agent_vars.items()}
        save_wanted_agents(self._wanted)

    def _agent_running(self, agent_id: str) -> bool:
        return self._proc_running(self._agent_role[agent_id])

    def _on_agent_toggle(self, agent_id: str) -> None:
        self._user_override.add(agent_id)
        if self._agent_vars[agent_id].get():
            self._start_agent(agent_id)
        else:
            self._stop_agent(agent_id)
        self._persist_wanted()
        self._refresh_status()

    def _start_agent(self, agent_id: str) -> None:
        role_id = self._agent_role[agent_id]
        if self._proc_running(role_id):
            return
        base = self._site_var.get().strip() or site_base_url()
        if agent_id == AGENT_SERVER:
            base = f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
            self._site_var.set(base)
        os.environ["WIMS_SERVER"] = base
        if agent_id == AGENT_WSJT:
            self._run_wsjt_check_inline(then_start_monitor=True)
            return
        if agent_id == AGENT_LOG:
            os.environ.pop("WIMS_BAND", None)
        self._append_log(f"Starting {agent_id} agent…")
        self._start_role(role_by_id(role_id))
        self.root.after(1500, self._refresh_status)

    def _stop_agent(self, agent_id: str) -> None:
        role_id = self._agent_role[agent_id]
        self._append_log(f"Stopping {agent_id} agent…")
        self._stop_role(role_id)
        if agent_id == AGENT_WSJT:
            self._last_wsjt_sev = None
            self._last_wsjt_msg = ""
        self.root.after(800, self._refresh_status)

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

        # Per-row status
        labels = {
            AGENT_LOG: "Log agent",
            AGENT_WSJT: "Seat agent",
            AGENT_KEY: "Key agent",
            AGENT_SERVER: "Site server",
        }
        for aid, role_id in self._agent_role.items():
            checked = bool(self._agent_vars[aid].get())
            running = self._proc_running(role_id)
            if running:
                self._agent_status[aid].set("running")
            elif checked:
                self._agent_status[aid].set("starting…")
            else:
                self._agent_status[aid].set("off")

        if self._proc_running("wsjt_agent"):
            self._fetch_wsjt_report()

        # Banner from checked agents
        wanted = [a for a, v in self._agent_vars.items() if v.get()]
        missing = [labels[a] for a in wanted if not self._agent_running(a)]
        if not wanted:
            self._set_banner(
                "busy",
                "Check an agent to start",
                "N1MM → Log agent · WSJT-X → Seat agent · Key → Key agent · Site server.",
            )
        elif missing:
            self._set_banner(
                "warn",
                "Waiting for: " + ", ".join(missing),
                "Uncheck to cancel, or wait for the agent window/process.",
            )
        elif self._agent_running(AGENT_WSJT) and self._last_wsjt_sev == "error":
            self._set_banner(
                "err",
                "Seat agent: WSJT config needs fixing",
                self._last_wsjt_msg or "Open local status / Details.",
            )
        elif not ok_site and not self._agent_running(AGENT_SERVER):
            self._set_banner(
                "warn",
                "Agents running — site console not reachable",
                f"Cannot reach {base}. Check Site server, or Find on LAN under Other tools…",
            )
        else:
            self._set_banner(
                "ok",
                "Ready — checked agents are running",
                "Use Open site console for the fleet.",
            )
        self.root.after(3000, self._refresh_status)

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
                "Seat agent is not running",
                "Check WSJT-X to start the seat agent, then Open local status.",
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
        # Log/key agents have their own Tk window — hide extra console on Windows.
        if role.id in ("log", "key") and sys.platform.startswith("win"):
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._append_log(f"{role.title} status window should open on this PC.")
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
                "Key agent: set WIMS_KEY_DEVICE and WIMS_KEY_TARGETS "
                "(CTS source + inhibit host:port list).",
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
            # Any exit means it is not a resident agent (Task Manager empty).
            self._set_banner(
                "err",
                "Log agent stopped",
                "It exited instead of staying running. Check Details, "
                "then check N1MM again to restart. (Task Manager will not show it if it quit.)",
            )
            self._append_log(f"{title} exited with code {code}.")
        elif code == 0:
            self._append_log(f"{title} finished OK.")
        elif code is not None:
            self._append_log(f"{title} exited with code {code}.")
        self._procs.pop(role_id, None)
        # Keep the checkbox checked on crash so detect can restart the agent.
        # User uncheck already cleared the var and set _user_override.
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
        description="WIMS desktop launcher — checkbox agents for apps on this PC.",
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
