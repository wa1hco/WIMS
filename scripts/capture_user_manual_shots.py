#!/usr/bin/env python3
# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refresh user-manual screenshots from docs/manual/shots.json.

Stable filenames under docs/manual/images/ — re-run this after UI changes;
docs/User-manual.md keeps the same image paths.

Usage:
  python scripts/capture_user_manual_shots.py
  python scripts/capture_user_manual_shots.py --only site-operate,site-status
  WIMS_MANUAL_BASE=http://192.168.1.119:8787 python scripts/capture_user_manual_shots.py

Requires Google Chrome/Chromium for kind=url shots. Placeholder shots get a
labeled stub PNG if missing (or --force-placeholders).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "manual"
MANIFEST = MANUAL / "shots.json"
IMAGES = MANUAL / "images"


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


def _rewrite_url(url: str, base: str | None) -> str:
    if not base:
        return url
    # Replace localhost site-console origin with WIMS_MANUAL_BASE when set.
    base = base.rstrip("/")
    for host in ("http://127.0.0.1:8787", "http://localhost:8787"):
        if url.startswith(host):
            return base + url[len(host) :]
    return url


def _placeholder_png(path: Path, title: str, note: str) -> None:
    """Write a simple stub image (Pillow if available, else minimal PNG)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont

        im = Image.new("RGB", (1100, 640), (244, 244, 244))
        d = ImageDraw.Draw(im)
        d.rectangle([20, 20, 1079, 619], outline=(11, 92, 173), width=4)
        font = ImageFont.load_default()
        d.text((40, 40), "WIMS manual screenshot stub", fill=(11, 92, 173), font=font)
        d.text((40, 80), title, fill=(30, 30, 30), font=font)
        d.text((40, 120), note or "Replace with a real capture.", fill=(80, 80, 80), font=font)
        d.text((40, 180), f"File: {path.name}", fill=(100, 100, 100), font=font)
        im.save(path, "PNG")
        return
    except Exception:
        pass
    # 1x1 PNG fallback (still a valid image embed).
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def capture_url(chrome: str, url: str, out: Path, width: int, height: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wims-shot-") as td:
        # Chrome writes screenshot.png into cwd when --screenshot has no path
        # on some builds; prefer explicit path.
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
        proc = subprocess.run(
            cmd, cwd=td, capture_output=True, text=True, timeout=60,
        )
        # Some Chrome builds ignore the path and write screenshot.png in cwd.
        candidates = [shot, Path(td) / "screenshot.png"]
        src = next((p for p in candidates if p.is_file() and p.stat().st_size > 100), None)
        if src is None:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise RuntimeError(f"chrome screenshot failed for {url}: {err}")
        shutil.copyfile(src, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated shot ids to refresh (default: all)",
    )
    ap.add_argument(
        "--force-placeholders",
        action="store_true",
        help="rewrite stub PNGs even if a real file already exists",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST,
        help="path to shots.json",
    )
    args = ap.parse_args(argv)

    if not args.manifest.is_file():
        print(f"ERROR: missing manifest {args.manifest}", file=sys.stderr)
        return 2

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    shots = data.get("shots") or []
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    base = (os.environ.get("WIMS_MANUAL_BASE") or "").strip() or None
    chrome = _chrome()
    images = args.manifest.parent / (data.get("image_dir") or "images")
    images.mkdir(parents=True, exist_ok=True)

    ok = fail = skip = 0
    for shot in shots:
        sid = shot.get("id") or ""
        if only and sid not in only:
            continue
        out = images / f"{sid}.png"
        kind = shot.get("kind") or "url"
        caption = shot.get("caption") or sid

        try:
            if kind == "url":
                if not chrome:
                    print(f"[SKIP] {sid}: no Chrome/Chromium on PATH")
                    skip += 1
                    continue
                url = _rewrite_url(shot["url"], base)
                w = int(shot.get("width") or 1280)
                h = int(shot.get("height") or 900)
                print(f"[SHOT] {sid} ← {url}")
                capture_url(chrome, url, out, w, h)
                print(f"       → {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
                ok += 1
            elif kind == "placeholder":
                if out.is_file() and out.stat().st_size > 2000 and not args.force_placeholders:
                    print(f"[KEEP] {sid} (existing {out.name})")
                    skip += 1
                    continue
                note = shot.get("note") or ""
                print(f"[STUB] {sid}")
                _placeholder_png(out, caption, note)
                ok += 1
            else:
                print(f"[SKIP] {sid}: unknown kind {kind!r}")
                skip += 1
        except Exception as e:
            print(f"[FAIL] {sid}: {e}", file=sys.stderr)
            fail += 1

    print(f"Done: ok={ok} fail={fail} skip={skip}  images={images}")
    print("Markdown embeds use fixed paths — no User-manual.md edit needed.")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
