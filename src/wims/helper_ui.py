# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tiny Tk status shell for seat helpers (log / key / …).

Light mode, 12 pt. Shared chrome only — each helper supplies status text,
check lines, and action callbacks. No site-console roster here.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class HelperStatusModel:
    """Snapshot the Tk window redraws from."""

    title: str = "WIMS helper"
    banner_level: str = "busy"  # ok | warn | err | busy
    banner_text: str = "Starting..."
    status_lines: list[str] = field(default_factory=list)
    interconnect_lines: list[str] = field(default_factory=list)
    check_lines: list[str] = field(default_factory=list)
    site_url: str | None = None


RefreshFn = Callable[[], HelperStatusModel]
ActionFn = Callable[[], None]


class HelperStatusWindow:
    """Small read-mostly status window; polls ``refresh`` on an interval."""

    def __init__(
        self,
        *,
        refresh: RefreshFn,
        on_rescan: ActionFn | None = None,
        on_quit: ActionFn | None = None,
        poll_ms: int = 1000,
        root: Any | None = None,
    ) -> None:
        import tkinter as tk

        self._refresh = refresh
        self._on_rescan = on_rescan
        self._on_quit = on_quit
        self._poll_ms = max(250, int(poll_ms))
        self.tk = tk
        self.root = root or tk.Tk()
        self._owns_root = root is None
        self.root.title("WIMS helper")
        self.root.minsize(420, 360)
        self.root.configure(bg="#f4f4f4")

        self._banner_var = tk.StringVar(value="Starting...")
        self._banner = tk.Label(
            self.root, textvariable=self._banner_var,
            font=_ui_font(14, "bold"), bg="#e7f1ff", fg="#0b5cab",
            padx=12, pady=10, anchor="w", justify="left",
        )
        self._banner.pack(fill="x", padx=12, pady=(12, 6))

        body = tk.Frame(self.root, bg="#f4f4f4")
        body.pack(fill="both", expand=True, padx=12, pady=4)

        self._status = self._section(body, "Status")
        self._inter = self._section(body, "Interconnect")
        self._checks = self._section(body, "Config check")

        btns = tk.Frame(self.root, bg="#f4f4f4")
        btns.pack(fill="x", padx=12, pady=(4, 12))
        tk.Button(
            btns, text="Rescan", font=_ui_font(11),
            command=self._do_rescan,
        ).pack(side="left")
        tk.Button(
            btns, text="Open site console", font=_ui_font(11),
            command=self._open_site,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            btns, text="Quit", font=_ui_font(11),
            command=self._do_quit,
        ).pack(side="right")

        self._site_url: str | None = None
        self.root.protocol("WM_DELETE_WINDOW", self._do_quit)
        self.root.after(100, self._tick)

    def _section(self, parent, title: str):
        import tkinter as tk

        frame = tk.LabelFrame(
            parent, text=title, font=_ui_font(11),
            bg="#f4f4f4", fg="#333333", padx=6, pady=4,
        )
        frame.pack(fill="both", expand=True, pady=4)
        text = tk.Text(
            frame, height=4, font=_ui_font(11),
            bg="#ffffff", fg="#222222", wrap="word",
            relief="solid", borderwidth=1,
        )
        text.pack(fill="both", expand=True)
        text.bind("<Key>", lambda e: self._readonly_key(e))
        return text

    def _readonly_key(self, event):
        if event.state & 0x4:
            key = (event.keysym or "").lower()
            if key in ("c", "a"):
                return None
        if event.keysym in (
            "Left", "Right", "Up", "Down", "Home", "End",
            "Prior", "Next", "Shift_L", "Shift_R", "Control_L", "Control_R",
        ):
            return None
        return "break"

    def _set_text(self, widget, lines: list[str]) -> None:
        body = "\n".join(lines) if lines else "(none)"
        widget.delete("1.0", "end")
        widget.insert("end", body)

    def _tick(self) -> None:
        try:
            model = self._refresh()
        except Exception as e:
            model = HelperStatusModel(
                banner_level="err",
                banner_text=f"Status refresh failed: {e}",
            )
        self._apply(model)
        self.root.after(self._poll_ms, self._tick)

    def _apply(self, model: HelperStatusModel) -> None:
        colors = {
            "ok": ("#d8f3dc", "#0a7a2f"),
            "warn": ("#fff3cd", "#7a5b00"),
            "err": ("#f8d7da", "#a4000f"),
            "busy": ("#e7f1ff", "#0b5cab"),
        }
        bg, fg = colors.get(model.banner_level, colors["busy"])
        self._banner.configure(bg=bg, fg=fg)
        self._banner_var.set(model.banner_text)
        self.root.title(model.title)
        self._site_url = model.site_url
        self._set_text(self._status, model.status_lines)
        self._set_text(self._inter, model.interconnect_lines)
        self._set_text(self._checks, model.check_lines)

    def _do_rescan(self) -> None:
        if self._on_rescan:
            self._on_rescan()
        self._tick()

    def _open_site(self) -> None:
        url = (self._site_url or "").rstrip("/")
        if not url:
            return
        if not url.endswith("/"):
            url = url + "/"
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _do_quit(self) -> None:
        if self._on_quit:
            try:
                self._on_quit()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        if self._owns_root:
            self.root.mainloop()
