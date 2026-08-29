# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Desktop GUI launcher — sits next to N1MM / WSJT-X / GridTracker.

Light mode, 12 pt. Role cards with tooltips. Long-running roles run as
subprocesses so the window stays responsive.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

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
from wims.launcher.tooltips import ToolTip

# Repo root = parents of src/wims/launcher/app.py → …/wims
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
_ICON_ICO = _REPO_ROOT / "scripts" / "windows" / "assets" / "wims.ico"


def _ui_font(size: int = 12, weight: str = "normal") -> tuple:
    # Prefer fonts that look familiar next to Windows ham apps.
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


def _python_cmd() -> list[str]:
    """Interpreter used to spawn roles (same as the launcher).

    ``-u`` keeps Activity log lines appearing while roles start (no block buffer).
    """
    return [sys.executable, "-u"]


def _role_env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(_SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else f"{src}{os.pathsep}{existing}"
    env["PYTHONUNBUFFERED"] = "1"
    return env


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
    """Create ~/Desktop/WIMS.desktop pointing at this launcher."""
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    path = desk / "WIMS.desktop"
    icon = find_icon_path()
    icon_line = f"Icon={icon}" if icon else "Icon=utilities-terminal"
    exe = sys.executable
    # Use -m so PYTHONPATH is set in Exec via env wrapper.
    content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=WIMS
GenericName=WSJT-X Instance Management
Comment=Start WIMS Solo, site server, seat agent, or KEY lab tools
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
    """Create Desktop\\WIMS.lnk via PowerShell + WScript.Shell."""
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    lnk = desk / "WIMS.lnk"
    icon = find_icon_path()
    # Launch through a tiny .cmd so PYTHONPATH is set without a console flash
    # when pythonw is available; fall back to python.exe.
    starter = _REPO_ROOT / "scripts" / "windows" / "Start-WimsLauncher.cmd"
    target = str(starter if starter.is_file() else sys.executable)
    workdir = str(starter.parent if starter.is_file() else _REPO_ROOT)
    if starter.is_file():
        args = ""
    else:
        args = f'-m wims.launcher'
        # When calling python directly, working dir = repo; PYTHONPATH set in GUI only.
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
            "$s.Description = 'WIMS — desktop launcher (Solo, server, seat agent)'; "
            f"{icon_ps}"
            "$s.Save()"
        )
    else:
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{lnk}'); "
            f"$s.TargetPath = '{sys.executable}'; "
            f"$s.Arguments = '{args}'; "
            f"$s.WorkingDirectory = '{_REPO_ROOT}'; "
            "$s.WindowStyle = 1; "
            "$s.Description = 'WIMS — desktop launcher (Solo, server, seat agent)'; "
            f"{icon_ps}"
            "$s.Save()"
        )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False,
        capture_output=True,
        text=True,
    )
    return lnk


class LauncherApp:
    def __init__(self, root: "tk.Tk") -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title(f"WIMS  ·  v{__version__}")
        self.root.minsize(560, 640)
        self.root.configure(bg="#f4f4f4")

        self._procs: dict[str, subprocess.Popen] = {}
        self._solo_port = tk.IntVar(value=DEFAULT_SOLO_PORT)
        self._show_advanced = tk.BooleanVar(value=False)
        self._status_var = tk.StringVar(value="Ready. Pick a role below — hover any button for help.")

        self._apply_icon()
        self._build()
        self.root.after(1000, self._poll_procs)

    def _apply_icon(self) -> None:
        icon = find_icon_path()
        if not icon:
            return
        try:
            # Windows: .ico via iconbitmap. Linux often ignores .ico — best-effort.
            self.root.iconbitmap(default=str(icon))
        except Exception:
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass

    def _build(self) -> None:
        tk = self.tk
        pad = {"padx": 14, "pady": 6}

        header = tk.Frame(self.root, bg="#f4f4f4")
        header.pack(fill="x", **pad)
        tk.Label(
            header, text="WIMS", font=_ui_font(20, "bold"),
            bg="#f4f4f4", fg="#1a1a1a",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Contest fleet — start the WIMS piece for this PC",
            font=_ui_font(11), bg="#f4f4f4", fg="#444444",
            wraplength=520, justify="left",
        ).pack(anchor="w")
        peers = tk.Label(
            header,
            text="N1MM PC: server (optional) + log agent + key agent.  "
                 "WSJT PC: optional seat check/monitor.  "
                 "You still start N1MM / WSJT-X / GridTracker yourself.",
            font=_ui_font(10), bg="#f4f4f4", fg="#666666",
            wraplength=520, justify="left",
        )
        peers.pack(anchor="w", pady=(4, 0))
        ToolTip(
            peers,
            "WIMS does not replace N1MM or WSJT-X.\n"
            "• N1MM PC — log agent (mcast→localhost) + key agent (SSB/CW)\n"
            "• WSJT PC — config/monitor agent only (RF stays in WSJT-X)\n"
            "• Site server — one per LAN (may share the N1MM box)\n"
            "• Solo lab path is under Advanced — not contest bring-up\n"
            "See docs/decisions/2026-08-29-contest-pc-roles.md",
        )

        hint = tk.Label(
            self.root,
            text="Each agent will grow a compact GUI (status · interconnect · config check). "
                 "Config checks are scoped to what that role needs.",
            font=_ui_font(10), bg="#f4f4f4", fg="#555555",
            wraplength=540, justify="left",
        )
        hint.pack(anchor="w", padx=14, pady=(2, 6))

        self._cards = tk.Frame(self.root, bg="#f4f4f4")
        self._cards.pack(fill="both", expand=True, padx=14, pady=4)
        self._card_widgets: dict[str, dict] = {}
        for role in primary_roles():
            self._add_role_card(self._cards, role)

        adv_toggle = tk.Checkbutton(
            self.root,
            text="Show lab roles (Solo single-PC)",
            variable=self._show_advanced,
            command=self._toggle_advanced,
            font=_ui_font(10), bg="#f4f4f4", activebackground="#f4f4f4",
            highlightthickness=0,
        )
        adv_toggle.pack(anchor="w", padx=14)
        ToolTip(
            adv_toggle,
            "Solo is for home/lab single-PC testing only — low priority for contest drive.",
        )

        self._adv_frame = tk.Frame(self.root, bg="#f4f4f4")
        # Solo band port only when lab roles are shown.
        band = tk.LabelFrame(
            self._adv_frame, text="Solo band port (lab only)",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=10, pady=6,
        )
        band.pack(fill="x", pady=(0, 4))
        ToolTip(
            band,
            "Lab Solo only. Contest fleet uses shared multicast :2237 + log agent "
            "(see remote-logging decision). UDP 2240 unused (N1MM conflict hole).",
        )
        row = tk.Frame(band, bg="#f4f4f4")
        row.pack(fill="x")
        for label, port in BAND_PORTS:
            rb = tk.Radiobutton(
                row, text=f"{label}\n:{port}", variable=self._solo_port, value=port,
                font=_ui_font(10), bg="#f4f4f4", activebackground="#f4f4f4",
                highlightthickness=0, indicatoron=True, justify="center",
            )
            rb.pack(side="left", expand=True, padx=2)
            ToolTip(rb, f"Lab Solo: UDP port {port} for {label}.")

        for role in ROLES:
            if role.advanced:
                self._add_role_card(self._adv_frame, role)

        # Console links + desktop shortcut
        links = tk.Frame(self.root, bg="#f4f4f4")
        links.pack(fill="x", padx=14, pady=(8, 4))
        for key, title, tip in (
            ("operate", "Open Operate", "Call roster — click a line to Work."),
            ("status", "Open Status", "Instances, N1MM, agents, health."),
            ("setup", "Open Setup", "Log pick / resync and networking checklist."),
        ):
            b = tk.Button(
                links, text=title, font=_ui_font(10),
                command=lambda k=key: self._open_console(k),
            )
            b.pack(side="left", padx=(0, 8))
            ToolTip(b, tip)

        shortcut_btn = tk.Button(
            links, text="Put WIMS on Desktop", font=_ui_font(10),
            command=self._install_shortcut,
        )
        shortcut_btn.pack(side="right")
        ToolTip(
            shortcut_btn,
            "Creates a Desktop shortcut named WIMS with the WIMS icon,\n"
            "alongside N1MM and WSJT-X. Safe to run more than once.",
        )

        # Status / log
        status_frame = tk.LabelFrame(
            self.root, text="Activity", font=_ui_font(11),
            bg="#f4f4f4", fg="#333333", padx=8, pady=4,
        )
        status_frame.pack(fill="both", expand=True, padx=14, pady=(4, 10))
        tk.Label(
            status_frame, textvariable=self._status_var,
            font=_ui_font(10), bg="#f4f4f4", fg="#333333",
            anchor="w", justify="left",
        ).pack(fill="x")
        self._log = tk.Text(
            status_frame, height=10, font=_ui_font(10),
            bg="#ffffff", fg="#222222", wrap="word",
            relief="solid", borderwidth=1,
        )
        self._log.pack(fill="both", expand=True, pady=(4, 0))
        self._log.insert(
            "end",
            "Contest: Start server (one PC) · on N1MM PCs start log agent + key agent · "
            "on WSJT PCs optional seat check/monitor.\n",
        )
        self._log.configure(state="disabled")

    def _add_role_card(self, parent, role) -> None:
        tk = self.tk
        card = tk.Frame(parent, bg="#ffffff", highlightbackground="#cccccc",
                        highlightthickness=1, padx=10, pady=8)
        card.pack(fill="x", pady=4)

        top = tk.Frame(card, bg="#ffffff")
        top.pack(fill="x")
        title = role.title
        if role.recommended:
            title = f"{title}  ★ recommended"
        tk.Label(
            top, text=title, font=_ui_font(12, "bold"),
            bg="#ffffff", fg="#1a1a1a",
        ).pack(side="left", anchor="w")

        state_lbl = tk.Label(
            top, text="", font=_ui_font(10), bg="#ffffff", fg="#0a7a2f",
        )
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
        ToolTip(card, role.tooltip)

        stop = tk.Button(
            btn_row, text="Stop", font=_ui_font(10),
            command=lambda r=role: self._stop_role(r.id),
            state="disabled",
        )
        if role.long_running:
            stop.pack(side="left", padx=(8, 0))
            ToolTip(stop, f"Stop the {role.title} process started from this window.")

        self._card_widgets[role.id] = {
            "start": start,
            "stop": stop,
            "state": state_lbl,
            "role": role,
        }

    def _toggle_advanced(self) -> None:
        if self._show_advanced.get():
            self._adv_frame.pack(fill="x", padx=14, pady=(0, 4))
        else:
            self._adv_frame.pack_forget()

    def _append_log(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text)
        if not text.endswith("\n"):
            self._log.insert("end", "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    def _start_role(self, role) -> None:
        if role.id in self._procs and self._procs[role.id].poll() is None:
            self._set_status(f"{role.title} is already running.")
            return

        kwargs = {}
        if role.id == "solo":
            kwargs["port"] = int(self._solo_port.get())

        try:
            py_argv = role.build_argv(**kwargs)
        except TypeError:
            py_argv = role.build_argv()

        cmd = _python_cmd() + py_argv
        self._append_log(f"$ {' '.join(cmd)}")
        self._set_status(f"Starting {role.title}…")

        try:
            # One-shot roles: capture output. Long-running: pipe and stream.
            proc = subprocess.Popen(
                cmd,
                cwd=str(_REPO_ROOT),
                env=_role_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            self._append_log(f"ERROR: {e}")
            self._set_status("Could not start — Python not found.")
            return
        except Exception as e:
            self._append_log(f"ERROR: {e}")
            self._set_status(f"Start failed: {e}")
            return

        # KEY module may be missing until stub lands — surface ImportError nicely.
        self._procs[role.id] = proc
        self._update_card_state(role.id)
        threading.Thread(
            target=self._reader, args=(role.id, proc), daemon=True,
        ).start()

        if role.id == "solo":
            urls = console_urls(DEFAULT_HTTP_PORT)
            self.root.after(1800, lambda: webbrowser.open(urls["operate"]))
        elif role.id == "wsjt_agent":
            # Local seat UI — port 8790 (not 8970). Opens after agent binds.
            self._append_log("Seat monitor UI: http://127.0.0.1:8790/")
            self.root.after(2500, lambda: webbrowser.open("http://127.0.0.1:8790/"))
        elif role.id == "server":
            urls = console_urls(DEFAULT_HTTP_PORT)
            self.root.after(1800, lambda: webbrowser.open(urls["status"]))

    def _reader(self, role_id: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                text = line.rstrip("\n")
                self.root.after(0, self._append_log, text)
        except Exception as e:
            self.root.after(0, self._append_log, f"({role_id} reader: {e})")
        code = proc.poll()
        self.root.after(0, self._on_proc_exit, role_id, code)

    def _on_proc_exit(self, role_id: str, code: int | None) -> None:
        role = role_by_id(role_id)
        title = role.title if role else role_id
        if code == 0:
            self._set_status(f"{title} finished OK.")
        elif code is None:
            self._set_status(f"{title} stopped.")
        else:
            self._set_status(f"{title} exited with code {code}.")
            if role_id == "key" and code != 0:
                self._append_log(
                    "HINT: KEY product module may not be installed yet. "
                    "Lab path: python testbed/inhibit_spike.py selftest"
                )
        self._procs.pop(role_id, None)
        self._update_card_state(role_id)

    def _stop_role(self, role_id: str) -> None:
        proc = self._procs.get(role_id)
        if not proc or proc.poll() is not None:
            self._set_status("Nothing to stop.")
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
        proc = self._procs.get(role_id)
        running = proc is not None and proc.poll() is None
        if running:
            widgets["state"].configure(text="Running", fg="#0a7a2f")
            widgets["stop"].configure(state="normal")
        else:
            widgets["state"].configure(text="", fg="#0a7a2f")
            widgets["stop"].configure(state="disabled")

    def _open_console(self, which: str) -> None:
        url = console_urls(DEFAULT_HTTP_PORT).get(which)
        if not url:
            return
        self._append_log(f"Open {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            self._append_log(f"Browser error: {e}")

    def _install_shortcut(self) -> None:
        try:
            if sys.platform.startswith("win"):
                path = write_windows_shortcut()
            else:
                path = write_linux_desktop_shortcut()
            self._append_log(f"Desktop shortcut: {path}")
            self._set_status(f"Desktop shortcut ready: {path.name}")
        except Exception as e:
            self._append_log(f"Shortcut failed: {e}")
            self._set_status("Could not create Desktop shortcut.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m wims.launcher",
        description="WIMS desktop GUI launcher (peer to N1MM / WSJT-X).",
    )
    ap.add_argument(
        "--install-shortcut", action="store_true",
        help="create Desktop shortcut and exit (no GUI)",
    )
    args = ap.parse_args(argv)

    if args.install_shortcut:
        if sys.platform.startswith("win"):
            path = write_windows_shortcut()
        else:
            path = write_linux_desktop_shortcut()
        print(f"Created: {path}")
        return 0

    try:
        import tkinter as tk
    except ImportError:
        print(
            "ERROR: tkinter is not available. On Debian/Ubuntu: sudo apt install python3-tk\n"
            "Or start roles from the command line: python -m wims.solo",
            file=sys.stderr,
        )
        return 2

    root = tk.Tk()
    # Light, readable default geometry — sits nicely beside other ham icons.
    root.geometry("600x780")
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
