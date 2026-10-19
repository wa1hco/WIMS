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

"""Operate roster show-menu: which heard stations stay on the page.

The console applies the same rule in ``wims.js`` (``rosKeepCandidate``) to
fields the server already parsed for the Message column: ``is_cq`` and
``message_tail``. This module does not read the datagram again.

Modes, in menu order:

* ``needed`` — stations marked needed (the old checked box).
* ``needed-cq`` — those whose latest decode is a CQ, including CQ NA / CQ DX.
* ``needed-73`` — those, or a 73 / RR73 sign-off. RR73 followed by a grid
  still counts. These stations are free to call.
* ``all`` — no filter (the old unchecked box).

A saved checked checkbox (``True`` / ``"1"``) loads as Needed. Unchecked
(``False`` / ``"0"``) loads as All.
"""

from __future__ import annotations

from wims.udp.messages import _interpret_decode

MODES = ("needed", "needed-cq", "needed-73", "all")

# Whole tokens in the Message-column tail. RRR is a mid-QSO ack, not a
# station that is free to call.
_FREE_SIGNOFF = frozenset({"73", "RR73"})

_CHECKED = frozenset({"true", "1", "yes", "on", "checked"})
_UNCHECKED = frozenset({"false", "0", "no", "off", "unchecked"})


def normalize_need_filter(saved) -> str:
    """Map a stored show-menu value, or an old checkbox, to a mode name.

    Missing storage is Needed, which is what the checked box did on each load.
    """
    if saved is None:
        return "needed"
    if isinstance(saved, bool):
        return "needed" if saved else "all"
    text = str(saved).strip().lower()
    if text in MODES:
        return text
    if text in _CHECKED:
        return "needed"
    if text in _UNCHECKED:
        return "all"
    if text == "":
        return "needed"
    return "needed"


def tail_is_free_signoff(message_tail: str | None) -> bool:
    """True when the Message-column tail is 73 or RR73, optionally plus a grid.

    The tail is the text ``_interpret_decode`` already split off after the
    callsigns. ``RR73 FN42`` keeps both tokens, so the sign-off still matches.
    """
    text = (message_tail or "").strip()
    if not text:
        return False
    return any(tok.upper() in _FREE_SIGNOFF for tok in text.split())


def row_visible(*, is_needed: bool, is_cq: bool, message_tail: str | None,
                mode: str) -> bool:
    """Whether one roster row stays visible for this show-menu mode."""
    chosen = normalize_need_filter(mode)
    if chosen == "all":
        return True
    if not is_needed:
        return False
    if chosen == "needed":
        return True
    if chosen == "needed-cq":
        return bool(is_cq)
    if chosen == "needed-73":
        return bool(is_cq) or tail_is_free_signoff(message_tail)
    return True


def visible_decode(message: str | None, *, is_needed: bool, mode: str) -> bool:
    """Filter one decode text. CQ and the tail come from the Message parser."""
    is_cq, _dx, _to, _grid, tail = _interpret_decode(message)
    return row_visible(
        is_needed=is_needed, is_cq=is_cq, message_tail=tail, mode=mode,
    )
