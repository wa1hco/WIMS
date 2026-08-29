# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compact Tk status shell for seat helpers (log / key / …).

Tired-operator chrome: one green/yellow/red banner, a few fact lines,
Rescan / Quit. No multi-panel config dump on the home face.
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


# ok=green, warn/busy=yellow, err=red
_LEVEL_COLORS = {
    "ok": ("#d8f3dc", "#0a7a2f"),
    "warn": ("#fff3cd", "#7a5b00"),
    "busy": ("#fff3cd", "#7a5b00"),
    "err": ("#f8d7da", "#a4000f"),
}


@dataclass
class HelperStatusModel:
    """Snapshot the Tk window redraws from."""

    title: str = "WIMS helper"
    banner_level: str = "busy"  # ok | warn | err | busy
    banner_text: str = "Starting..."
    fix_text: str = ""
    fact_lines: list[str] = field(default_factory=list)
    # Kept for callers / Copy details; not shown unless Details is opened.
    detail_lines: list[str] = field(default_factory=list)
    site_url: str | None = None

    # Backward-compatible aliases used by older call sites.
    @property
    def status_lines(self) -> list[str]:
        return self.fact_lines

    @status_lines.setter
    def status_lines(self, lines: list[str]) -> None:
        self.fact_lines = list(lines)

    @property
    def interconnect_lines(self) -> list[str]:
        return []

    @interconnect_lines.setter
    def interconnect_lines(self, _lines: list[str]) -> None:
        return

    @property
    def check_lines(self) -> list[str]:
        return self.detail_lines

    @check_lines.setter
    def check_lines(self, lines: list[str]) -> None:
        self.detail_lines = list(lines)


RefreshFn = Callable[[], HelperStatusModel]
ActionFn = Callable[[], None]


class HelperStatusWindow:
    """Compact color-coded helper window."""

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
        self.root.minsize(360, 160)
        self.root.geometry("420x200")
        self.root.configure(bg="#f4f4f4")

        self._banner_var = tk.StringVar(value="Starting...")
        self._fix_var = tk.StringVar(value="")
        self._facts_var = tk.StringVar(value="")
        self._detail_lines: list[str] = []
        self._details_open = False

        self._banner = tk.Label(
            self.root, textvariable=self._banner_var,
            font=_ui_font(16, "bold"), bg="#fff3cd", fg="#7a5b00",
            padx=12, pady=12, anchor="w", justify="left", wraplength=390,
        )
        self._banner.pack(fill="x", padx=10, pady=(10, 2))

        tk.Label(
            self.root, textvariable=self._fix_var,
            font=_ui_font(11), bg="#f4f4f4", fg="#444444",
            anchor="w", justify="left", wraplength=390,
        ).pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(
            self.root, textvariable=self._facts_var,
            font=_ui_font(12), bg="#f4f4f4", fg="#222222",
            anchor="w", justify="left", wraplength=390,
        ).pack(fill="x", padx=12, pady=(0, 6))

        btns = tk.Frame(self.root, bg="#f4f4f4")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            btns, text="Rescan", font=_ui_font(11),
            command=self._do_rescan,
        ).pack(side="left")
        tk.Button(
            btns, text="Site", font=_ui_font(11),
            command=self._open_site,
        ).pack(side="left", padx=(6, 0))
        tk.Button(
            btns, text="Copy", font=_ui_font(11),
            command=self._copy_details,
        ).pack(side="left", padx=(6, 0))
        tk.Button(
            btns, text="Details", font=_ui_font(11),
            command=self._toggle_details,
        ).pack(side="left", padx=(6, 0))
        tk.Button(
            btns, text="Quit", font=_ui_font(11),
            command=self._do_quit,
        ).pack(side="right")

        self._details = tk.Text(
            self.root, height=6, font=_ui_font(10),
            bg="#ffffff", fg="#222222", wrap="word",
            relief="solid", borderwidth=1,
        )
        self._details.bind("<Key>", self._readonly_key)

        self._site_url: str | None = None
        self.root.protocol("WM_DELETE_WINDOW", self._do_quit)
        self.root.after(100, self._tick)

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

    def _tick(self) -> None:
        try:
            model = self._refresh()
        except Exception as e:
            model = HelperStatusModel(
                banner_level="err",
                banner_text="Status refresh failed",
                fix_text=str(e),
            )
        self._apply(model)
        self.root.after(self._poll_ms, self._tick)

    def _apply(self, model: HelperStatusModel) -> None:
        bg, fg = _LEVEL_COLORS.get(model.banner_level, _LEVEL_COLORS["warn"])
        self._banner.configure(bg=bg, fg=fg)
        self._banner_var.set(model.banner_text)
        self._fix_var.set(model.fix_text or "")
        facts = [ln for ln in (model.fact_lines or []) if ln][:5]
        self._facts_var.set("\n".join(facts))
        self.root.title(model.title)
        self._site_url = model.site_url
        self._detail_lines = list(model.detail_lines or [])
        if self._details_open:
            self._details.delete("1.0", "end")
            body = "\n".join(self._detail_lines) if self._detail_lines else "(none)"
            self._details.insert("end", body)

    def _toggle_details(self) -> None:
        if self._details_open:
            self._details.pack_forget()
            self._details_open = False
            self.root.geometry("420x200")
            return
        self._details.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._details.delete("1.0", "end")
        body = "\n".join(self._detail_lines) if self._detail_lines else "(none)"
        self._details.insert("end", body)
        self._details_open = True
        self.root.geometry("420x360")

    def _copy_details(self) -> None:
        parts = [
            self._banner_var.get(),
            self._fix_var.get(),
            self._facts_var.get(),
            "",
            *self._detail_lines,
        ]
        body = "\n".join(p for p in parts if p is not None)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(body)
            self.root.update_idletasks()
        except Exception:
            pass

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
