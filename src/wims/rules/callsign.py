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

"""Callsign shape shared by the country file and the builtin prefix list.

A portable or rover suffix does not change the DXCC entity. A leading or
trailing location prefix does (``W1/VE3XX`` and ``VE3XX/W1`` are the United
States). A few shapes are not prefixes. Both resolvers ask these helpers
before they trust a prefix match, so the rules cannot drift apart.

``/R`` is a rover only when it is not the leading piece. A leading ``R/``
is European Russia.
"""

from __future__ import annotations

# Suffixes that do not move the station. ``/R`` is a VHF rover.
# ``/M`` mobile, ``/MM`` maritime, ``/AM`` aeronautical, ``/P`` portable,
# ``/QRP`` low power, ``/A`` alternate, ``/B`` beacon, ``/LH`` lighthouse.
# A single digit (``/4``) is a call-area suffix and also does not move it.
PORTABLE = frozenset({
    "P", "M", "MM", "AM", "QRP", "R",
    "A", "LH", "N", "B", "PM", "J", "T", "S",
})

# VP8 plus one of these letters is not Falklands. The letter is the island.
_VP8_ISLAND = {
    "G": "VP8/G",
    "H": "VP8/H",
    "O": "VP8/O",
    "S": "VP8/S",
}


def normalize(call: str | None) -> str:
    if not call:
        return ""
    return (
        str(call)
        .upper()
        .replace("<", "")
        .replace(">", "")
        .strip()
    )


def is_portable(piece: str) -> bool:
    if piece in PORTABLE:
        return True
    return len(piece) == 1 and piece.isdigit()


def location_body(call: str | None) -> str:
    """The piece a prefix list should see.

    Trailing portable and rover suffixes are dropped. A leading piece is
    kept, so ``R/W1AW`` stays Russia and ``W1AW/R`` stays the home call.
    When two pieces remain, the shorter one (at most four characters) is
    the place they are operating from. A tie uses the right-hand piece
    (``K9CS/KH8S``).
    """
    raw = normalize(call)
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return ""
    if len(parts) > 1:
        head, tail = parts[0], parts[1:]
        tail = [p for p in tail if not is_portable(p)]
        parts = [head, *tail] if tail else [head]
    if len(parts) == 1:
        return parts[0]
    shorts = [p for p in parts if len(p) <= 4]
    pool = shorts or parts
    best = min(len(p) for p in pool)
    return [p for p in pool if len(p) == best][-1]


def kg4_kind(body: str) -> str | None:
    """``us`` for a three-letter KG4 suffix, ``gtmo`` for a shorter one.

    ``KG4LDK`` is a United States call. ``KG4AA`` and ``KG4/`` are
    Guantanamo Bay. ``None`` when the body is not a KG4 call. An exact
    call in the country file is applied by the caller before this.
    """
    if not body.startswith("KG4"):
        return None
    letters = "".join(ch for ch in body[3:] if ch.isalpha())
    if len(letters) >= 3:
        return "us"
    return "gtmo"


def kc4_antarctica(body: str) -> bool:
    """US Antarctic bases that are not ordinary KC4 calls.

    ``KC4AAA`` through ``KC4AAF``, and ``KC4US`` plus more letters
    (``KC4USB``, ``KC4USV``). Any other KC4 call is a United States call.
    An exact call in the file still wins, because the caller checks
    exact calls first.
    """
    if not body.startswith("KC4"):
        return False
    rest = body[3:]
    if rest in {"AAA", "AAB", "AAC", "AAD", "AAE", "AAF"}:
        return True
    return rest.startswith("US") and len(rest) >= 3


def island_key(call: str | None) -> str | None:
    """Prefix key for a shape the country file cannot write as one token.

    Examples: ``VP8LP/G`` is South Georgia (``VP8/G``), ``SV2ASP/A`` is
    Mount Athos (``SV/A``), ``CE0/X`` is San Felix (``CE0X``), ``3Y/B``
    is Bouvet, and ``3Y0J`` is Peter I (``3Y/P``). ``None`` when no
    rule applies. The caller looks that key up. A miss means the rule
    does not invent an entity the table does not have.
    """
    raw = normalize(call)
    if not raw:
        return None
    parts = [p for p in raw.split("/") if p]
    if len(parts) >= 2:
        left, right = parts[0], parts[1]
        if left.startswith("VP8") and right in _VP8_ISLAND:
            return _VP8_ISLAND[right]
        if (
            right == "A"
            and left.startswith("SV")
            and not left.startswith(("SV5", "SV9"))
        ):
            return "SV/A"
        if left == "3Y" and right in {"B", "P"}:
            return f"3Y/{right}"
        if left == "CE0" and len(right) == 1 and right in {"X", "Y", "Z", "I"}:
            return "CE0" + right
    body = location_body(raw)
    if body.startswith("3Y0"):
        return "3Y/P"
    return None
