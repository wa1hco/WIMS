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

"""Read-only ``cty.dat`` (AD1C country file) for continent and zones.

WIMS does not ship a country file and does not write one. It reads the copy
WSJT-X already keeps. The format is the country-file layout documented at
https://www.country-files.com/cty-dat-format/ : a primary line (name, CQ,
ITU, continent, lat, lon, offset, primary prefix) and comma-separated alias
prefixes. ``prefix(cq)[itu]`` is a zone override. A ``(lat/lon)`` pair is not
a zone.

A prefix with an explicit zone uses that zone. An entity whose prefixes all
agree, and whose primary prefix is not in the known multi-zone list below,
uses the primary zone. Otherwise the zone comes from the grid
(``rules/zones.py``). No grid, or a grid the table will not call, is zone
uncertain — the caller must not claim the station is needed for that zone.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from wims.rules.zones import cq_zone_from_grid, itu_zone_from_grid

# Primary prefixes that span more than one zone even when a cty.dat file
# records a single default number. Alaska (KL) and Hawaii (KH6) are separate
# entities in the country file, so they are not in this set.
# CQ: United States 3/4/5, Canada 1–5, Russia 16–19, Australia 29/30,
# China 23/24. Brazil is CQ 11 only.
# ITU: those, plus Brazil 12/13/15.
# Same sources as rules/zones.py (CQ WAZ list, ITU zone map).
MULTI_CQ = frozenset({"K", "VE", "UA", "VK", "BY"})
MULTI_ITU = frozenset({"K", "VE", "UA", "VK", "BY", "PY"})

CONTINENTS = frozenset({"NA", "SA", "EU", "AF", "AS", "OC", "AN"})
CONTINENT_NAMES = {
    "NA": "North America",
    "SA": "South America",
    "EU": "Europe",
    "AF": "Africa",
    "AS": "Asia",
    "OC": "Oceania",
    "AN": "Antarctica",
}

_TOKEN = re.compile(
    r"^(?P<exact>=)?(?P<pre>[A-Z0-9]+)"
    r"(?:\((?P<paren>[^)]*)\))?"
    r"(?:\[(?P<bracket>[^\]]*)\])?$",
)
_SUFFIXES = frozenset({
    "P", "M", "MM", "AM", "QRP", "R", "LH", "A", "B", "T", "N", "S",
})


@dataclass(frozen=True)
class Hit:
    """One prefix match. ``cq`` / ``itu`` are None when the grid must decide."""

    name: str
    continent: str
    cq: int | None
    itu: int | None
    cq_from_grid: bool
    itu_from_grid: bool


@dataclass(frozen=True)
class Derived:
    """Continent and zones for one station. Uncertain means do not claim needed."""

    continent: str | None
    cq: int | None
    itu: int | None
    cq_uncertain: bool
    itu_uncertain: bool
    known: bool


@dataclass
class _Raw:
    text: str
    exact: bool
    cq: int | None
    itu: int | None
    cq_explicit: bool
    itu_explicit: bool


@dataclass
class _Ent:
    name: str
    continent: str
    cq: int
    itu: int
    primary: str
    prefs: list


def continent_name(code: str | None) -> str:
    if not code:
        return ""
    return CONTINENT_NAMES.get(code, code)


def norm_zone(value, limit: int) -> int | None:
    """ADIF zone number, or None when the field is empty or out of range."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    number = int(text)
    if number < 1 or number > limit:
        return None
    return number


def norm_cont(value) -> str | None:
    text = str(value or "").strip().upper()
    if text in CONTINENTS:
        return text
    return None


def match_text(call: str | None) -> str:
    """Call body used for prefix match. A leading DX prefix wins over the home call."""
    raw = (call or "").upper().replace("<", "").replace(">", "").strip()
    if not raw:
        return ""
    if "/" not in raw:
        return raw
    parts = [p for p in raw.split("/") if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    left, right = parts[0], parts[1]
    if right in _SUFFIXES or (len(right) == 1 and right.isdigit()):
        return left
    if len(left) <= len(right) and len(left) <= 4:
        return left
    if len(right) <= 4 and len(right) < len(left):
        return right
    return left


def _parse_token(token: str) -> _Raw | None:
    text = token.strip().upper()
    if not text or text == ";":
        return None
    found = _TOKEN.match(text)
    if not found:
        return None
    pre = found.group("pre")
    if not pre:
        return None
    cq = None
    itu = None
    cq_explicit = False
    itu_explicit = False
    paren = (found.group("paren") or "").strip()
    if paren.isdigit():
        cq = int(paren)
        cq_explicit = True
    bracket = (found.group("bracket") or "").strip()
    if bracket.isdigit():
        itu = int(bracket)
        itu_explicit = True
    return _Raw(pre, bool(found.group("exact")), cq, itu, cq_explicit, itu_explicit)


def _parse_primary(line: str) -> _Ent | None:
    parts = [p.strip() for p in line.split(":")]
    if len(parts) < 4:
        return None
    name = parts[0].strip()
    if not name:
        return None
    try:
        cq = int(parts[1])
        itu = int(parts[2])
    except ValueError:
        return None
    cont = parts[3].strip().upper()
    if cont not in CONTINENTS:
        return None
    primary = parts[7].strip().upper() if len(parts) >= 8 else ""
    return _Ent(name, cont, cq, itu, primary, [])


class CtyIndex:
    """Longest-prefix country index. Empty until ``parse`` fills it."""

    def __init__(self) -> None:
        self.by_prefix: dict[str, Hit] = {}
        self.exact: dict[str, Hit] = {}
        self.entities = 0

    @classmethod
    def parse(cls, text: str) -> "CtyIndex":
        index = cls()
        current: _Ent | None = None
        alias: list[str] = []

        def finish_alias() -> None:
            if current is None or not alias:
                alias.clear()
                return
            blob = " ".join(alias)
            alias.clear()
            if ";" in blob:
                blob = blob.split(";", 1)[0]
            else:
                return
            for token in blob.split(","):
                raw = _parse_token(token)
                if raw:
                    current.prefs.append(raw)

        def finish_entity() -> None:
            finish_alias()
            if current is not None:
                index._add(current)

        for line in text.splitlines():
            if not line.strip():
                continue
            if line[0] in " \t":
                alias.append(line.strip())
                if ";" in line:
                    finish_alias()
                continue
            finish_entity()
            current = _parse_primary(line)
        finish_entity()
        return index

    @classmethod
    def load(cls, path: str | Path) -> "CtyIndex":
        # Country names in the upstream file are not always UTF-8.
        text = Path(path).read_text(encoding="latin-1", errors="replace")
        return cls.parse(text)

    def _add(self, ent: _Ent) -> None:
        cq_vals = {ent.cq}
        itu_vals = {ent.itu}
        for pref in ent.prefs:
            if pref.cq_explicit and pref.cq is not None:
                cq_vals.add(pref.cq)
            if pref.itu_explicit and pref.itu is not None:
                itu_vals.add(pref.itu)
        multi_cq = len(cq_vals) > 1 or ent.primary in MULTI_CQ
        multi_itu = len(itu_vals) > 1 or ent.primary in MULTI_ITU
        seen = {pref.text for pref in ent.prefs if not pref.exact}
        if ent.primary and ent.primary not in seen:
            ent.prefs.append(_Raw(ent.primary, False, None, None, False, False))
        for pref in ent.prefs:
            if pref.cq_explicit and pref.cq is not None:
                cq, cq_grid = pref.cq, False
            elif multi_cq:
                cq, cq_grid = None, True
            else:
                cq, cq_grid = ent.cq, False
            if pref.itu_explicit and pref.itu is not None:
                itu, itu_grid = pref.itu, False
            elif multi_itu:
                itu, itu_grid = None, True
            else:
                itu, itu_grid = ent.itu, False
            hit = Hit(ent.name, ent.continent, cq, itu, cq_grid, itu_grid)
            if pref.exact:
                self.exact[pref.text] = hit
            else:
                self.by_prefix[pref.text] = hit
        self.entities += 1

    def lookup(self, call: str | None) -> Hit | None:
        key = match_text(call)
        if not key:
            return None
        exact = self.exact.get(key)
        if exact is not None:
            return exact
        for length in range(len(key), 0, -1):
            hit = self.by_prefix.get(key[:length])
            if hit is not None:
                return hit
        return None

    def entity_name(self, call: str | None) -> str | None:
        """Name for the DXCC checklist. None when this call is not in the file."""
        hit = self.lookup(call)
        if hit is None:
            return None
        return hit.name

    def describe(
        self,
        call: str | None,
        grid: str | None = None,
        *,
        cqz=None,
        ituz=None,
        cont=None,
    ) -> Derived:
        """ADIF CQZ / ITUZ / CONT win. Otherwise the country file, then the grid."""
        hit = self.lookup(call)
        continent = norm_cont(cont)
        if continent is None and hit is not None:
            continent = hit.continent or None
        cq = norm_zone(cqz, 40)
        itu = norm_zone(ituz, 90)
        cq_field = cq is not None
        itu_field = itu is not None
        cq_uncertain = False
        itu_uncertain = False
        if not cq_field:
            if hit is None:
                cq = None
            elif hit.cq_from_grid:
                cq = cq_zone_from_grid(grid)
                cq_uncertain = cq is None
            else:
                cq = hit.cq
        if not itu_field:
            if hit is None:
                itu = None
            elif hit.itu_from_grid:
                itu = itu_zone_from_grid(grid)
                itu_uncertain = itu is None
            else:
                itu = hit.itu
        known = hit is not None or continent is not None or cq_field or itu_field
        return Derived(continent, cq, itu, cq_uncertain, itu_uncertain, known)


def find_cty_dat(roots: list[str | Path] | None = None) -> Path | None:
    """The first readable ``cty.dat``.

    ``roots`` limits the search (tests). With no argument, WIMS looks in each
    WSJT-X data directory and beside a normal install. It does not download
    a file and it does not write one.
    """
    if roots is not None:
        for raw in roots:
            path = Path(raw)
            if path.is_file() and path.name.lower() == "cty.dat":
                return path
            if path.is_dir():
                cand = path / "cty.dat"
                if cand.is_file():
                    return cand
        return None
    candidates: list[Path] = []
    try:
        from wims.integrations.wsjtx_logs import config_home, data_home, installed_dirs
        for folder in installed_dirs():
            candidates.append(folder / "cty.dat")
        candidates.append(data_home() / "WSJT-X" / "cty.dat")
        candidates.append(config_home() / "cty.dat")
    except Exception:
        pass
    for fixed in (
        "/usr/share/wsjtx/cty.dat",
        "/usr/local/share/wsjtx/cty.dat",
        "/usr/share/wsjt/cty.dat",
    ):
        candidates.append(Path(fixed))
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = (os.environ.get(env) or "").strip()
        if not base:
            continue
        root = Path(base)
        candidates.append(root / "WSJT-X" / "cty.dat")
        candidates.append(root / "wsjtx" / "bin" / "cty.dat")
    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None
