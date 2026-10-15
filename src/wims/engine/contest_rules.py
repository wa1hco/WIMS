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

"""Contest rules: one JSON file per contest, plus the WSJT-X Colors fallback.

Rules decide dupe, multiplier, and QSO points. Rank weights stay in
``scoring.py``. Files under ``wims/rules/`` are original GPL-3.0 summaries
that cite the sponsor's rules page. This module does not write logs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from wims.engine.scoring import band_points

_RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

# Colors-tab order for the six categories this needed-rule uses.
COLOR_ORDER = (
    "new_dxcc",
    "new_dxcc_band",
    "new_grid",
    "new_grid_band",
    "new_call",
    "new_call_band",
)

COLOR_LABELS = {
    "new_dxcc": "New DXCC",
    "new_dxcc_band": "New DXCC on Band",
    "new_grid": "New Grid",
    "new_grid_band": "New Grid on Band",
    "new_call": "New Call",
    "new_call_band": "New Call on Band",
}

# WSJT-X DecodeHighlightingModel factory defaults (DXCC on, the rest off).
FACTORY_CATEGORIES = {
    "new_dxcc": True,
    "new_dxcc_band": True,
    "new_grid": False,
    "new_grid_band": False,
    "new_call": False,
    "new_call_band": False,
}

_GROUP_WORD = {"PH": "phone", "CW": "CW", "DIG": "digital"}


@dataclass
class Verdict:
    is_dupe: bool
    is_new_mult: bool
    need_reason: str = ""
    mult_reason: str = ""
    points: int = 0


def _upper(value) -> str:
    return (value or "").strip().upper()


def load_file(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(f"rules file {path} needs an id")
    return data


def shipped_paths() -> list[Path]:
    return sorted(_RULES_DIR.glob("*.json"))


def iter_shipped() -> list["FileRules"]:
    out = []
    for path in shipped_paths():
        out.append(FileRules(load_file(path)))
    return out


def load_builtin(rule_id: str) -> "FileRules":
    want = (rule_id or "").strip()
    for rules in iter_shipped():
        if rules.id == want:
            return rules
    raise KeyError(want)


def catalog() -> list[dict]:
    """Dropdown rows: id, title, summary. Custom is added by the caller."""
    rows = []
    for rules in iter_shipped():
        rows.append({
            "id": rules.id,
            "title": rules.title,
            "summary": rules.plain_summary(),
        })
    rows.sort(key=lambda r: r["title"].lower())
    return rows


class FileRules:
    """One contest file. NYQP and ARRL VHF share this engine."""

    def __init__(self, data: dict):
        self.data = data
        self.id = str(data.get("id") or "custom")
        self.title = str(data.get("title") or self.id)
        self.summary = str(data.get("summary") or "")

    def mode_group(self, mode: str | None) -> str:
        token = _upper(mode)
        groups = self.data.get("mode_groups") or {}
        for name, modes in groups.items():
            if token and token in {_upper(m) for m in (modes or [])}:
                return str(name)
        if token in {"SSB", "USB", "LSB", "FM", "AM", "PHONE", "PH"}:
            return "PH"
        if token == "CW":
            return "CW"
        return "DIG"

    def excluded_name(self, mode: str | None, submode: str | None = None) -> str | None:
        ident = _upper(submode) or _upper(mode)
        mode_u = _upper(mode)
        sub_u = _upper(submode)
        for item in self.data.get("excluded_modes") or []:
            if not isinstance(item, dict):
                continue
            em = _upper(item.get("mode"))
            es = _upper(item.get("submode"))
            if es and (sub_u == es or ident == es):
                return es
            if em and not es and (ident == em or mode_u == em or sub_u == em):
                return em
        return None

    def _row_mode(self, row: dict) -> str:
        return _upper(row.get("submode")) or _upper(row.get("mode"))

    def _county_skips(self, row: dict, current_county: str | None) -> bool:
        if (self.data.get("dupe_reset") or "") != "my_county":
            return False
        logged = _upper(row.get("my_county"))
        cur = _upper(current_county)
        return bool(logged and cur and logged != cur)

    def _matches(self, row: dict, call: str, band: str, mode: str | None,
                 grid: str | None, current_county: str | None) -> bool:
        if _upper(row.get("call")) != _upper(call):
            return False
        if self.excluded_name(self._row_mode(row)):
            return False
        if self._county_skips(row, current_county):
            return False
        scope = self.data.get("dupe_scope") or "band"
        if scope == "all":
            return True
        if (row.get("band") or "") != (band or ""):
            return False
        if scope == "band+group":
            return self.mode_group(mode) == self.mode_group(self._row_mode(row))
        if self.data.get("rover_grid") and "/R" in _upper(call):
            if not grid:
                return True
            return _upper(row.get("grid")) == _upper(grid)
        return True

    def qso_points(self, band: str, mode: str | None) -> tuple[int, str]:
        banned = self.excluded_name(mode)
        if banned:
            return 0, f"{banned} is not counted in {self.title}."
        pts = self.data.get("points")
        if pts == "vhf-band":
            n = band_points(band)
            return n, f"{band}={n}pt"
        if isinstance(pts, dict):
            group = self.mode_group(mode)
            n = int(pts.get(group) or 0)
            return n, f"{_GROUP_WORD.get(group, group)} = {n}"
        return 0, ""

    def _new_mult(self, store, band: str, grid: str | None,
                  exchange: str | None) -> tuple[bool, str]:
        mults = [m for m in (self.data.get("multipliers") or []) if isinstance(m, dict)]
        if any(m.get("per") == "unverified" for m in mults):
            return False, (
                "Multiplier scope is not confirmed yet, so WIMS is not marking new multipliers."
            )
        for mult in mults:
            if mult.get("type") == "grid" and mult.get("per") == "band":
                if not grid:
                    return False, "No grid, so this is not a grid multiplier."
                want = _upper(grid)
                for row in store.cached_rows():
                    if (row.get("band") or "") == band and _upper(row.get("grid")) == want:
                        return False, f"Grid {want} is already worked on {band}."
                return True, f"New mult: grid {want} on {band}."
        if exchange:
            return False, "This rules file has no multiplier WIMS can mark yet."
        return False, ""

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None) -> Verdict:
        points, _why = self.qso_points(band, mode)
        banned = self.excluded_name(mode)
        new_mult, mult_reason = self._new_mult(store, band, grid, exchange)
        if banned:
            return Verdict(
                is_dupe=True,
                is_new_mult=False,
                need_reason=f"{banned} is not counted in {self.title}.",
                mult_reason="",
                points=0,
            )
        worked = False
        if call:
            for row in store.cached_rows():
                if self._matches(row, call, band, mode, grid, my_county):
                    worked = True
                    break
        if worked:
            group = _GROUP_WORD.get(self.mode_group(mode), "")
            where = f"{band} {group}".strip()
            return Verdict(
                is_dupe=True,
                is_new_mult=bool(new_mult),
                need_reason=f"Already worked: {call} on {where}.",
                mult_reason=mult_reason if new_mult else "",
                points=points,
            )
        group = _GROUP_WORD.get(self.mode_group(mode), "")
        if (self.data.get("dupe_scope") or "") == "band+group" and group:
            need = f"Needed: {call} is not in the log on {band} {group}."
        elif call:
            need = f"Needed: {call} is not in the log on {band}."
        else:
            need = ""
        return Verdict(
            is_dupe=False,
            is_new_mult=bool(new_mult),
            need_reason=need,
            mult_reason=mult_reason if new_mult else "",
            points=points,
        )

    def plain_summary(self) -> str:
        parts = [self.summary.strip()] if self.summary.strip() else []
        banned = []
        for item in self.data.get("excluded_modes") or []:
            if isinstance(item, dict):
                name = item.get("submode") or item.get("mode")
                if name:
                    banned.append(str(name))
        if banned:
            clause = (
                f"{' and '.join(banned)} "
                f"{'is' if len(banned) == 1 else 'are'} not counted."
            )
            if clause not in " ".join(parts):
                parts.append(clause)
        if any(
            isinstance(m, dict) and m.get("per") == "unverified"
            for m in (self.data.get("multipliers") or [])
        ):
            parts.append(
                "New multipliers stay off until the rules page confirms how they count."
            )
        return " ".join(p for p in parts if p).strip()

    def public(self, *, source_label: str, n1mm: bool, extra: dict | None = None) -> dict:
        out = {
            "id": self.id,
            "title": self.title,
            "source_label": source_label,
            "n1mm_authoritative": bool(n1mm),
            "summary": self.plain_summary(),
            "rules_url": self.data.get("rules_url") or "",
            "rules_version": self.data.get("rules_version") or "",
            "catalog": catalog(),
        }
        if extra:
            out.update(extra)
        return out


def default_color_categories(*, cty_ok: bool) -> tuple[dict, str]:
    """Categories until the DecodeHighlighting blob can be parsed.

    Factory defaults (New DXCC and New DXCC on Band) apply when ``cty.dat``
    can name an entity. Without it those two categories cannot match, so the
    four call/grid categories start on and Setup says why.
    """
    if cty_ok:
        return dict(FACTORY_CATEGORIES), (
            "WIMS could not read the Colors list from WSJT-X.ini. "
            "Showing WSJT-X’s default categories. You can edit them here."
        )
    cats = {key: False for key in COLOR_ORDER}
    for key in ("new_grid", "new_grid_band", "new_call", "new_call_band"):
        cats[key] = True
    return cats, (
        "WIMS could not read the Colors list from WSJT-X.ini, and cty.dat was not found, "
        "so DXCC highlighting is off. Showing New Call, New Call on Band, New Grid, "
        "and New Grid on Band. You can edit them here."
    )


def _grid_key(grid: str | None, fields_only: bool) -> str | None:
    g = _upper(grid)
    if not g:
        return None
    if fields_only:
        return g[:2]
    return g[:4] if len(g) >= 4 else g


def _entity(call: str, dxcc: str | None, lookup) -> str | None:
    num = (dxcc or "").strip()
    if num:
        return f"dxcc:{num}"
    if lookup is None or not call:
        return None
    try:
        name = lookup(call)
    except Exception:
        return None
    if not name:
        return None
    return f"name:{name}"


class WsjtxColors:
    """Needed when any enabled Colors category misses the ADIF log."""

    id = "wsjtx-colors"
    title = "WSJT-X Colors"

    def __init__(
        self,
        *,
        categories: dict | None = None,
        highlight_by_mode: bool = False,
        only_fields_sought: bool = False,
        log_label: str = "wsjtx_log.adi",
        dxcc_lookup=None,
        note: str = "",
        source_label: str = "WSJT-X Colors",
    ):
        base = {key: False for key in COLOR_ORDER}
        for key, val in (categories or {}).items():
            if key in base:
                base[key] = bool(val)
        self.categories = base
        self.highlight_by_mode = bool(highlight_by_mode)
        self.only_fields_sought = bool(only_fields_sought)
        self.log_label = log_label or "wsjtx_log.adi"
        self.dxcc_lookup = dxcc_lookup
        self.note = note
        self.source_label = source_label

    def plain_summary(self) -> str:
        enabled = [COLOR_LABELS[k] for k in COLOR_ORDER if self.categories.get(k)]
        if not enabled:
            line = "No color category is enabled, so no CQ will show as needed."
        else:
            line = "Needed when a CQ matches " + ", ".join(enabled) + "."
        if self.highlight_by_mode:
            line += " Worked-before is per mode."
        if self.only_fields_sought:
            line += " Grid compare uses the field (first two characters)."
        if self.note:
            line += " " + self.note
        return line

    def _worked_index(self, store) -> dict:
        gen = store.generation()
        cache = getattr(self, "_worked_cache", None)
        if cache and cache[0] == gen and cache[1] is store:
            return cache[2]
        calls: set = set()
        calls_band: set = set()
        calls_mode: set = set()
        calls_band_mode: set = set()
        grids: set = set()
        grids_band: set = set()
        dxcc: set = set()
        dxcc_band: set = set()
        for row in store.cached_rows():
            call = _upper(row.get("call"))
            if not call:
                continue
            band = row.get("band") or ""
            mode = _upper(row.get("submode")) or _upper(row.get("mode"))
            if self.highlight_by_mode:
                if mode:
                    calls_mode.add((call, mode))
                    if band:
                        calls_band_mode.add((call, band, mode))
            else:
                calls.add(call)
                if band:
                    calls_band.add((call, band))
            g = _grid_key(row.get("grid"), self.only_fields_sought)
            if g:
                grids.add(g)
                if band:
                    grids_band.add((g, band))
            ent = _entity(call, row.get("dxcc"), self.dxcc_lookup)
            if ent:
                dxcc.add(ent)
                if band:
                    dxcc_band.add((ent, band))
        built = {
            "calls": calls,
            "calls_band": calls_band,
            "calls_mode": calls_mode,
            "calls_band_mode": calls_band_mode,
            "grids": grids,
            "grids_band": grids_band,
            "dxcc": dxcc,
            "dxcc_band": dxcc_band,
        }
        self._worked_cache = (gen, store, built)
        return built

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None) -> Verdict:
        del exchange, my_county
        call_u = _upper(call)
        mode_u = _upper(mode)
        idx = self._worked_index(store)
        if not any(self.categories.values()):
            return Verdict(
                True, False,
                need_reason="No color category is enabled, so no CQ will show as needed.",
                points=1,
            )
        ent = _entity(call_u, None, self.dxcc_lookup)
        g = _grid_key(grid, self.only_fields_sought)
        hits: list[tuple[str, str]] = []

        def _mode_ok() -> bool:
            return (not self.highlight_by_mode) or bool(mode_u)

        if self.categories["new_dxcc"] and ent and ent not in idx["dxcc"]:
            hits.append(("new_dxcc", f"Needed: New DXCC — {call_u} is not in {self.log_label}."))
        if self.categories["new_dxcc_band"] and ent and (ent, band) not in idx["dxcc_band"]:
            hits.append((
                "new_dxcc_band",
                f"Needed: New DXCC on Band — {call_u} on {band} is not in {self.log_label}.",
            ))
        if self.categories["new_grid"] and g and g not in idx["grids"]:
            hits.append((
                "new_grid",
                f"Needed: New Grid — {g} is not in {self.log_label}.",
            ))
        if self.categories["new_grid_band"] and g and (g, band) not in idx["grids_band"]:
            hits.append((
                "new_grid_band",
                f"Needed: New Grid on Band — {g} on {band} is not in {self.log_label}.",
            ))
        if self.categories["new_call"] and call_u and _mode_ok():
            worked = (
                (call_u, mode_u) in idx["calls_mode"]
                if self.highlight_by_mode else call_u in idx["calls"]
            )
            if not worked:
                hits.append((
                    "new_call",
                    f"Needed: New Call — {call_u} is not in {self.log_label}.",
                ))
        if self.categories["new_call_band"] and call_u and band and _mode_ok():
            worked = (
                (call_u, band, mode_u) in idx["calls_band_mode"]
                if self.highlight_by_mode else (call_u, band) in idx["calls_band"]
            )
            if not worked:
                hits.append((
                    "new_call_band",
                    f"Needed: New Call on Band — {call_u} on {band} is not in {self.log_label}.",
                ))
        if hits:
            key, reason = hits[0]
            mult = key in {"new_dxcc", "new_dxcc_band", "new_grid", "new_grid_band"}
            mult_reason = ""
            if key == "new_grid":
                mult_reason = f"New mult: grid {g}."
            elif key == "new_grid_band":
                mult_reason = f"New mult: grid {g} on {band}."
            elif key in {"new_dxcc", "new_dxcc_band"}:
                mult_reason = f"New mult: {COLOR_LABELS[key]}."
            return Verdict(False, mult, need_reason=reason, mult_reason=mult_reason, points=1)
        shown_mode = f" {mode_u}" if mode_u else ""
        return Verdict(
            True,
            False,
            need_reason=(
                f"Not needed: {call_u} on {band}{shown_mode} matches no enabled WSJT-X color."
            ),
            points=1,
        )

    def public(self, *, source_label: str | None = None, n1mm: bool = False,
               extra: dict | None = None) -> dict:
        out = {
            "id": self.id,
            "title": self.title,
            "source_label": source_label or self.source_label,
            "n1mm_authoritative": bool(n1mm),
            "summary": self.plain_summary(),
            "rules_url": "",
            "rules_version": "",
            "catalog": catalog(),
            "colors": {
                "categories": dict(self.categories),
                "labels": dict(COLOR_LABELS),
                "highlight_by_mode": self.highlight_by_mode,
                "only_fields_sought": self.only_fields_sought,
                "note": self.note,
            },
        }
        if extra:
            out.update(extra)
        return out


def read_colors_ini(path: str | Path | None) -> dict:
    """Plain bools from WSJT-X.ini. The DecodeHighlighting blob is not parsed."""
    out = {
        "found": False,
        "path": str(path or ""),
        "highlight_by_mode": None,
        "only_fields_sought": None,
        "include_wae": None,
    }
    if not path:
        return out
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    out["found"] = True
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("[") or raw.startswith("#") or raw.startswith(";"):
            continue
        if "=" not in raw:
            continue
        key, val = raw.split("=", 1)
        flag = val.strip().lower() in {"true", "1", "yes"}
        name = key.strip()
        if name == "HighlightByMode":
            out["highlight_by_mode"] = flag
        elif name == "OnlyFieldsSought":
            out["only_fields_sought"] = flag
        elif name == "IncludeWAEEntities":
            out["include_wae"] = flag
    return out


def suggest_contest(names: list[str], today: date | None = None) -> tuple[str | None, str]:
    """Return ``(rules id, "log"|"date"|"")``. Empty season never matches a date."""
    tokens = [_upper(n) for n in names if _upper(n)]
    shipped = iter_shipped()
    for rules in shipped:
        aliases = [_upper(a) for a in (rules.data.get("aliases") or []) if _upper(a)]
        for token in tokens:
            for alias in aliases:
                if token == alias:
                    return rules.id, "log"
                if len(alias) >= 4 and alias in token:
                    return rules.id, "log"
                if len(token) >= 4 and token in alias:
                    return rules.id, "log"
    day = today or date.today()
    iso = day.isoformat()
    for rules in shipped:
        season = rules.data.get("season") or {}
        start = str(season.get("start") or "").strip()
        end = str(season.get("end") or "").strip()
        if start and end and start <= iso <= end:
            return rules.id, "date"
    return None, ""


def import_udc(text: str) -> dict:
    """Read a local N1MM ``.udc`` the operator already has. Does not write it.

    Recognizes a name, a dupe phrase, points lines, and multiplier names.
    Every other key is listed under ``unparsed``.
    """
    title = ""
    dupe_scope = ""
    points: dict[str, int] = {}
    mults: list[str] = []
    unparsed: list[str] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith(";") or raw.startswith("#") or raw.startswith("["):
            continue
        if "=" not in raw:
            unparsed.append(raw)
            continue
        key, val = raw.split("=", 1)
        name = key.strip()
        value = val.strip()
        low = name.lower().replace(" ", "")
        if low in {"name", "title", "contestname"}:
            title = value
        elif "dupe" in low:
            blob = value.lower()
            if "mode" in blob:
                dupe_scope = "band+group"
            elif "band" in blob:
                dupe_scope = "band"
            elif blob in {"all", "once", "no"}:
                dupe_scope = "all"
            else:
                unparsed.append(name)
        elif low.startswith("points"):
            try:
                points[name] = int(float(value))
            except ValueError:
                unparsed.append(name)
        elif "mult" in low and value:
            mults.append(value)
        else:
            unparsed.append(name)
    return {
        "title": title or "Custom rules",
        "dupe_scope": dupe_scope,
        "points": points,
        "multipliers": mults,
        "unparsed": unparsed,
    }


def custom_from_checkboxes(body: dict) -> dict:
    """Advanced checkbox set → one rules file (same schema as the shipped files)."""
    scope = body.get("dupe_scope") or "band"
    if scope not in {"band", "band+group", "all"}:
        scope = "band"
    excluded = []
    if body.get("ban_ft8"):
        excluded.append({"mode": "FT8"})
    if body.get("ban_ft4"):
        excluded.append({"mode": "FT4"})
    reset = "my_county" if body.get("dupe_reset_county") else ""
    points = body.get("points") if isinstance(body.get("points"), dict) else {
        "PH": 1, "CW": 2, "DIG": 3,
    }
    return {
        "id": "custom",
        "title": "Custom rules",
        "license": "GPL-3.0-or-later",
        "rules_url": "",
        "rules_version": "",
        "rules_date": "",
        "year": date.today().year,
        "season": {"start": "", "end": ""},
        "aliases": [],
        "mode_groups": {
            "PH": ["SSB", "USB", "LSB", "FM", "AM"],
            "CW": ["CW"],
            "DIG": ["RTTY"],
        },
        "excluded_modes": excluded,
        "dupe_scope": scope,
        "rover_grid": bool(body.get("rover_grid")),
        "dupe_reset": reset,
        "points": points,
        "multipliers": [],
        "summary": "Custom rules from Setup → Advanced.",
    }


@dataclass
class Resolved:
    rules: object
    public: dict
    contest: str | None
    suggested: bool = False
    suggested_from: str = ""
    choice: dict = field(default_factory=dict)


def resolve(
    choice: dict,
    *,
    n1mm: bool,
    contest_names: list[str] | None = None,
    today: date | None = None,
    ini_path: str | Path | None = None,
    cty_ok: bool = False,
    dxcc_lookup=None,
    custom_data: dict | None = None,
    log_label: str = "wsjtx_log.adi",
) -> Resolved:
    """Pick the active rule. Does not override an explicit dropdown choice."""
    choice = dict(choice or {})
    explicit = bool(choice.get("explicit"))
    contest = choice.get("contest") or None
    if contest == "":
        contest = None
    suggested = bool(choice.get("suggested"))
    suggested_from = ""
    if not explicit and not contest:
        sid, how = suggest_contest(contest_names or [], today)
        if sid:
            contest = sid
            suggested = True
            suggested_from = how
    rules_obj: object
    label: str
    note = ""
    if contest and contest != "custom":
        try:
            rules_obj = load_builtin(str(contest))
        except KeyError:
            rules_obj = load_builtin("arrl-vhf")
            contest = "arrl-vhf"
        label = rules_obj.title
        if n1mm and not suggested:
            label = rules_obj.title
    elif contest == "custom" and custom_data:
        rules_obj = FileRules(custom_data)
        label = "Custom rules"
    elif n1mm:
        rules_obj = load_builtin("arrl-vhf")
        contest = None
        label = "N1MM · ARRL VHF"
        suggested = False
    else:
        rules_obj, label, note = _colors_from_choice(
            choice, ini_path=ini_path, cty_ok=cty_ok,
            dxcc_lookup=dxcc_lookup, log_label=log_label,
        )
        contest = None
    if n1mm and contest:
        # Named contest under N1MM keeps the contest title. The sentence adds the log line.
        pass
    extra = {
        "choice": {
            "contest": contest,
            "explicit": explicit,
            "suggested": suggested and not explicit,
            "fallback": choice.get("fallback") or "wsjtx-colors",
            "station_state": choice.get("station_state") or "",
            "station_county": choice.get("station_county") or "",
        },
        "custom_available": bool(custom_data),
        "colors_note": note,
    }
    if suggested and not explicit and suggested_from:
        if suggested_from == "date":
            extra["suggested_note"] = (
                f"Suggested from the date: {rules_obj.title}. "
                "Set Contest to None if that is wrong."
            )
        elif suggested_from == "log":
            extra["suggested_note"] = (
                f"Suggested from the log: {rules_obj.title}. "
                "Set Contest to None if that is wrong."
            )
    if n1mm:
        extra["n1mm_line"] = (
            f"N1MM is the log of record, so needed uses {getattr(rules_obj, 'title', label)}. "
            "The WSJT-X / GridTracker fallback is not used."
        )
    public = rules_obj.public(source_label=label, n1mm=n1mm, extra=extra)
    if getattr(rules_obj, "id", "") == "nyqp" and not (choice.get("station_state") or "").strip():
        public["summary"] = (
            public["summary"].rstrip()
            + " WIMS does not know if this station is in NY, so only NY counties would count."
        )
    if suggested and not explicit and contest:
        public["source_label"] = rules_obj.title
    return Resolved(
        rules=rules_obj,
        public=public,
        contest=contest,
        suggested=bool(suggested and not explicit),
        suggested_from=suggested_from,
        choice=choice,
    )


def _colors_from_choice(choice, *, ini_path, cty_ok, dxcc_lookup, log_label):
    ini = read_colors_ini(ini_path)
    override = choice.get("wsjtx_override")
    if isinstance(override, dict) and isinstance(override.get("categories"), dict):
        cats = override["categories"]
        note = ""
        label = "WSJT-X Colors · edited in WIMS"
        highlight = bool(override.get("highlight_by_mode"))
        fields = bool(override.get("only_fields_sought"))
    else:
        cats, note = default_color_categories(cty_ok=cty_ok)
        highlight = bool(ini["highlight_by_mode"]) if ini["highlight_by_mode"] is not None else False
        fields = bool(ini["only_fields_sought"]) if ini["only_fields_sought"] is not None else False
        if ini["found"]:
            name = Path(ini["path"]).name or "WSJT-X.ini"
            label = f"WSJT-X Colors · {name}"
        else:
            label = "WSJT-X Colors"
    if (choice.get("fallback") or "wsjtx-colors") == "gridtracker":
        note = (
            (note + " " if note else "")
            + "GridTracker settings are not readable. Needed is using WSJT-X Colors until this file opens."
        ).strip()
    rules = WsjtxColors(
        categories=cats,
        highlight_by_mode=highlight,
        only_fields_sought=fields,
        log_label=log_label,
        dxcc_lookup=dxcc_lookup,
        note=note,
        source_label=label,
    )
    return rules, label, note
