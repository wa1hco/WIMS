# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compact Tk status shell for agents (log / key / …).

Tired-operator chrome: one green/yellow/red banner, a few fact lines,
Rescan / Quit. Extra detail lives on hover tooltips (and optional Details).
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from wims.launcher.tooltips import ToolTip


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
class AgentStatusModel:
    """Snapshot the Tk window redraws from."""

    title: str = "WIMS agent"
    banner_level: str = "busy"  # ok | warn | err | busy
    banner_text: str = "Starting..."
    fix_text: str = ""
    # Compact per-subsystem rows: (level, label, text), each colored by its
    # own level — e.g. ("ok", "LOG", "2m · FWD 3 ...") / ("err", "KEY", ...).
    status_rows: list[tuple[str, str, str]] = field(default_factory=list)
    fact_lines: list[str] = field(default_factory=list)
    # Shown on hover over banner / facts; also in Details / Copy.
    detail_lines: list[str] = field(default_factory=list)
    hover_text: str = ""
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


RefreshFn = Callable[[], AgentStatusModel]
ActionFn = Callable[[], None]


class AgentStatusWindow:
    """Compact color-coded agent window with hover details."""

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
        self.root.title("WIMS agent")
        # Tall enough for Broadcast + Log + KEY rows without a manual resize.
        self.root.minsize(520, 280)
        self.root.geometry("560x340")
        self.root.configure(bg="#f4f4f4")

        self._banner_var = tk.StringVar(value="Starting...")
        self._fix_var = tk.StringVar(value="")
        self._facts_var = tk.StringVar(value="")
        self._detail_lines: list[str] = []
        self._details_open = False

        self._wrap = 520
        self._banner = tk.Label(
            self.root, textvariable=self._banner_var,
            font=_ui_font(16, "bold"), bg="#fff3cd", fg="#7a5b00",
            padx=12, pady=12, anchor="w", justify="left", wraplength=self._wrap,
        )
        self._banner.pack(fill="x", padx=10, pady=(10, 2))

        self._fix = tk.Label(
            self.root, textvariable=self._fix_var,
            font=_ui_font(11), bg="#f4f4f4", fg="#444444",
            anchor="w", justify="left", wraplength=self._wrap,
        )
        self._fix.pack(fill="x", padx=12, pady=(0, 4))

        # Per-subsystem rows (LOG / KEY / …), each colored by its own level.
        self._rows_frame = tk.Frame(self.root, bg="#f4f4f4")
        self._rows_frame.pack(fill="x", padx=12, pady=(0, 2))
        self._row_labels: list[Any] = []
        self._rows_text: list[str] = []

        self._facts = tk.Label(
            self.root, textvariable=self._facts_var,
            font=_ui_font(12), bg="#f4f4f4", fg="#222222",
            anchor="w", justify="left", wraplength=self._wrap,
        )
        self._facts.pack(fill="x", padx=12, pady=(0, 6))

        # Dynamic hover text — updated each refresh with config-check detail.
        self._tip_banner = ToolTip(self._banner, "Hover for status detail.")
        self._tip_fix = ToolTip(self._fix, "")
        self._tip_facts = ToolTip(self._facts, "")

        btns = tk.Frame(self.root, bg="#f4f4f4")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        b_rescan = tk.Button(
            btns, text="Rescan", font=_ui_font(11),
            command=self._do_rescan,
        )
        b_rescan.pack(side="left")
        ToolTip(b_rescan, "Re-run interconnect / config checks now.")

        # Site only shows when a server URL is known (see _apply).
        self._b_site = tk.Button(
            btns, text="Site", font=_ui_font(11),
            command=self._open_site,
        )
        ToolTip(self._b_site, "Open the site console (Operate / Status) in your browser.")

        b_copy = tk.Button(
            btns, text="Copy", font=_ui_font(11),
            command=self._copy_details,
        )
        b_copy.pack(side="left", padx=(6, 0))
        ToolTip(b_copy, "Copy banner + facts + full check list to the clipboard.")

        b_details = tk.Button(
            btns, text="Details", font=_ui_font(11),
            command=self._toggle_details,
        )
        b_details.pack(side="left", padx=(6, 0))
        ToolTip(b_details, "Show or hide the full config-check list.")
        # No Quit button: closing the window (X) stops the agent the same way
        # (WM_DELETE_WINDOW → _do_quit below).

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
            model = AgentStatusModel(
                banner_level="err",
                banner_text="Status refresh failed",
                fix_text=str(e),
            )
        self._apply(model)
        self.root.after(self._poll_ms, self._tick)

    def _hover_blob(self, model: AgentStatusModel) -> str:
        if model.hover_text.strip():
            return model.hover_text.strip()
        parts = [
            model.banner_text,
            model.fix_text,
            "",
            *(model.detail_lines or []),
        ]
        text = "\n".join(p for p in parts if p).strip()
        return text or "No extra detail yet."

    def _apply_rows(self, rows: list[tuple[str, str, str]]) -> None:
        tk = self.tk
        while len(self._row_labels) < len(rows):
            lab = tk.Label(
                self._rows_frame, font=_ui_font(12, "bold"),
                anchor="w", justify="left", wraplength=self._wrap, padx=8, pady=3,
            )
            lab.pack(fill="x", pady=1)
            self._row_labels.append(lab)
        self._rows_text = []
        for i, lab in enumerate(self._row_labels):
            if i >= len(rows):
                lab.pack_forget()
                continue
            lvl, name, text = rows[i]
            bg, fg = _LEVEL_COLORS.get(lvl, _LEVEL_COLORS["warn"])
            line = f"{name}: {text}"
            lab.configure(text=line, bg=bg, fg=fg)
            self._rows_text.append(line)
            if not lab.winfo_manager():
                lab.pack(fill="x", pady=1)

    def _apply(self, model: AgentStatusModel) -> None:
        bg, fg = _LEVEL_COLORS.get(model.banner_level, _LEVEL_COLORS["warn"])
        self._banner.configure(bg=bg, fg=fg)
        self._banner_var.set(model.banner_text)
        self._fix_var.set(model.fix_text or "")
        self._apply_rows(list(model.status_rows or []))
        facts = [ln for ln in (model.fact_lines or []) if ln][:5]
        self._facts_var.set("\n".join(facts))
        self.root.title(model.title)
        self._site_url = model.site_url
        if model.site_url and not self._b_site.winfo_manager():
            self._b_site.pack(side="left", padx=(6, 0))
        elif not model.site_url and self._b_site.winfo_manager():
            self._b_site.pack_forget()
        self._detail_lines = list(model.detail_lines or [])
        hover = self._hover_blob(model)
        self._tip_banner.set_text(hover)
        self._tip_fix.set_text(hover if model.fix_text else "")
        self._tip_facts.set_text(hover)
        if self._details_open:
            self._details.delete("1.0", "end")
            body = "\n".join(self._detail_lines) if self._detail_lines else "(none)"
            self._details.insert("end", body)
        self.root.after_idle(self._fit_window)

    def _fit_window(self) -> None:
        """Grow to fit banner + rows + facts (no manual resize for normal seat)."""
        try:
            self.root.update_idletasks()
            req_w = max(520, int(self.root.winfo_reqwidth()) + 8)
            req_h = max(280, int(self.root.winfo_reqheight()) + 8)
            # Cap so a huge Details dump does not dominate the desktop.
            req_w = min(req_w, 720)
            req_h = min(req_h, 640 if self._details_open else 420)
            self.root.geometry(f"{req_w}x{req_h}")
            wrap = max(400, req_w - 40)
            if wrap != self._wrap:
                self._wrap = wrap
                self._banner.configure(wraplength=wrap)
                self._fix.configure(wraplength=wrap)
                self._facts.configure(wraplength=wrap)
                for lab in self._row_labels:
                    lab.configure(wraplength=wrap)
        except Exception:
            pass

    def _toggle_details(self) -> None:
        if self._details_open:
            self._details.pack_forget()
            self._details_open = False
            self.root.after_idle(self._fit_window)
            return
        self._details.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._details.delete("1.0", "end")
        body = "\n".join(self._detail_lines) if self._detail_lines else "(none)"
        self._details.insert("end", body)
        self._details_open = True
        self.root.after_idle(self._fit_window)

    def _copy_details(self) -> None:
        parts = [
            self._banner_var.get(),
            self._fix_var.get(),
            *self._rows_text,
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
