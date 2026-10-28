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

"""One station identity for FT8/FT4 callsign tokens.

A compound or nonstandard call is sent in more than one shape. The CQ carries
the full call (``CQ P4/WE9V``). Later 77-bit messages hash it, and WSJT-X
prints the hash in angle brackets when it has seen the full call
(``<P4/WE9V>``) or as ``<...>`` when it has not. A standard message can also
carry only the home call (``WE9V``). Those tokens are one station when the
full call was just heard on the same instance and band.

``<...>`` is not a station. The home call of a different station (``WE9V`` at
home, ``P4/WE9V`` in Aruba) stays separate unless a recent full call on that
band links them.
"""

from __future__ import annotations

import re

# How long a full compound call still explains a hashed or home-call token.
# Long enough for an FT8/FT4 contact with a few repeats. Short enough that a
# home station calling later is not swallowed.
COMPOUND_LINK_S = 180.0

# A root call has a letter after its digit run (WE9V, W1XX, 2E0ABC).
# Prefixes and portable tags do not: P4, VE3, KH6, QRP, MM, P, R.
_ROOT = re.compile(r"^(?:[A-Z0-9]+)?[A-Z]+[0-9]+[A-Z]+$")


def is_unresolved_hash(token: str | None) -> bool:
    """True for WSJT-X ``<...>`` (a hash with no call yet)."""
    if token is None:
        return False
    text = str(token).strip().upper()
    if len(text) < 2 or text[0] != "<" or text[-1] != ">":
        return False
    inner = text[1:-1].strip()
    return not inner or set(inner) <= {"."}


def plain_call(token: str | None) -> str | None:
    """Callsign with one pair of angle brackets removed.

    ``<P4/WE9V>`` is ``P4/WE9V``. An unresolved hash is None. Other text is
    uppercased and returned unchanged.
    """
    if token is None:
        return None
    text = str(token).strip().upper()
    if not text:
        return None
    if text[0] == "<" and text[-1] == ">" and len(text) >= 2:
        if is_unresolved_hash(text):
            return None
        text = text[1:-1].strip()
    if not text or set(text) <= {"."}:
        return None
    return text


def home_call(call: str | None) -> str:
    """The root call inside a compound token.

    ``P4/WE9V``, ``WE9V/P``, ``WE9V/QRP``, ``WE9V/MM``, and ``VE3/W1XX`` all
    yield the root (``WE9V`` or ``W1XX``). A plain call yields itself. Two
    roots (``K1ABC/W1XX``) yield ``""`` so they are not guessed.
    """
    plain = plain_call(call)
    if not plain:
        return ""
    parts = [part for part in plain.split("/") if part]
    roots = [part for part in parts if _ROOT.match(part)]
    if len(roots) == 1:
        return roots[0]
    return ""


def is_compound_call(call: str | None) -> bool:
    """True when the token has a slash and one root that is not the whole call."""
    plain = plain_call(call)
    if not plain or "/" not in plain:
        return False
    home = home_call(plain)
    return bool(home) and home != plain


def same_home(a: str | None, b: str | None) -> bool:
    """True when both tokens are the same call or share one root."""
    left = plain_call(a)
    right = plain_call(b)
    if not left or not right:
        return False
    if left == right:
        return True
    home_left = home_call(left)
    home_right = home_call(right)
    return bool(home_left and home_left == home_right)
