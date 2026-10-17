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

"""US states, DC, and Canadian provinces — postal abbreviations only.

Original list of well-known postal abbreviations and their names. This is not
a county file and not a callsign-prefix file. WIMS does not ship either of
those, and this module does not invent them.
"""

from __future__ import annotations

import unicodedata

# Fifty states. DC is separate and does not count for Worked All States.
US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

DC: dict[str, str] = {"DC": "District of Columbia"}

# Ten provinces and three territories.
CA_PROVINCES: dict[str, str] = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}

TERRITORIES = frozenset({"NT", "NU", "YT"})

_EXTRA_NAMES = {
    "PEI": "PE",
    "NFLD": "NL",
    "NEWFOUNDLAND": "NL",
    "LABRADOR": "NL",
}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.upper().split())


def _name_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for table in (US_STATES, DC, CA_PROVINCES):
        for abbr, name in table.items():
            out[_fold(name)] = abbr
            out[abbr] = abbr
    out.update(_EXTRA_NAMES)
    return out


_BY_NAME = _name_index()


def canonical_place(value: str | None) -> str | None:
    """Postal abbreviation for a state, DC, or province. Empty if unknown."""
    token = _fold(value or "")
    if not token:
        return None
    return _BY_NAME.get(token)


def is_us_state(abbr: str | None) -> bool:
    return bool(abbr) and abbr in US_STATES


def place_name(abbr: str | None) -> str:
    if not abbr:
        return ""
    return US_STATES.get(abbr) or DC.get(abbr) or CA_PROVINCES.get(abbr) or abbr


def place_word(abbr: str | None) -> str:
    """Plain word for a sentence: state, district, province, or territory."""
    if abbr in TERRITORIES:
        return "territory"
    if abbr in CA_PROVINCES:
        return "province"
    if abbr == "DC":
        return "district"
    return "state"
