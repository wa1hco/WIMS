# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prefix → PFX / CQZ / ITUZ for N1MM Log ADIF.

N1MM's TCP Log insert does not run Entry-window CTY / Call History lookup.
Edit Contact then has CALL and GRID but empty Callsign Info (country, zones).
These fields are in N1MM's documented Log ADIF tag list.
"""

from __future__ import annotations

# Longest prefix first. Zones are contest defaults, not a full wl_cty.dat.
_PREFIX = (
    ("KL7", "KL", 1, 1),
    ("KH6", "KH6", 31, 61),
    ("KP4", "KP4", 8, 11),
    ("KP2", "KP2", 8, 11),
    ("VY1", "VY1", 1, 2),
    ("VY2", "VY2", 5, 9),
    ("VO1", "VO", 5, 9),
    ("VO2", "VO", 2, 9),
    ("VE", "VE", 4, 4),
    ("VA", "VE", 4, 4),
    ("VY", "VE", 4, 4),
    ("VO", "VO", 5, 9),
    ("XE", "XE", 6, 10),
    ("CO", "CM", 8, 11),
    ("CM", "CM", 8, 11),
    ("HI", "HI", 8, 11),
    ("C6", "C6", 8, 11),
    ("ZF", "ZF", 8, 11),
    ("VP5", "VP5", 8, 11),
    ("VP9", "VP9", 5, 11),
    ("J3", "J3", 8, 11),
    ("P4", "P4", 9, 11),
    ("PJ2", "PJ2", 9, 11),
    ("PJ4", "PJ4", 9, 11),
    ("FY", "FY", 9, 12),
    ("FM", "FM", 8, 11),
    ("FS", "FS", 8, 11),
    ("G", "G", 14, 27),
    ("M", "G", 14, 27),
    ("2", "G", 14, 27),
    ("DL", "DL", 14, 28),
    ("DA", "DL", 14, 28),
    ("DB", "DL", 14, 28),
    ("DC", "DL", 14, 28),
    ("DD", "DL", 14, 28),
    ("DE", "DL", 14, 28),
    ("DF", "DL", 14, 28),
    ("DG", "DL", 14, 28),
    ("DH", "DL", 14, 28),
    ("DI", "DL", 14, 28),
    ("DJ", "DL", 14, 28),
    ("DK", "DL", 14, 28),
    ("F", "F", 14, 27),
    ("EA", "EA", 14, 37),
    ("I", "I", 15, 28),
    ("PA", "PA", 14, 27),
    ("ON", "ON", 14, 27),
    ("OK", "OK", 15, 28),
    ("SP", "SP", 15, 28),
    ("S5", "S5", 15, 28),
    ("HA", "HA", 15, 28),
    ("OE", "OE", 15, 28),
    ("HB", "HB", 14, 28),
    ("SM", "SM", 14, 18),
    ("LA", "LA", 14, 18),
    ("OH", "OH", 15, 18),
    ("OZ", "OZ", 14, 18),
    ("LY", "LY", 15, 29),
    ("YL", "YL", 15, 29),
    ("ES", "ES", 15, 29),
    ("UA9", "UA9", 17, 30),
    ("UA0", "UA9", 19, 25),
    ("UA", "UA", 16, 29),
    ("R", "UA", 16, 29),
    ("JA", "JA", 25, 45),
    ("JE", "JA", 25, 45),
    ("JF", "JA", 25, 45),
    ("JG", "JA", 25, 45),
    ("JH", "JA", 25, 45),
    ("JI", "JA", 25, 45),
    ("JJ", "JA", 25, 45),
    ("JK", "JA", 25, 45),
    ("JL", "JA", 25, 45),
    ("JM", "JA", 25, 45),
    ("JN", "JA", 25, 45),
    ("JO", "JA", 25, 45),
    ("JP", "JA", 25, 45),
    ("JQ", "JA", 25, 45),
    ("JR", "JA", 25, 45),
    ("JS", "JA", 25, 45),
    ("7J", "JA", 25, 45),
    ("HL", "HL", 25, 44),
    ("BY", "BY", 24, 44),
    ("BA", "BY", 24, 44),
    ("BD", "BY", 24, 44),
    ("BG", "BY", 24, 44),
    ("BH", "BY", 24, 44),
    ("BV", "BV", 24, 44),
    ("VR", "VR2", 24, 44),
    ("VK", "VK", 30, 59),
    ("ZL", "ZL", 32, 60),
    ("PY", "PY", 11, 15),
    ("LU", "LU", 13, 14),
    ("CE", "CE", 12, 14),
    ("HK", "HK", 9, 12),
    ("YV", "YV", 9, 12),
    ("HC", "HC", 10, 12),
    ("OA", "OA", 10, 12),
    ("ZP", "ZP", 11, 14),
    ("CX", "CX", 13, 14),
    ("ZS", "ZS", 38, 57),
    ("4X", "4X", 20, 39),
    ("TA", "TA", 20, 39),
    ("SV", "SV", 20, 28),
    ("YO", "YO", 20, 28),
    ("LZ", "LZ", 20, 28),
    ("YU", "YT", 15, 28),
    ("YT", "YT", 15, 28),
    ("E7", "E7", 15, 28),
    ("9A", "9A", 15, 28),
    ("OM", "OM", 15, 28),
    ("UR", "UR", 16, 29),
    ("EU", "EU", 16, 29),
    ("ER", "ER", 16, 29),
    ("LY", "LY", 15, 29),
)

_US_CQ = {0: 4, 1: 5, 2: 5, 3: 5, 4: 5, 5: 4, 6: 3, 7: 3, 8: 4, 9: 4}
_US_ITU = {0: 7, 1: 8, 2: 8, 3: 8, 4: 8, 5: 7, 6: 6, 7: 6, 8: 8, 9: 8}
_VE_CQ = {1: 5, 2: 5, 3: 4, 4: 4, 5: 4, 6: 4, 7: 3, 8: 1, 9: 5, 0: 4}
_VE_ITU = {1: 9, 2: 9, 3: 4, 4: 3, 5: 3, 6: 2, 7: 2, 8: 3, 9: 9, 0: 4}


def _bare_call(call: str) -> str:
    s = (call or "").strip().upper()
    if not s:
        return ""
    # Portable /P /M /R /MM or DX prefix like F/W1ABC — use the home call.
    if "/" in s:
        parts = [p for p in s.split("/") if p]
        if len(parts) >= 2 and len(parts[0]) <= 3 and any(c.isdigit() for c in parts[1]):
            s = parts[1]
        else:
            s = parts[0]
    return s


def _call_digit(call: str) -> int | None:
    for ch in call:
        if ch.isdigit():
            return int(ch)
    return None


def lookup_pfx(call: str) -> tuple[str, int, int] | None:
    """Return (PFX, CQZ, ITUZ) or None."""
    s = _bare_call(call)
    if not s:
        return None
    digit = _call_digit(s)
    for pre, pfx, cqz, ituz in _PREFIX:
        if s.startswith(pre):
            if pfx == "VE" and digit is not None:
                return pfx, _VE_CQ.get(digit, cqz), _VE_ITU.get(digit, ituz)
            return pfx, cqz, ituz
    if s[0] in "KNW" or (s[0] == "A" and len(s) >= 2 and s[1].isalpha()):
        area = digit if digit is not None else 2
        return "K", _US_CQ.get(area, 5), _US_ITU.get(area, 8)
    return None
