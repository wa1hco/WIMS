# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Launcher home: Running list (observe) + Seat intent checkboxes (remembered)."""

from __future__ import annotations

import sys
from typing import Any, Callable

from wims.launcher.assets import (
    INTENT_N1MM,
    INTENT_SERVER,
    INTENT_SSB_CW,
    INTENT_WSJT,
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


# intent_id -> (label, agent blurb, tip)
_INTENT_ROWS = (
    (INTENT_N1MM, "N1MM", "→ N1MM agent Log + Broadcast",
     "This PC will run N1MM. WIMS starts the N1MM agent: "
     "Broadcast (RadioInfo on 127.0.0.1:12060 → site later) and "
     "Log (fleet digi QSOs → local N1MM). Shared band with KEY if both checked."),
    (INTENT_WSJT, "WSJT-X", "→ WSJT monitor",
     "This PC will run WSJT-X (one or more instances). "
     "WIMS starts one monitor agent that audits all live instances."),
    (INTENT_SSB_CW, "SSB/CW KEY", "→ N1MM agent KEY",
     "This PC has an SSB/CW KEY/CTS interface. With N1MM, WIMS runs one "
     "N1MM agent (Broadcast / Log / KEY). Key holds digi seats on the live band "
     "(InhibitStatus discovery, or WIMS_KEY_TARGETS). "
     "Pick the KEY COM/tty below."),
    (INTENT_SERVER, "Site server", "→ Site console",
     "Optional: run the fleet site server on this PC (:8787). "
     "Only one site server on the LAN — adopts existing if already up."),
)


class AgentHomePanel:
    """Running-on-this-PC list + separate seat-intent checkboxes."""

    def __init__(
        self,
        parent,
        *,
        tk,
        intent_vars: dict[str, Any],
        on_intent_toggle: Callable[[str], None],
        on_open_site: Callable[[], None],
        on_open_local: Callable[[], None],
        on_restart_server: Callable[[], None] | None = None,
        on_start_server: Callable[[], None] | None = None,
        key_device_var: Any | None = None,
        on_key_device_change: Callable[[], None] | None = None,
        on_refresh_key_ports: Callable[[], None] | None = None,
    ) -> None:
        self.tk = tk
        self._intent_vars = intent_vars
        self._run_labels: dict[str, Any] = {}
        self._key_device_var = key_device_var
        self._on_key_device_change = on_key_device_change
        self._on_refresh_key_ports = on_refresh_key_ports
        self._key_cts_var: Any | None = None
        self._key_combo = None
        self._key_row = None

        # —— Running (read-only) ——
        run_fr = tk.LabelFrame(
            parent, text="Running on this PC",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=8, pady=6,
        )
        run_fr.pack(fill="x", pady=(0, 8))
        for key, title in (
            ("n1mm", "N1MM"),
            ("wsjt", "WSJT-X"),
            ("log", "N1MM agent (Log)"),
            ("seat", "WSJT monitor"),
            ("key", "N1MM agent (KEY)"),
            ("server", "Site server"),
        ):
            row = tk.Frame(run_fr, bg="#f4f4f4")
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=title, font=_ui_font(11), bg="#f4f4f4", fg="#333333",
                width=14, anchor="w",
            ).pack(side="left")
            var = tk.StringVar(value="…")
            tk.Label(
                row, textvariable=var, font=_ui_font(11), bg="#f4f4f4",
                fg="#444444", anchor="w",
            ).pack(side="left", fill="x", expand=True)
            self._run_labels[key] = var

        # —— Intent (remembered) ——
        intent_fr = tk.LabelFrame(
            parent, text="This seat will run",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=8, pady=6,
        )
        intent_fr.pack(fill="x", pady=(0, 8))
        self.intent_frame = intent_fr

        for intent_id, label, agent, tip in _INTENT_ROWS:
            row = tk.Frame(intent_fr, bg="#f4f4f4")
            row.pack(fill="x", pady=2)
            var = intent_vars[intent_id]
            cb = tk.Checkbutton(
                row, text=label,
                variable=var,
                font=_ui_font(12), bg="#f4f4f4", activebackground="#f4f4f4",
                highlightthickness=0,
                command=lambda i=intent_id: on_intent_toggle(i),
                width=14, anchor="w",
            )
            cb.pack(side="left")
            tk.Label(
                row, text=agent,
                font=_ui_font(11), bg="#f4f4f4", fg="#444444",
                anchor="w",
            ).pack(side="left", padx=(4, 0))
            ToolTip(cb, tip)

        # KEY device row (shown when SSB/CW KEY intent is on).
        if key_device_var is not None:
            key_row = tk.Frame(intent_fr, bg="#f4f4f4")
            key_row.pack(fill="x", pady=(4, 0))
            self._key_row = key_row
            tk.Label(
                key_row, text="KEY device", font=_ui_font(11),
                bg="#f4f4f4", fg="#333333", width=14, anchor="w",
            ).pack(side="left")
            try:
                from tkinter import ttk
                combo = ttk.Combobox(
                    key_row, textvariable=key_device_var, width=28,
                    font=_ui_font(11),
                )
                combo.pack(side="left", padx=(0, 4))
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _e: on_key_device_change() if on_key_device_change else None,
                )
                combo.bind(
                    "<FocusOut>",
                    lambda _e: on_key_device_change() if on_key_device_change else None,
                )
                self._key_combo = combo
            except Exception:
                ent = tk.Entry(
                    key_row, textvariable=key_device_var, width=30,
                    font=_ui_font(11),
                )
                ent.pack(side="left", padx=(0, 4))
                ent.bind(
                    "<FocusOut>",
                    lambda _e: on_key_device_change() if on_key_device_change else None,
                )
            refresh_btn = tk.Button(
                key_row, text="Refresh", font=_ui_font(10),
                command=(on_refresh_key_ports or (lambda: None)),
                padx=6, pady=1,
            )
            refresh_btn.pack(side="left", padx=(0, 6))
            ToolTip(
                refresh_btn,
                "Rescan serial ports (USB KEY dongle plug/unplug).",
            )
            self._key_cts_var = tk.StringVar(value="CTS: —")
            cts_lbl = tk.Label(
                key_row, textvariable=self._key_cts_var,
                font=_ui_font(10), bg="#f4f4f4", fg="#555555",
                anchor="w",
            )
            cts_lbl.pack(side="left", fill="x", expand=True)
            ToolTip(
                cts_lbl,
                "Live CTS sample when KEY intent is on and the seat is not "
                "holding the port. Seat agent owns the port while Key is running.",
            )

        tk.Label(
            intent_fr,
            text="Intent is remembered on this PC. Checking a box starts the "
                 "matching agent; uncheck stops it. Apps may start before or after.",
            font=_ui_font(10), bg="#f4f4f4", fg="#666666",
            wraplength=500, justify="left", anchor="w",
        ).pack(fill="x", pady=(6, 0))

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
        self.local_btn.pack(side="left", padx=(8, 0))
        ToolTip(self.local_btn, "Seat agent local page (:8790) when that agent is up.")
        self.start_server_btn = tk.Button(
            btns, text="Start site server", font=_ui_font(11),
            command=(on_start_server or (lambda: None)), padx=10, pady=5,
        )
        ToolTip(
            self.start_server_btn,
            "No site console reachable — start one on this PC "
            "(only if this machine should host the fleet server).",
        )
        self.restart_server_btn = tk.Button(
            btns, text="Restart site server", font=_ui_font(11),
            command=(on_restart_server or (lambda: None)), padx=10, pady=5,
        )
        ToolTip(
            self.restart_server_btn,
            "Site server is on this PC — stop and start it again to load "
            "the latest code after Update WIMS / git pull.",
        )
        # Shown/hidden by app.refresh based on local vs remote server state.
        self.start_server_btn.pack_forget()
        self.restart_server_btn.pack_forget()
        # Update WIMS lives beside the launcher banner (next to the update
        # message), not down here — see app._show_update_button.

    def update_running(
        self,
        snap: AssetSnapshot,
        *,
        log_up: bool,
        seat_up: bool,
        key_up: bool,
        server_up: bool,
        server_existing: bool = False,
    ) -> None:
        """Refresh the observational Running list."""
        if snap.n1mm_running:
            self._run_labels["n1mm"].set("live")
        elif snap.n1mm_found and sys.platform.startswith("win"):
            # Windows only: Logger+ data dirs mean "installed but not running".
            # Linux often has leftover Documents/N1MM trees; N1MM does not run here.
            self._run_labels["n1mm"].set("off (installed)")
        else:
            self._run_labels["n1mm"].set("off")

        if snap.wsjt_running:
            names = snap.wsjt_running_names
            n = len(names) or 1
            if names:
                shown = ", ".join(names[:4])
                extra = f" +{len(names) - 4}" if len(names) > 4 else ""
                self._run_labels["wsjt"].set(f"{n} live ({shown}{extra})")
            else:
                self._run_labels["wsjt"].set(f"{n} live")
        elif snap.wsjt_ini_count:
            self._run_labels["wsjt"].set(f"off ({snap.wsjt_ini_count} ini on disk)")
        else:
            self._run_labels["wsjt"].set("off")

        self._run_labels["log"].set("up" if log_up else "off")
        self._run_labels["seat"].set("up" if seat_up else "off")
        self._run_labels["key"].set("up" if key_up else "off")
        if server_up and server_existing:
            self._run_labels["server"].set("up (existing)")
        elif server_up:
            self._run_labels["server"].set("up")
        else:
            self._run_labels["server"].set("off")

    def set_key_port_choices(self, ports: list[str]) -> None:
        """Update KEY device combobox values; keep current selection if still listed."""
        if self._key_combo is None:
            return
        cur = ""
        if self._key_device_var is not None:
            cur = (self._key_device_var.get() or "").strip()
        values = list(ports)
        if cur and cur not in values:
            values = [cur] + values
        try:
            self._key_combo["values"] = values
        except Exception:
            pass

    def set_key_cts_status(self, text: str) -> None:
        if self._key_cts_var is not None:
            self._key_cts_var.set(text)

    def show_key_device_row(self, visible: bool) -> None:
        """KEY row stays packed (order-stable); dim when SSB/CW intent is off."""
        if self._key_row is None:
            return
        fg = "#333333" if visible else "#999999"
        try:
            for child in self._key_row.winfo_children():
                try:
                    child.configure(fg=fg)
                except Exception:
                    pass
        except Exception:
            pass

    # Compat name used by older app.py call sites during transition.
    def update_asset_labels(self, snap: AssetSnapshot) -> None:
        self.update_running(
            snap, log_up=False, seat_up=False, key_up=False, server_up=False,
        )
