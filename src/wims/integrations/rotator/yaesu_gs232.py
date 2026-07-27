# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Yaesu GS-232 family command/response helpers (K3NG-compatible subset).

Pure string builders/parsers — no sockets. Site K3NG builds vary (A vs B);
these cover the common subset:

  C / C2     — request az (C2 may include elevation)
  Mxxx       — move to azimuth (degrees, 0–450 on some builds; we use 0–359)
  A or S     — stop

Confirm dialect on the deployed K3NG before trusting live control.
"""

from __future__ import annotations

import re

# Responses seen in the wild: "+0nnn" (4-digit), "AZ=nnn", "AZ=nnn EL=nnn", "nnn"
_AZ_RE = re.compile(
    r"(?:AZ\s*=\s*)?([+-]?\d{1,4})(?:\s*(?:EL\s*=\s*([+-]?\d{1,3})))?",
    re.IGNORECASE,
)


def cmd_read_az(*, long_form: bool = True) -> bytes:
    """Poll position. Prefer C2 (az+el) when the controller supports it."""
    return b"C2\r" if long_form else b"C\r"


def cmd_move_az(az: float) -> bytes:
    """Move to az degrees true (rounded, clamped 0–359)."""
    n = int(round(float(az))) % 360
    return f"M{n:03d}\r".encode("ascii")


def cmd_stop() -> bytes:
    """Stop rotation (GS-232 ``A``)."""
    return b"A\r"


def parse_position(raw: bytes | str) -> tuple[float | None, float | None]:
    """Extract (az, el) from a controller response. el may be None.

    Returns (None, None) if nothing parseable.
    """
    if isinstance(raw, bytes):
        text = raw.decode("ascii", "replace")
    else:
        text = str(raw)
    text = text.strip().replace("\r", " ").replace("\n", " ")
    if not text:
        return None, None
    m = _AZ_RE.search(text)
    if not m:
        # Bare three-digit leftover (some firmwares)
        m2 = re.search(r"\b(\d{1,3})\b", text)
        if not m2:
            return None, None
        az = float(m2.group(1)) % 360.0
        return az, None
    az = float(m.group(1)) % 360.0
    el = None
    if m.group(2) is not None:
        el = float(m.group(2))
    return az, el
