# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checkbox asset/agent home panel (no fixed seat role)."""

from __future__ import annotations

from typing import Any, Callable

from wims.launcher.assets import (
    AGENT_KEY,
    AGENT_LOG,
    AGENT_SERVER,
    AGENT_WSJT,
    AssetSnapshot,
)
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


# agent_id -> (asset label, agent label, tip)
_ROWS = (
    (AGENT_LOG, "N1MM", "Log agent",
     "One Log agent per N1MM. Joins fleet mcast, filters by N1MM band, "
     "delivers Logged QSOs to local N1MM."),
    (AGENT_WSJT, "WSJT-X", "Seat agent",
     "One Seat agent for all local WSJT-X instances. Config check + monitor."),
    (AGENT_KEY, "Key (CTS)", "Key agent",
     "No companion app. Checks KEY/CTS device and inhibit target list."),
    (AGENT_SERVER, "Site server", "Site server",
     "Fleet console on this PC (:8787). Only one site server on the LAN."),
)


class AgentHomePanel:
    """Builds the checkbox rows; calls back into the launcher to start/stop."""

    def __init__(
        self,
        parent,
        *,
        tk,
        vars_by_id: dict[str, Any],
        status_vars: dict[str, Any],
        on_toggle: Callable[[str], None],
        on_open_site: Callable[[], None],
        on_open_local: Callable[[], None],
    ) -> None:
        self.tk = tk
        self._on_toggle = on_toggle
        self._rows: dict[str, dict] = {}

        frame = tk.LabelFrame(
            parent, text="Agents on this PC",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=8, pady=6,
        )
        frame.pack(fill="x", pady=(0, 8))
        self.frame = frame

        for agent_id, asset, agent, tip in _ROWS:
            row = tk.Frame(frame, bg="#f4f4f4")
            row.pack(fill="x", pady=2)
            var = vars_by_id[agent_id]
            cb = tk.Checkbutton(
                row, text=f"{asset}",
                variable=var,
                font=_ui_font(12), bg="#f4f4f4", activebackground="#f4f4f4",
                highlightthickness=0,
                command=lambda a=agent_id: on_toggle(a),
                width=14, anchor="w",
            )
            cb.pack(side="left")
            tk.Label(
                row, text=f"→ {agent}",
                font=_ui_font(11), bg="#f4f4f4", fg="#444444",
                width=14, anchor="w",
            ).pack(side="left", padx=(4, 0))
            st = status_vars[agent_id]
            st_lbl = tk.Label(
                row, textvariable=st,
                font=_ui_font(11), bg="#f4f4f4", fg="#333333",
                anchor="w",
            )
            st_lbl.pack(side="left", fill="x", expand=True, padx=(8, 0))
            ToolTip(cb, tip)
            ToolTip(st_lbl, tip)
            self._rows[agent_id] = {"cb": cb, "status": st_lbl}

        hint = tk.Label(
            frame,
            text="Check a box to start that agent; uncheck to stop. "
                 "Boxes auto-check when N1MM / WSJT-X is detected.",
            font=_ui_font(10), bg="#f4f4f4", fg="#666666",
            wraplength=480, justify="left", anchor="w",
        )
        hint.pack(fill="x", pady=(6, 0))

        btns = tk.Frame(parent, bg="#f4f4f4")
        btns.pack(fill="x", pady=4)
        open_btn = tk.Button(
            btns, text="Open site console", font=_ui_font(12),
            command=on_open_site, padx=12, pady=6,
        )
        open_btn.pack(side="left")
        ToolTip(open_btn, "Fleet Operate / Status / Setup in the browser.")
        self.local_btn = tk.Button(
            btns, text="Open local status", font=_ui_font(12),
            command=on_open_local, padx=12, pady=6,
        )
        ToolTip(self.local_btn, "WSJT seat agent local page (when that agent is running).")

    def update_asset_labels(self, snap: AssetSnapshot) -> None:
        """Refresh checkbox labels with live asset counts."""
        wsjt = self._rows[AGENT_WSJT]["cb"]
        n = len(snap.wsjt_running_names) or (1 if snap.wsjt_running else 0)
        if snap.wsjt_running and n:
            wsjt.configure(text=f"WSJT-X ({n})")
        elif snap.wsjt_ini_count:
            wsjt.configure(text=f"WSJT-X ({snap.wsjt_ini_count} ini)")
        else:
            wsjt.configure(text="WSJT-X")
        n1 = self._rows[AGENT_LOG]["cb"]
        n1.configure(text="N1MM" + (" (running)" if snap.n1mm_running else ""))
