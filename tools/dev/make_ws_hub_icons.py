#!/usr/bin/env python3
# WS Hub — regenerate the shipped desktop icons from one master image.
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate every WS Hub icon file the release ships.

The master is ``tools/dev/icons/ws-hub-1024.png``: white "WS" over "HUB"
on the WS-series blue (11, 92, 173) rounded square, letters only. It is the
same source as ``assets/icons/ws-hub.png`` in the WS Skim repo, so the two
apps share one look.

The output file names stay the old ``wims*`` names on purpose. Installed
desktop entries and shortcuts point at those paths, so an update swaps the
picture without a reinstall.

Run from anywhere (needs Pillow): ``python3 tools/dev/make_ws_hub_icons.py``
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "tools" / "dev" / "icons" / "ws-hub-1024.png"
PNG_DIR = ROOT / "scripts" / "assets"
ICO = ROOT / "scripts" / "windows" / "assets" / "wims.ico"

PNG_SIZES = {"wims.png": 256, "wims-128.png": 128, "wims-64.png": 64, "wims-48.png": 48}
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _scaled(master: Image.Image, px: int) -> Image.Image:
    return master.resize((px, px), Image.LANCZOS)


def main() -> int:
    master = Image.open(MASTER).convert("RGBA")
    for name, px in PNG_SIZES.items():
        # optimize=True with no timestamps keeps the bytes stable run to run.
        _scaled(master, px).save(PNG_DIR / name, format="PNG", optimize=True)
        print(f"wrote {PNG_DIR / name} ({px}px)")
    _scaled(master, 256).save(ICO, format="ICO", sizes=ICO_SIZES)
    print(f"wrote {ICO} ({', '.join(str(s[0]) for s in ICO_SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
