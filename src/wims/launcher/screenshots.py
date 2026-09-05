# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Screenshot capture panel (map144-style) for documentation images.

Writes PNGs under ``docs/manual/images/`` using stable ids from
``docs/manual/shots.json``. Filename modes:

* **Standard name** — overwrites the canonical file used by User-manual.md
* **Add suffix** — ``site-operate_contest.png`` so the doc embed is untouched

Browser pages use headless Chrome; the launcher window uses ImageMagick
``import -window`` when available (Tk has no grab API).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from typing import Callable

_REPO = Path(__file__).resolve().parents[3]
_MANIFEST = _REPO / "docs" / "manual" / "shots.json"
_IMAGES = _REPO / "docs" / "manual" / "images"


def load_manifest(path: Path | None = None) -> dict:
    p = path or _MANIFEST
    return json.loads(p.read_text(encoding="utf-8"))


def image_dir(manifest: dict | None = None) -> Path:
    data = manifest or load_manifest()
    return _MANIFEST.parent / (data.get("image_dir") or "images")


def _chrome() -> str | None:
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        path = shutil.which(name)
        if path:
            return path
    return None


def capture_url(
    url: str,
    out: Path,
    *,
    width: int = 1280,
    height: int = 900,
    chrome: str | None = None,
) -> None:
    chrome = chrome or _chrome()
    if not chrome:
        raise RuntimeError("Chrome/Chromium not found on PATH")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wims-shot-") as td:
        shot = Path(td) / "shot.png"
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-size={width},{height}",
            f"--screenshot={shot}",
            url,
        ]
        proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=60)
        candidates = [shot, Path(td) / "screenshot.png"]
        src = next((p for p in candidates if p.is_file() and p.stat().st_size > 100), None)
        if src is None:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise RuntimeError(f"chrome screenshot failed for {url}: {err}")
        shutil.copyfile(src, out)


def capture_tk_window(root: tk.Misc, out: Path) -> None:
    """Grab a Tk toplevel into *out* (PNG). Prefers ImageMagick ``import``."""
    out.parent.mkdir(parents=True, exist_ok=True)
    root.update_idletasks()
    wid = hex(int(root.winfo_id()))
    import_bin = shutil.which("import")
    if import_bin:
        proc = subprocess.run(
            [import_bin, "-window", wid, str(out)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 100:
            return
        raise RuntimeError(
            f"ImageMagick import failed: {(proc.stderr or proc.stdout or '').strip()[-300:]}"
        )
    # Fallback: full-screen crop via gnome-screenshot if present (less precise).
    gs = shutil.which("gnome-screenshot")
    if gs:
        proc = subprocess.run(
            [gs, "-w", "-f", str(out)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 100:
            return
    raise RuntimeError(
        "No window grabber found. Install ImageMagick (`import`) or "
        "gnome-screenshot, or drop a PNG on docs/manual/images/ by hand."
    )


def out_path_for(shot_id: str, *, suffix: str = "", images: Path | None = None) -> Path:
    base = images or _IMAGES
    tag = ""
    if suffix:
        tag = "_" + suffix.lstrip("_ ").replace(" ", "_")
    return base / f"{shot_id}{tag}.png"


def rewrite_url(url: str, base: str | None) -> str:
    if not base:
        return url
    base = base.rstrip("/")
    for host in ("http://127.0.0.1:8787", "http://localhost:8787"):
        if url.startswith(host):
            return base + url[len(host):]
    return url


class ScreenshotPanel:
    """map144-style: checkboxes per shot, Capture Selected / All, standard vs suffix."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        launcher_root: tk.Misc | None = None,
        site_base: Callable[[], str] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.master = master
        self.launcher_root = launcher_root
        self._site_base = site_base or (lambda: "")
        self._on_log = on_log or (lambda _m: None)
        self._win: tk.Toplevel | None = None
        self._checks: dict[str, tk.BooleanVar] = {}
        self._mode = tk.StringVar(value="standard")
        self._suffix = tk.StringVar(value="")
        self._status: tk.Text | None = None
        self._manifest = load_manifest()

    def open(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        win = tk.Toplevel(self.master)
        win.title("WIMS — Screenshots")
        win.configure(bg="#f4f4f4")
        win.minsize(380, 520)
        self._win = win

        pad = {"padx": 12, "pady": 4}
        tk.Label(
            win,
            text="Capture to docs/manual/images/",
            font=("TkDefaultFont", 11, "bold"),
            bg="#f4f4f4",
        ).pack(anchor="w", **pad)
        tk.Label(
            win,
            text=str(image_dir(self._manifest)),
            font=("TkDefaultFont", 9),
            fg="#555555",
            bg="#f4f4f4",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=12)

        fr = tk.LabelFrame(win, text="Windows / pages", bg="#f4f4f4", padx=8, pady=6)
        fr.pack(fill="both", expand=True, padx=12, pady=8)
        self._checks.clear()
        for shot in self._manifest.get("shots") or []:
            sid = shot.get("id") or ""
            if not sid:
                continue
            kind = shot.get("kind") or "url"
            label = f"{sid}  ({kind})"
            var = tk.BooleanVar(value=(shot.get("status") != "stub"))
            cb = tk.Checkbutton(
                fr, text=label, variable=var, bg="#f4f4f4",
                activebackground="#f4f4f4", anchor="w",
            )
            cb.pack(fill="x", anchor="w")
            tip = shot.get("caption") or ""
            if tip:
                # lightweight tooltip via title
                cb.configure(text=f"{sid}  — {tip[:60]}")
            self._checks[sid] = var

        sel = tk.Frame(win, bg="#f4f4f4")
        sel.pack(fill="x", padx=12)
        tk.Button(sel, text="Select All", command=lambda: self._set_all(True)).pack(
            side="left"
        )
        tk.Button(sel, text="Select None", command=lambda: self._set_all(False)).pack(
            side="left", padx=6
        )

        mode = tk.LabelFrame(win, text="Filename", bg="#f4f4f4", padx=8, pady=6)
        mode.pack(fill="x", padx=12, pady=4)
        tk.Radiobutton(
            mode, text="Standard name (overwrites doc image)",
            variable=self._mode, value="standard", bg="#f4f4f4",
            activebackground="#f4f4f4",
        ).pack(anchor="w")
        row = tk.Frame(mode, bg="#f4f4f4")
        row.pack(fill="x", anchor="w")
        tk.Radiobutton(
            row, text="Add suffix:",
            variable=self._mode, value="suffix", bg="#f4f4f4",
            activebackground="#f4f4f4",
        ).pack(side="left")
        tk.Entry(row, textvariable=self._suffix, width=22).pack(side="left", padx=4)
        tk.Label(
            mode,
            text="Suffix example: contest_run → site-operate_contest_run.png",
            font=("TkDefaultFont", 8), fg="#666666", bg="#f4f4f4",
        ).pack(anchor="w")

        btns = tk.Frame(win, bg="#f4f4f4")
        btns.pack(fill="x", padx=12, pady=8)
        tk.Button(
            btns, text="Capture All", command=lambda: self.capture(all_shots=True),
            padx=10, pady=4,
        ).pack(side="left")
        tk.Button(
            btns, text="Capture Selected",
            command=lambda: self.capture(all_shots=False),
            padx=10, pady=4,
        ).pack(side="left", padx=8)

        self._status = tk.Text(
            win, height=8, font=("TkDefaultFont", 9),
            bg="#ffffff", fg="#222222", wrap="word",
        )
        self._status.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._status.insert("end", "Ready. Site server / :8790 should be up for URL shots.\n")
        self._status.configure(state="disabled")

        win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self._win is not None:
            self._win.destroy()
        self._win = None

    def _set_all(self, on: bool) -> None:
        for var in self._checks.values():
            var.set(on)

    def _log_status(self, lines: list[str]) -> None:
        text = "\n".join(lines) + "\n"
        if self._status is not None:
            self._status.configure(state="normal")
            self._status.delete("1.0", "end")
            self._status.insert("end", text)
            self._status.configure(state="disabled")
        for line in lines:
            self._on_log(line)

    def capture(self, *, all_shots: bool) -> None:
        shots = self._manifest.get("shots") or []
        images = image_dir(self._manifest)
        images.mkdir(parents=True, exist_ok=True)
        suffix = ""
        if self._mode.get() == "suffix":
            suffix = self._suffix.get().strip()
        base = (self._site_base() or "").strip() or None
        chrome = _chrome()
        lines: list[str] = []
        n_ok = 0

        for shot in shots:
            sid = shot.get("id") or ""
            if not sid:
                continue
            if not all_shots and not self._checks.get(sid, tk.BooleanVar(value=False)).get():
                continue
            kind = shot.get("kind") or "url"
            out = out_path_for(sid, suffix=suffix, images=images)
            try:
                if kind == "url":
                    if not chrome:
                        lines.append(f"  skip  {sid}  (no Chrome)")
                        continue
                    url = rewrite_url(shot.get("url") or "", base)
                    capture_url(
                        url, out,
                        width=int(shot.get("width") or 1280),
                        height=int(shot.get("height") or 900),
                        chrome=chrome,
                    )
                    lines.append(f"  OK    {out.name}")
                    n_ok += 1
                elif kind == "window" and shot.get("window") == "launcher":
                    root = self.launcher_root
                    if root is None:
                        lines.append(f"  skip  {sid}  (no launcher window)")
                        continue
                    capture_tk_window(root, out)
                    lines.append(f"  OK    {out.name}")
                    n_ok += 1
                elif kind == "placeholder":
                    lines.append(
                        f"  skip  {sid}  (placeholder — drop PNG on {out.name} by hand)"
                    )
                else:
                    lines.append(f"  skip  {sid}  (unknown kind {kind!r})")
            except Exception as e:
                lines.append(f"  FAIL  {sid}  ({e})")

        lines.insert(0, f"Captured {n_ok} → {images}")
        self._log_status(lines)
