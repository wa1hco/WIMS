# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Updates list on the WIMS window, next to the existing buttons.

Nothing here installs a release by itself. Check now only looks.
Each row's date is this PC's local day. The hover tip adds the local
time when GitHub sent a clock time.
"""

from __future__ import annotations

from typing import Callable

from wims.launcher.tooltips import ToolTip
from wims.launcher.update_check import ReleaseEntry, notes_tooltip


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


class UpdatesPanel:
    """Version list, notes, Check now, Install, and Go back."""

    def __init__(
        self,
        parent,
        *,
        tk,
        on_check: Callable[[], None],
        on_install: Callable[[], None],
        on_rollback: Callable[[], None],
    ) -> None:
        self.tk = tk
        self._entries: list[ReleaseEntry] = []
        frame = tk.LabelFrame(
            parent, text="Updates",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=8, pady=6,
        )
        frame.pack(fill="x", pady=(6, 0))
        self.frame = frame

        self._mark = tk.Label(
            frame, text="", font=_ui_font(10), bg="#f4f4f4", fg="#9a6700",
            anchor="w",
        )
        self._mark.pack(fill="x")
        self._mark_tip = ToolTip(
            self._mark,
            "An update is available. Nothing is installed until you choose it.",
        )

        self._list = tk.Listbox(
            frame, height=4, font=_ui_font(11),
            bg="#ffffff", fg="#1a1a1a",
            activestyle="dotbox", exportselection=False,
        )
        self._list.pack(fill="x", pady=(2, 4))
        self._list.bind("<<ListboxSelect>>", self._on_select)
        self._hover_index: int | None = None
        self._list_tip = ToolTip(self._list, "Hover a row to read what changed.")
        self._list.bind("<Motion>", self._on_list_motion, add="+")
        self._list.bind("<Enter>", self._on_list_motion, add="+")
        self._list.bind("<Leave>", self._on_list_leave, add="+")

        self._summary = tk.Label(
            frame, text="No update list yet.",
            font=_ui_font(11), bg="#f4f4f4", fg="#444444",
            wraplength=500, justify="left", anchor="w",
        )
        self._summary.pack(fill="x", pady=(0, 4))

        row = tk.Frame(frame, bg="#f4f4f4")
        row.pack(fill="x")
        self._check_btn = tk.Button(
            row, text="Check now", font=_ui_font(12),
            command=on_check, padx=8, pady=3,
        )
        self._check_btn.pack(side="left")
        ToolTip(self._check_btn, "Look at GitHub now. This does not install anything.")
        self._install_btn = tk.Button(
            row, text="Install this update", font=_ui_font(12),
            command=on_install, padx=8, pady=3,
        )
        self._install_btn.pack(side="left", padx=(8, 0))
        ToolTip(
            self._install_btn,
            "Install the update you selected. You can go back afterwards.",
        )
        self._back_btn = tk.Button(
            row, text="Go back", font=_ui_font(12),
            command=on_rollback, padx=8, pady=3,
        )
        self._back_btn.pack(side="left", padx=(8, 0))
        ToolTip(
            self._back_btn,
            "Return to the copy that was running before the last install.",
        )

        self._progress = tk.Label(
            frame, text="",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333",
            wraplength=500, justify="left", anchor="w",
        )
        self._progress.pack(fill="x", pady=(4, 0))

    def set_mark(self, text: str) -> None:
        self._mark.configure(text=text or "")
        if text:
            self._mark_tip.set_text(
                "An update is available. Nothing is installed until you choose it."
            )

    def set_notice(self, text: str) -> None:
        self._progress.configure(text=text or "")

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for btn in (self._check_btn, self._install_btn, self._back_btn):
            btn.configure(state=state)

    def set_releases(self, entries: list[ReleaseEntry] | tuple[ReleaseEntry, ...]) -> None:
        previous = self.selected_tag()
        self._entries = list(entries)
        self._hover_index = None
        self._list.delete(0, "end")
        for entry in self._entries:
            self._list.insert("end", entry.line())
        if not self._entries:
            self._summary.configure(text="No versions to show.")
            self._list_tip.set_text("No versions to show.")
            return
        self._list_tip.hide()
        pick = 0
        if previous:
            for i, entry in enumerate(self._entries):
                if entry.tag == previous:
                    pick = i
                    break
        self._list.selection_clear(0, "end")
        self._list.selection_set(pick)
        self._list.activate(pick)
        self._show_entry(self._entries[pick])

    def selected_tag(self) -> str:
        if not self._entries:
            return ""
        try:
            picked = self._list.curselection()
        except Exception:
            return ""
        if not picked:
            return ""
        index = int(picked[0])
        if index < 0 or index >= len(self._entries):
            return ""
        return self._entries[index].tag

    def selected_entry(self) -> ReleaseEntry | None:
        tag = self.selected_tag()
        for entry in self._entries:
            if entry.tag == tag:
                return entry
        return None

    def _on_select(self, _event=None) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self._show_entry(entry)

    def _show_entry(self, entry: ReleaseEntry) -> None:
        """Selection drives the summary line and Install. Hover drives the tip."""
        self._summary.configure(text=entry.summary())

    def _row_at(self, y: int) -> int | None:
        if not self._entries:
            return None
        try:
            index = int(self._list.nearest(y))
        except Exception:
            return None
        if index < 0 or index >= len(self._entries):
            return None
        try:
            bbox = self._list.bbox(index)
        except Exception:
            bbox = None
        if not bbox:
            return None
        top = int(bbox[1])
        height = int(bbox[3])
        if y < top or y >= top + height:
            return None
        return index

    def _on_list_motion(self, event) -> None:
        index = self._row_at(int(getattr(event, "y", 0) or 0))
        if index is None:
            self._on_list_leave()
            return
        if index == self._hover_index:
            return
        self._hover_index = index
        self._list_tip.set_text(notes_tooltip(self._entries[index]))

    def _on_list_leave(self, _event=None) -> None:
        self._hover_index = None
        self._list_tip.hide()
