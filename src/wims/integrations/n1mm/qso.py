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

"""Unified logged-QSO record from N1MM's two feeds (plan §3.6).

Both the live `<contactinfo>` / `<contactreplace>` UDP broadcasts and the `DXLOG`
rows of N1MM's `.s3db` describe the same QSO with the same field names and the
same unique `ID`, so they collapse to one `LoggedQso`. The DB read seeds the log
copy at cold start; live add/edit/delete keep it current; both dedup on `id`.

N1MM contact UDP roots (Broadcast Data → Contacts):
  - `<contactinfo>`   — new QSO logged
  - `<contactdelete>` — QSO deleted (or first half of an edit)
  - `<contactreplace>` — edited QSO (second half of an edit; same fields as contactinfo)
"""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from wims.core.bands import band_label_mhz

_FALSEY = {"", "0", "false", "no", "n"}
# Roots that carry a full contact record (upsert into the log copy).
_LIVE_UPSERT_ROOTS = frozenset({"contactinfo", "contactreplace"})


def _truthy(v) -> bool:
    return str(v).strip().lower() not in _FALSEY


def _grid(v) -> str | None:
    s = (str(v) if v is not None else "").strip().upper()
    return s or None


def _band(v) -> str:
    try:
        return band_label_mhz(float(v))
    except (TypeError, ValueError):
        return "?"


def _fields(xml_text: str) -> tuple[str, dict[str, str]]:
    """Return (root_tag_lower, {tag_lower: text}) for an N1MM XML datagram."""
    root = ET.fromstring(xml_text)
    d = {c.tag.lower(): (c.text or "").strip() for c in root}
    return root.tag.lower(), d


def id_from_contactdelete(xml_text: str) -> str | None:
    """Extract the unique QSO ID from a `<contactdelete>` packet, or None."""
    tag, d = _fields(xml_text)
    if tag != "contactdelete":
        return None
    qid = (d.get("id") or "").strip()
    return qid or None


@dataclass
class LoggedQso:
    id: str
    call: str
    band: str            # normalized label, e.g. "20m"
    grid: str | None
    mode: str | None
    points: int
    is_mult: bool        # any of N1MM's ismultiplier1/2/3
    contest: str | None
    timestamp: str | None
    operator: str | None
    rover_location: str | None
    source: str          # "seed" (DB) or "live" (broadcast)

    @classmethod
    def _from_dict(cls, d: dict, source: str) -> "LoggedQso":
        """d has lowercased keys from either feed."""
        return cls(
            id=str(d.get("id") or "").strip(),
            call=(d.get("call") or "").strip().upper(),
            band=_band(d.get("band")),
            grid=_grid(d.get("gridsquare")),
            mode=(d.get("mode") or None),
            points=int(float(d.get("points") or 0)),
            is_mult=any(_truthy(d.get(k)) for k in
                        ("ismultiplier1", "ismultiplier2", "ismultiplier3")),
            contest=(d.get("contestname") or None),
            timestamp=(d.get("timestamp") or d.get("ts") or None),
            operator=(d.get("operator") or None),
            rover_location=(d.get("roverlocation") or None),
            source=source,
        )

    @classmethod
    def from_contactinfo(cls, xml_text: str) -> "LoggedQso":
        """Parse `<contactinfo>` or `<contactreplace>` (same field set)."""
        tag, d = _fields(xml_text)
        if tag not in _LIVE_UPSERT_ROOTS:
            raise ValueError(f"expected contactinfo/contactreplace, got <{tag}>")
        return cls._from_dict(d, source="live")

    @classmethod
    def from_dxlog_row(cls, row: dict) -> "LoggedQso":
        d = {str(k).lower(): v for k, v in row.items()}
        return cls._from_dict(d, source="seed")
