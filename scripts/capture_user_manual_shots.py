#!/usr/bin/env python3
# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refresh user-manual screenshots from docs/manual/shots.json.

Same catalog as the launcher **Screenshots…** panel. Stable filenames under
docs/manual/images/ — re-run after UI changes; User-manual.md keeps the same
paths. Use ``--suffix`` for a variant that does not overwrite the doc embed.

Usage:
  python scripts/capture_user_manual_shots.py
  python scripts/capture_user_manual_shots.py --only site-operate,site-n1mm
  python scripts/capture_user_manual_shots.py --suffix contest_run
  WIMS_MANUAL_BASE=http://192.168.1.119:8787 python scripts/capture_user_manual_shots.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wims.launcher.screenshots import (  # noqa: E402
    _chrome,
    capture_url,
    image_dir,
    load_manifest,
    out_path_for,
    rewrite_url,
)


def _placeholder_png(path: Path, title: str, note: str) -> None:
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
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="comma-separated shot ids")
    ap.add_argument(
        "--suffix",
        default="",
        help="append _SUFFIX before .png (does not overwrite canonical doc images)",
    )
    ap.add_argument(
        "--force-placeholders",
        action="store_true",
        help="rewrite stub PNGs even if a real file already exists",
    )
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args(argv)

    data = load_manifest(args.manifest) if args.manifest else load_manifest()
    shots = data.get("shots") or []
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    base = (os.environ.get("WIMS_MANUAL_BASE") or "").strip() or None
    chrome = _chrome()
    images = image_dir(data)
    images.mkdir(parents=True, exist_ok=True)
    suffix = args.suffix.strip()

    ok = fail = skip = 0
    for shot in shots:
        sid = shot.get("id") or ""
        if only and sid not in only:
            continue
        out = out_path_for(sid, suffix=suffix, images=images)
        kind = shot.get("kind") or "url"
        caption = shot.get("caption") or sid

        try:
            if kind == "url":
                if not chrome:
                    print(f"[SKIP] {sid}: no Chrome/Chromium on PATH")
                    skip += 1
                    continue
                url = rewrite_url(shot["url"], base)
                w = int(shot.get("width") or 1280)
                h = int(shot.get("height") or 900)
                print(f"[SHOT] {sid} ← {url}")
                capture_url(
                    url, out, width=w, height=h,
                    wait_ms=int(shot.get("wait_ms") or 2500),
                    chrome=chrome,
                )
                print(f"       → {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
                ok += 1
            elif kind == "window":
                print(
                    f"[SKIP] {sid}: window shot — use launcher Screenshots… panel"
                )
                skip += 1
            elif kind == "placeholder":
                if out.is_file() and out.stat().st_size > 2000 and not args.force_placeholders:
                    print(f"[KEEP] {sid} (existing {out.name})")
                    skip += 1
                    continue
                print(f"[STUB] {sid}")
                _placeholder_png(out, caption, shot.get("note") or "")
                ok += 1
            else:
                print(f"[SKIP] {sid}: unknown kind {kind!r}")
                skip += 1
        except Exception as e:
            print(f"[FAIL] {sid}: {e}", file=sys.stderr)
            fail += 1

    print(f"Done: ok={ok} fail={fail} skip={skip}  images={images}")
    print("Markdown embeds use fixed paths — no User-manual.md edit needed for standard names.")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
