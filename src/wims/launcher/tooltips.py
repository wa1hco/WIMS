# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simple delayed tooltips for tkinter (stdlib only)."""

from __future__ import annotations

import tkinter as tk


class ToolTip:
    """Show ``text`` in a small light popup after a short hover delay."""

    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        # Place just below the pointer-ish region of the widget.
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tip.attributes("-topmost", True)
        frame = tk.Frame(tip, background="#ffffe0", borderwidth=1, relief="solid")
        frame.pack()
        label = tk.Label(
            frame,
            text=self.text,
            justify="left",
            background="#ffffe0",
            foreground="#222222",
            font=("Segoe UI", 10) if _has_font("Segoe UI") else ("TkDefaultFont", 10),
            padx=8,
            pady=6,
            wraplength=360,
        )
        label.pack()
        self._tip = tip


_FONT_CACHE: dict[str, bool] = {}


def _has_font(name: str) -> bool:
    if name in _FONT_CACHE:
        return _FONT_CACHE[name]
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        ok = name in available
    except Exception:
        ok = False
    _FONT_CACHE[name] = ok
    return ok
