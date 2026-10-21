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


# N1MM's documented band tag is the band edge in MHz ("144", "50", "3.5", "3,5").
# A bare meter number is also seen on the wire ("2" for 2 meters). Those integers
# are not MHz edges, so reading them as MHz stores a 2 m QSO as 160 m and the
# roster keeps the station as a new multiplier.
_METER_BANDS = {
    "160": "160m",
    "80": "80m",
    "40": "40m",
    "30": "30m",
    "20": "20m",
    "17": "17m",
    "15": "15m",
    "12": "12m",
    "6": "6m",
    "2": "2m",
    "1.25": "1.25m",
}


def _band(v, freq=None) -> str:
    """Band label from N1MM's ``<band>`` and, when present, tx/rx frequency.

    Frequency is N1MM's 10 Hz units (or kHz in a database column). It wins
    when it lands in a ham band, so ``<band>2</band>`` plus a 144 MHz frequency
    is 2 m. A label such as ``2M`` or ``70cm`` is used as written. A comma
    decimal (``3,5``) is 3.5 MHz.
    """
    label = (str(v) if v is not None else "").strip()
    low = label.lower().replace(" ", "")
    if low.endswith("cm") or low.endswith("m"):
        return low
    if freq not in (None, ""):
        from wims.core.bands import band_label, in_ham_band, n1mm_raw_to_hz
        hz = n1mm_raw_to_hz(freq)
        if hz and in_ham_band(hz):
            return band_label(hz, apply_if=False)
    token = label.replace(",", ".").strip()
    if token in _METER_BANDS:
        return _METER_BANDS[token]
    try:
        return band_label_mhz(float(token))
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
    # Optional ADIF / contest fields. Defaults keep older constructors working.
    submode: str | None = None
    qso_date: str | None = None
    time_on: str | None = None
    exchange: str | None = None
    state: str | None = None
    section: str | None = None
    my_state: str | None = None
    my_county: str | None = None
    dxcc: str | None = None
    contest_id: str | None = None
    # "logged" when the QSO datagram carried a grid. "remembered" when WIMS
    # filled a blank grid from a decode. Never written back to the WSJT-X file.
    grid_source: str | None = None
    cqz: str | None = None
    ituz: str | None = None
    cont: str | None = None
    # True when the ADIF log already says this contact is confirmed.
    # Card, LoTW, and eQSL are decided in ``wims.adif.CONFIRMED_QSL_FIELDS``.
    # N1MM rows stay false: that log does not carry those fields.
    confirmed: bool = False

    @classmethod
    def _from_dict(cls, d: dict, source: str) -> "LoggedQso":
        """d has lowercased keys from either feed."""
        return cls(
            id=str(d.get("id") or "").strip(),
            call=(d.get("call") or "").strip().upper(),
            band=_band(d.get("band"), d.get("txfreq") or d.get("rxfreq") or d.get("freq")),
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
            cqz=(str(d.get("cqz")).strip() if d.get("cqz") not in (None, "") else None),
            ituz=(str(d.get("ituz")).strip() if d.get("ituz") not in (None, "") else None),
            cont=(str(d.get("cont")).strip().upper() if d.get("cont") not in (None, "") else None),
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
