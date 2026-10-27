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

This is the call-to-entity resolver for the checklist and for the Country
column. The column calls it when this file is loaded, so the two cannot
name different entities. Shapes that are not prefixes (KG4 suffix length,
KC4 Antarctic bases, ``3Y0``, ``VP8/G``, ``SV/A``, ``CE0/X``, rover ``/R``)
live in ``rules/callsign.py`` and are applied here. An exact call (``=``)
wins over those rules. A primary prefix with a leading ``*`` is a WAE
entity: it still supplies a zone, and it is not a separate DXCC entity.
The survey is ``docs/plan/wims_call_entities.md``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from wims.rules.callsign import (
    island_key,
    kc4_antarctica,
    kg4_kind,
    location_body,
    normalize,
)
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

# Overrides that may follow a prefix, in any order. A parenthesized
# latitude/longitude is not a CQ zone. Angle brackets and tildes are
# position and time; they do not change the entity.
_OVERRIDE = re.compile(
    r"\((?P<paren>[^)]*)\)"
    r"|\[(?P<bracket>[^\]]*)\]"
    r"|\{(?P<cont>[^}]*)\}"
    r"|<[^>]*>"
    r"|~[^~]*~"
)
_PREFIX_TEXT = re.compile(r"^[A-Z0-9/]+$")


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
    cont: str | None = None


@dataclass
class _Ent:
    name: str
    continent: str
    cq: int
    itu: int
    primary: str
    prefs: list
    wae: bool = False


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
    """Call body used for a prefix match. Same rules as ``location_body``."""
    return location_body(call)


def _parse_token(token: str) -> _Raw | None:
    text = token.strip().upper().rstrip(";")
    if not text:
        return None
    exact = text.startswith("=")
    if exact:
        text = text[1:]
    cq = None
    itu = None
    cont = None
    cq_explicit = False
    itu_explicit = False

    def _take(found: re.Match) -> str:
        nonlocal cq, itu, cont, cq_explicit, itu_explicit
        paren = found.group("paren")
        if paren is not None:
            paren = paren.strip()
            if paren.isdigit() and not cq_explicit:
                cq = int(paren)
                cq_explicit = True
            return ""
        bracket = found.group("bracket")
        if bracket is not None:
            bracket = bracket.strip()
            if bracket.isdigit() and not itu_explicit:
                itu = int(bracket)
                itu_explicit = True
            return ""
        continent = found.group("cont")
        if continent is not None:
            continent = continent.strip().upper()
            if continent in CONTINENTS and cont is None:
                cont = continent
        return ""

    pre = _OVERRIDE.sub(_take, text).strip()
    if not pre or not _PREFIX_TEXT.fullmatch(pre):
        return None
    return _Raw(pre, exact, cq, itu, cq_explicit, itu_explicit, cont)


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
    wae = primary.startswith("*")
    if wae:
        primary = primary[1:].strip()
    if primary and not _PREFIX_TEXT.fullmatch(primary):
        primary = ""
    return _Ent(name, cont, cq, itu, primary, [], wae)


class CtyIndex:
    """Longest-prefix country index. Empty until ``parse`` fills it."""

    def __init__(self) -> None:
        self.by_prefix: dict[str, Hit] = {}
        self.exact: dict[str, Hit] = {}
        # DXCC maps omit WAE (``*``) entities. Zone lookup still uses them.
        self.dxcc_prefix: dict[str, Hit] = {}
        self.dxcc_exact: dict[str, Hit] = {}
        self._zone_slash: tuple[str, ...] = ()
        self._dxcc_slash: tuple[str, ...] = ()
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
        index._finish()
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
            continent = pref.cont or ent.continent
            hit = Hit(ent.name, continent, cq, itu, cq_grid, itu_grid)
            if ent.wae:
                if pref.exact:
                    self._put(self.exact, pref.text, hit)
                else:
                    self._put(self.by_prefix, pref.text, hit)
            else:
                if pref.exact:
                    self._put(self.exact, pref.text, hit)
                    self._put(self.dxcc_exact, pref.text, hit)
                else:
                    self._put(self.by_prefix, pref.text, hit)
                    self._put(self.dxcc_prefix, pref.text, hit)
        self.entities += 1

    @staticmethod
    def _put(mapping: dict, key: str, hit: Hit) -> None:
        """First entry wins. A later duplicate call in the file is ignored."""
        if key and key not in mapping:
            mapping[key] = hit

    def _finish(self) -> None:
        self._zone_slash = self._slash_keys(self.by_prefix)
        self._dxcc_slash = self._slash_keys(self.dxcc_prefix)

    @staticmethod
    def _slash_keys(prefixes: dict) -> tuple[str, ...]:
        keys = [key for key in prefixes if "/" in key]
        keys.sort(key=len, reverse=True)
        return tuple(keys)

    def lookup(self, call: str | None, *, dxcc: bool = False) -> Hit | None:
        """Entity for ``call``.

        ``dxcc=False`` is the zone record, including WAE entities such as
        Sicily. ``dxcc=True`` is the DXCC entity. An exact call wins. Then
        a slash prefix (``3Y/B``), then the structural keys in
        ``callsign.island_key``, then the longest ordinary prefix. KG4
        suffix length is applied last, and only when no exact call matched.
        """
        raw = normalize(call)
        if not raw:
            return None
        if not any(ch.isdigit() for ch in raw) and "/" not in raw:
            return None
        exact, prefixes, slash_keys = self._maps(dxcc)
        hit = exact.get(raw)
        if hit is not None:
            return hit
        hit = self._slash_hit(raw, slash_keys, prefixes)
        if hit is not None:
            return hit
        key = island_key(raw)
        if key:
            hit = prefixes.get(key)
            if hit is not None:
                return hit
        body = location_body(raw)
        if not body:
            return None
        hit = exact.get(body)
        if hit is not None:
            return hit
        if kc4_antarctica(body):
            antarctic = prefixes.get("CE9")
            if antarctic is not None and "ANTARCT" in antarctic.name.upper():
                return antarctic
        hit, matched = self._longest_prefix(body, prefixes)
        if hit is None:
            return None
        return self._kg4_hit(body, hit, matched, prefixes)

    def _maps(self, dxcc: bool):
        if dxcc:
            return self.dxcc_exact, self.dxcc_prefix, self._dxcc_slash
        return self.exact, self.by_prefix, self._zone_slash

    @staticmethod
    def _slash_hit(raw: str, keys: tuple[str, ...], prefixes: dict) -> Hit | None:
        if "/" not in raw:
            return None
        for key in keys:
            if raw == key or raw.startswith(key + "/"):
                return prefixes[key]
        return None

    @staticmethod
    def _longest_prefix(key: str, prefixes: dict) -> tuple[Hit | None, str]:
        for length in range(len(key), 0, -1):
            prefix = key[:length]
            hit = prefixes.get(prefix)
            if hit is not None:
                return hit, prefix
        return None, ""

    @staticmethod
    def _kg4_hit(key: str, hit: Hit, matched: str, prefixes: dict) -> Hit:
        """A three-letter KG4 suffix belongs to prefix ``K``, not ``KG4``.

        Longest-prefix match would call ``KG4LDK`` Guantanamo Bay, because
        ``KG4`` is longer than ``K``. That suffix is a United States call.
        ``KG4AA`` stays on the ``KG4`` entry. Exact calls are handled before
        this runs. A file that has no ``K`` entry is left unchanged, and a
        file that has no ``KG4`` entry does not invent Guantanamo Bay.
        """
        kind = kg4_kind(key)
        if kind == "us":
            if matched == "KG4":
                us = prefixes.get("K")
                if us is not None:
                    return us
            return hit
        if kind == "gtmo" and matched != "KG4" and len(matched) < len("KG4"):
            gtmo = prefixes.get("KG4")
            if gtmo is not None:
                return gtmo
        return hit

    def entity_name(self, call: str | None) -> str | None:
        """DXCC name. None when this call is not in the file.

        WAE entities are not returned. Sicily is Italy. The zone for that
        call still comes from ``describe``.
        """
        hit = self.lookup(call, dxcc=True)
        if hit is None:
            return None
        return hit.name or None

    def country_fields(self, call: str | None, grid: str | None = None) -> dict:
        """Country-column fields from this same resolver."""
        name = self.entity_name(call)
        if not name:
            return {"country": "", "continent": "", "cq_zone": None}
        zone = self.describe(call, grid)
        return {
            "country": name,
            "continent": zone.continent or "",
            "cq_zone": zone.cq,
        }

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
