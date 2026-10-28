# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""DX cluster spot lines.

The line the nodes send is::

    DX de SPOTTER:     28074.0  K1ABC        FN42 FT8                 1734Z

Frequency is kilohertz when it is at least 1800 (160 m), otherwise megahertz
(``14.074``). Anything that is not a ``DX de`` spot is ignored. Announcements
are not spots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from wims.core.bands import band_label, in_ham_band

# Spotter, kHz or MHz, call, comment, HHMM, optional Z.
_DX = re.compile(
    r"^DX de\s+([A-Z0-9][A-Z0-9/\-#]{0,15})\s*:\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"([A-Z0-9][A-Z0-9/]{0,15})"
    r"(?:\s+(.*?))?\s+"
    r"(\d{4})Z?\s*$",
    re.IGNORECASE,
)
_GRID = re.compile(r"\b([A-R]{2}[0-9]{2}(?:[A-X]{2})?)\b", re.IGNORECASE)
_NOT_GRID = {"RR73"}
_LOGIN_CALL = re.compile(r"^[A-Z0-9]{3,10}(?:/[A-Z0-9]{1,4})?$")


@dataclass
class ParsedSpot:
    spotter: str
    freq_hz: int
    call: str
    comment: str
    grid: str | None
    hhmm: str
    band: str
    raw: str


def valid_login_call(call: str | None) -> bool:
    """A callsign we are willing to send as the login."""
    text = (call or "").strip().upper()
    if not _LOGIN_CALL.match(text):
        return False
    return any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)


def freq_to_hz(token: str) -> int | None:
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value >= 1800:
        hz = int(round(value * 1000))
    elif value >= 1.8:
        hz = int(round(value * 1_000_000))
    else:
        return None
    if not in_ham_band(hz):
        return None
    return hz


def grid_in_comment(comment: str | None) -> str | None:
    """First Maidenhead token in the comment, or None.

    ``RR73`` matches the shape of a grid and is not one.
    """
    if not comment:
        return None
    for match in _GRID.finditer(comment):
        grid = match.group(1).upper()
        if grid in _NOT_GRID:
            continue
        return grid
    return None


def parse_spot(line: str) -> ParsedSpot | None:
    """One ``DX de`` line, or None when the line is not a spot."""
    text = (line or "").strip()
    if not text.upper().startswith("DX DE"):
        return None
    match = _DX.match(text)
    if match is None:
        return None
    hz = freq_to_hz(match.group(2))
    if hz is None:
        return None
    call = match.group(3).upper()
    if not any(ch.isdigit() for ch in call):
        return None
    comment = (match.group(4) or "").strip()
    band = band_label(hz, apply_if=False)
    if not band or band == "?":
        return None
    return ParsedSpot(
        spotter=match.group(1).upper(),
        freq_hz=hz,
        call=call,
        comment=comment,
        grid=grid_in_comment(comment),
        hhmm=match.group(5),
        band=band,
        raw=text,
    )
