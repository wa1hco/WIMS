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
    INTENT_ANTENNAS,
    INTENT_SERVER,
    INTENT_SSB_CW,
    INTENT_WSJT,
    AssetSnapshot,
    new_antenna_id,
    new_device_id,
)
from wims.launcher.server_rev import (
    RESTART_NEEDED_MARK,
    RESTART_NEEDED_TIP,
    RESTART_PLAIN_TIP,
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
    (INTENT_ANTENNAS, "Antennas", "→ Antenna side of the agent",
     "This PC has antennas. WIMS reads each rotator’s heading and "
     "shows it on the console. It does not turn the antenna."),
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
        antennas: list | None = None,
        on_antennas_change: Callable[[list], None] | None = None,
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
        self._on_antennas_change = on_antennas_change
        self._ant_editors: list[dict] = []
        self._ant_frame = None
        self._ant_rows = None
        self._ant_warn: Any | None = None

        # —— Running (read-only, two columns to keep the home short) ——
        run_fr = tk.LabelFrame(
            parent, text="Running on this PC",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=6, pady=2,
        )
        run_fr.pack(fill="x", pady=(0, 4))
        run_grid = tk.Frame(run_fr, bg="#f4f4f4")
        run_grid.pack(fill="x")
        run_items = (
            ("n1mm", "N1MM"),
            ("wsjt", "WSJT-X"),
            ("log", "Log agent"),
            ("seat", "Seat agent"),
            ("key", "Key agent"),
            ("server", "Site server"),
        )
        for i, (key, title) in enumerate(run_items):
            r, c = divmod(i, 2)
            cell = tk.Frame(run_grid, bg="#f4f4f4")
            cell.grid(row=r, column=c, sticky="ew", padx=(0, 8), pady=0)
            tk.Label(
                cell, text=title, font=_ui_font(11), bg="#f4f4f4", fg="#333333",
                width=13, anchor="w",
            ).pack(side="left")
            var = tk.StringVar(value="…")
            tk.Label(
                cell, textvariable=var, font=_ui_font(11), bg="#f4f4f4",
                fg="#444444", anchor="w",
            ).pack(side="left", fill="x", expand=True)
            self._run_labels[key] = var
        run_grid.columnconfigure(0, weight=1)
        run_grid.columnconfigure(1, weight=1)

        # N1MM agent live rows (Broadcast / Log / KEY) — this launcher window,
        # not a second Tk process.
        self._n1mm_fr = tk.LabelFrame(
            parent, text="N1MM agent",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=6, pady=2,
        )
        self._n1mm_row_vars: list[Any] = []
        self._n1mm_row_labels: list[Any] = []
        self._n1mm_empty = tk.StringVar(value="off")
        self._n1mm_empty_lbl = tk.Label(
            self._n1mm_fr, textvariable=self._n1mm_empty,
            font=_ui_font(11), bg="#f4f4f4", fg="#666666", anchor="w",
        )
        self._n1mm_empty_lbl.pack(fill="x")
        self._n1mm_fr.pack(fill="x", pady=(0, 4))

        # —— Intent (remembered) ——
        intent_fr = tk.LabelFrame(
            parent, text="This seat will run",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=6, pady=2,
        )
        intent_fr.pack(fill="x", pady=(0, 4))
        self.intent_frame = intent_fr
        self._server_intent_row = None
        self._intent_help = None
        ToolTip(
            intent_fr,
            "Intent is remembered on this PC. Check starts the matching agent; "
            "uncheck stops it. Apps may start before or after.",
        )

        for intent_id, label, agent, tip in _INTENT_ROWS:
            row = tk.Frame(intent_fr, bg="#f4f4f4")
            row.pack(fill="x", pady=0)
            if intent_id == INTENT_SERVER:
                self._server_intent_row = row
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
            key_row.pack(fill="x", pady=(2, 0))
            self._key_row = key_row
            tk.Label(
                key_row, text="KEY device", font=_ui_font(11),
                bg="#f4f4f4", fg="#333333", width=14, anchor="w",
            ).pack(side="left")
            try:
                from tkinter import ttk
                combo = ttk.Combobox(
                    key_row, textvariable=key_device_var, width=22,
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
                    key_row, textvariable=key_device_var, width=24,
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

        # Antennas and their rotator devices. Shown when Antennas is checked.
        # Packed later, above the buttons, so unchecking does not reorder them.
        ant_fr = tk.LabelFrame(
            parent, text="Antennas on this PC",
            font=_ui_font(11), bg="#f4f4f4", fg="#333333", padx=6, pady=2,
        )
        self._ant_frame = ant_fr
        tk.Label(
            ant_fr,
            text=(
                "Each antenna can have a rotator. "
                "WIMS reads the heading. It does not turn the antenna."
            ),
            font=_ui_font(10), bg="#f4f4f4", fg="#555555",
            wraplength=500, justify="left", anchor="w",
        ).pack(fill="x")
        self._ant_rows = tk.Frame(ant_fr, bg="#f4f4f4")
        self._ant_rows.pack(fill="x")
        add_ant = tk.Button(
            ant_fr, text="Add antenna", font=_ui_font(10),
            command=self._add_antenna_block, padx=6, pady=1,
        )
        add_ant.pack(anchor="w", pady=(2, 0))
        ToolTip(
            add_ant,
            "Add an antenna on this PC. Add a rotator under it to read the heading.",
        )
        self._ant_warn = tk.StringVar(value="")
        tk.Label(
            ant_fr, textvariable=self._ant_warn,
            font=_ui_font(10), bg="#f4f4f4", fg="#7a5b00",
            anchor="w", justify="left", wraplength=500,
        ).pack(fill="x")
        for ant in antennas or []:
            self._add_antenna_block(ant, notify=False)

        btns = tk.Frame(parent, bg="#f4f4f4")
        btns.pack(fill="x", pady=(4, 0))
        self.btn_row = btns
        open_btn = tk.Button(
            btns, text="Open site console", font=_ui_font(12),
            command=on_open_site, padx=10, pady=4,
        )
        open_btn.pack(side="left")
        ToolTip(
            open_btn,
            "Opens the site console on this PC. If that window is already "
            "open, it reloads and stays where you put it.",
        )
        self.local_btn = tk.Button(
            btns, text="Open local status", font=_ui_font(12),
            command=on_open_local, padx=10, pady=4,
        )
        self.local_btn.pack(side="left", padx=(8, 0))
        ToolTip(self.local_btn, "Seat agent local page (:8790) when that agent is up.")
        self.start_server_btn = tk.Button(
            btns, text="Start site server", font=_ui_font(11),
            command=(on_start_server or (lambda: None)), padx=8, pady=4,
        )
        ToolTip(
            self.start_server_btn,
            "No site console reachable — start one on this PC "
            "(only if this machine should host the fleet server).",
        )
        self.restart_server_btn = tk.Button(
            btns, text="Restart site server", font=_ui_font(11),
            command=(on_restart_server or (lambda: None)), padx=8, pady=4,
        )
        self._restart_tip = ToolTip(self.restart_server_btn, RESTART_PLAIN_TIP)
        self._restart_detail = ""
        self.restart_needed_lbl = tk.Label(
            btns, text="", font=_ui_font(11, "bold"),
            bg="#fff3cd", fg="#7a5b00", padx=6, pady=2,
        )
        self._restart_mark_tip = ToolTip(self.restart_needed_lbl, "")
        # Shown/hidden by app.refresh based on local vs remote server state.
        self.start_server_btn.pack_forget()
        self.restart_server_btn.pack_forget()
        self.restart_needed_lbl.pack_forget()
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

    def update_n1mm_agent_status(
        self,
        status: dict | None,
        *,
        log_on: bool,
        key_on: bool,
        seat_up: bool,
    ) -> None:
        """Show Broadcast/Log/KEY rows from the seat snapshot (options that run)."""
        for lab in self._n1mm_row_labels:
            try:
                lab.destroy()
            except Exception:
                pass
        self._n1mm_row_labels = []
        rows = []
        if status and seat_up:
            raw = status.get("status_rows") or []
            for item in raw:
                if not (isinstance(item, (list, tuple)) and len(item) >= 3):
                    continue
                level, label, text = item[0], item[1], item[2]
                lab_u = str(label).upper()
                if lab_u == "LOG" and not log_on:
                    continue
                if lab_u == "KEY" and not key_on:
                    continue
                rows.append((str(level), str(label), str(text)))
        if not rows:
            self._n1mm_empty.set(
                "up — waiting for status…" if seat_up else "off"
            )
            if not self._n1mm_empty_lbl.winfo_manager():
                self._n1mm_empty_lbl.pack(fill="x")
            return
        self._n1mm_empty.set("")
        try:
            self._n1mm_empty_lbl.pack_forget()
        except Exception:
            pass
        colors = {
            "ok": ("#d8f3dc", "#0a7a2f"),
            "warn": ("#fff3cd", "#7a5b00"),
            "busy": ("#fff3cd", "#7a5b00"),
            "err": ("#f8d7da", "#a4000f"),
        }
        for level, label, text in rows:
            bg, fg = colors.get(level, ("#f4f4f4", "#222222"))
            line = self.tk.Label(
                self._n1mm_fr,
                text=f"{label}  {text}",
                font=_ui_font(11), bg=bg, fg=fg,
                anchor="w", padx=6, pady=2, justify="left",
            )
            line.pack(fill="x", pady=1)
            self._n1mm_row_labels.append(line)

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

    def set_restart_tip(self, text: str) -> None:
        """Revision sentence for Restart site server (running copy vs disk)."""
        self._restart_detail = text or ""
        if self._restart_detail:
            self._restart_tip.set_text(self._restart_detail)

    def set_restart_needed(self, needed: bool) -> None:
        """Show or clear the Restart needed mark beside Restart site server."""
        needed = bool(needed)
        detail = getattr(self, "_restart_detail", "") or ""
        if detail:
            self._restart_tip.set_text(detail)
        else:
            self._restart_tip.set_text(
                RESTART_NEEDED_TIP if needed else RESTART_PLAIN_TIP
            )
        self._restart_mark_tip.set_text(RESTART_NEEDED_TIP if needed else "")
        if needed:
            self.restart_needed_lbl.configure(text=RESTART_NEEDED_MARK)
            if not self.restart_needed_lbl.winfo_manager():
                self.restart_needed_lbl.pack(side="left", padx=(8, 0))
        else:
            self.restart_needed_lbl.configure(text="")
            if self.restart_needed_lbl.winfo_manager():
                self.restart_needed_lbl.pack_forget()

    def set_server_intent_visible(self, visible: bool) -> None:
        """Show or hide the Site server checkbox (never offered on WSJT-X seats)."""
        row = self._server_intent_row
        if row is None:
            return
        packed = bool(row.winfo_manager())
        if visible and not packed:
            before = self._key_row or self._intent_help
            try:
                if before is not None:
                    row.pack(fill="x", pady=2, before=before)
                else:
                    row.pack(fill="x", pady=2)
            except Exception:
                row.pack(fill="x", pady=2)
        elif not visible and packed:
            row.pack_forget()

    def show_antenna_settings(self, visible: bool) -> None:
        """Show antenna rows when Antennas is checked."""
        fr = self._ant_frame
        if fr is None:
            return
        packed = bool(fr.winfo_manager())
        if visible and not packed:
            try:
                fr.pack(fill="x", pady=(0, 4), before=self.btn_row)
            except Exception:
                fr.pack(fill="x", pady=(0, 4))
        elif not visible and packed:
            fr.pack_forget()

    def _add_antenna_block(self, ant: dict | None = None, *, notify: bool = True) -> None:
        """One antenna and the rotator devices under it.

        Other device kinds already in the file are kept on save and are
        not edited here.
        """
        tk = self.tk
        src = ant or {}
        aid = str(src.get("id") or "").strip() or new_antenna_id()
        block = tk.Frame(self._ant_rows, bg="#f4f4f4")
        block.pack(fill="x", pady=(2, 1))
        name = tk.StringVar(value=str(src.get("name") or ""))
        kept = [
            d for d in (src.get("devices") or [])
            if isinstance(d, dict) and str(d.get("kind") or "") != "rotator"
        ]
        ed: dict = {
            "id": aid, "block": block, "name": name,
            "devices": [], "kept": kept,
        }
        self._ant_editors.append(ed)
        head = tk.Frame(block, bg="#f4f4f4")
        head.pack(fill="x")
        tk.Label(
            head, text="Antenna", font=_ui_font(10),
            bg="#f4f4f4", fg="#333333",
        ).pack(side="left")
        name_ent = tk.Entry(head, textvariable=name, width=16, font=_ui_font(11))
        name_ent.pack(side="left", padx=(2, 6))
        name_ent.bind("<FocusOut>", lambda _e: self._emit_antennas())
        name_ent.bind("<Return>", lambda _e: self._emit_antennas())
        tk.Button(
            head, text="Remove", font=_ui_font(10),
            command=lambda this=ed: self._remove_antenna_block(this),
            padx=4, pady=0,
        ).pack(side="left")
        dev_fr = tk.Frame(block, bg="#f4f4f4")
        dev_fr.pack(fill="x", padx=(12, 0))
        ed["dev_frame"] = dev_fr
        rotators = [
            d for d in (src.get("devices") or [])
            if isinstance(d, dict) and str(d.get("kind") or "rotator") == "rotator"
        ]
        if ant is None:
            rotators = [{}]
        for dev in rotators:
            self._add_rotator_device(ed, dev, notify=False)
        tk.Button(
            block, text="Add rotator", font=_ui_font(10),
            command=lambda this=ed: self._add_rotator_device(this),
            padx=4, pady=0,
        ).pack(anchor="w", padx=(12, 0))
        self._refresh_antenna_warn()
        if notify:
            self._emit_antennas()

    def _add_rotator_device(
        self, ant: dict, dev: dict | None = None, *, notify: bool = True,
    ) -> None:
        tk = self.tk
        src = dev or {}
        did = str(src.get("id") or "").strip() or new_device_id()
        row = tk.Frame(ant["dev_frame"], bg="#f4f4f4")
        row.pack(fill="x", pady=1)
        host = tk.StringVar(value=str(src.get("host") or "127.0.0.1"))
        # A new rotator starts at the first port that is not the radio (4533).
        port_val = 4535 if not src else src.get("port")
        port = tk.StringVar(value="" if port_val is None else str(port_val))
        ded = {"id": did, "kind": "rotator", "row": row, "host": host, "port": port}
        ant["devices"].append(ded)
        tk.Label(
            row, text="Rotator", font=_ui_font(10),
            bg="#f4f4f4", fg="#333333",
        ).pack(side="left")
        tk.Label(
            row, text="Host", font=_ui_font(10),
            bg="#f4f4f4", fg="#333333",
        ).pack(side="left", padx=(6, 0))
        host_ent = tk.Entry(row, textvariable=host, width=14, font=_ui_font(11))
        host_ent.pack(side="left", padx=(2, 6))
        tk.Label(
            row, text="Port", font=_ui_font(10),
            bg="#f4f4f4", fg="#333333",
        ).pack(side="left")
        port_ent = tk.Entry(row, textvariable=port, width=6, font=_ui_font(11))
        port_ent.pack(side="left", padx=(2, 6))
        for widget in (host_ent, port_ent):
            widget.bind("<FocusOut>", lambda _e: self._emit_antennas())
            widget.bind("<Return>", lambda _e: self._emit_antennas())
        tk.Button(
            row, text="Remove", font=_ui_font(10),
            command=lambda this=ant, device=ded: self._remove_rotator_device(this, device),
            padx=4, pady=0,
        ).pack(side="left")
        self._refresh_antenna_warn()
        if notify:
            self._emit_antennas()

    def _remove_antenna_block(self, ed: dict) -> None:
        try:
            ed["block"].destroy()
        except Exception:
            pass
        self._ant_editors = [e for e in self._ant_editors if e is not ed]
        self._refresh_antenna_warn()
        self._emit_antennas()

    def _remove_rotator_device(self, ant: dict, dev: dict) -> None:
        try:
            dev["row"].destroy()
        except Exception:
            pass
        ant["devices"] = [d for d in ant["devices"] if d is not dev]
        self._refresh_antenna_warn()
        self._emit_antennas()

    def _refresh_antenna_warn(self) -> None:
        if self._ant_warn is None:
            return
        bad = False
        for ant in self._ant_editors:
            for dev in ant["devices"]:
                try:
                    if int(str(dev["port"].get()).strip()) == 4533:
                        bad = True
                except (TypeError, ValueError):
                    pass
        self._ant_warn.set(
            "Port 4533 belongs to the radio. Use the rotator port." if bad else ""
        )

    def _emit_antennas(self) -> None:
        self._refresh_antenna_warn()
        if not self._on_antennas_change:
            return
        rows = []
        for ant in self._ant_editors:
            devices = []
            for dev in ant["devices"]:
                devices.append({
                    "id": dev["id"],
                    "kind": "rotator",
                    "host": dev["host"].get(),
                    "port": dev["port"].get(),
                })
            for kept in ant.get("kept") or []:
                devices.append(kept)
            rows.append({
                "id": ant["id"],
                "name": ant["name"].get(),
                "devices": devices,
            })
        self._on_antennas_change(rows)

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
