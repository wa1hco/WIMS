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

"""Contest rules: one JSON file per contest.

Just operating uses the checklist in ``goal_rules``. Rules decide dupe,
multiplier, and QSO points. Rank weights stay in ``scoring.py``. Files under
``wims/rules/`` are original GPL-3.0 summaries that cite the sponsor's rules
page. This module does not write logs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from wims.engine.scoring import band_points

_RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

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


def _grid4(grid: str | None) -> str | None:
    """Four-character Maidenhead square. A subsquare is the same square."""
    g = _upper(grid)
    if len(g) >= 4 and g[0].isalpha() and g[1].isalpha() and g[2].isdigit() and g[3].isdigit():
        return g[:4]
    return None


def _log_name(store) -> str:
    return (getattr(store, "log_label", "") or "").strip() or "the log"


def _blank_grid_note(store, call: str, band: str, log_name: str) -> str:
    """The log has this call on this band, and that line has no square."""
    call_u = _upper(call)
    if not call_u:
        return ""
    for row in store.cached_rows():
        if _upper(row.get("call")) != call_u:
            continue
        if (row.get("band") or "") != (band or ""):
            continue
        if not _grid4(row.get("grid")):
            return f" {call_u} is in {log_name} on {band} with no grid."
    return ""


def _window_clause(store) -> str:
    """Plain reminder when count-since / count-until hides older contacts."""
    since = getattr(store, "count_since", "") or ""
    until = getattr(store, "count_until", "") or ""
    if not since and not until:
        return ""
    from wims.rules.log_use import pretty_time
    bits = []
    if since:
        bits.append("since " + pretty_time(since))
    if until:
        bits.append("through " + pretty_time(until))
    return " Counting contacts " + " ".join(bits) + "."


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
            logged = _grid4(row.get("grid")) or _upper(row.get("grid"))
            want = _grid4(grid) or _upper(grid)
            if not want:
                return True
            return logged == want
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
                want = _grid4(grid)
                name = _log_name(store)
                if not want:
                    return False, "No grid, so this is not a grid multiplier."
                for row in store.cached_rows():
                    if (row.get("band") or "") == band and _grid4(row.get("grid")) == want:
                        return False, f"Grid {want} is already worked on {band} in {name}."
                return True, (
                    f"Mult: grid {want} not yet worked on {band} in {name}."
                    + _window_clause(store)
                )
        if exchange:
            return False, "This rules file has no multiplier WIMS can mark yet."
        return False, ""

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None,
                 state: str | None = None) -> Verdict:
        del state
        points, _why = self.qso_points(band, mode)
        banned = self.excluded_name(mode)
        new_mult, mult_reason = self._new_mult(store, band, grid, exchange)
        if new_mult and mult_reason:
            mult_reason += _blank_grid_note(store, call, band, _log_name(store))
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
            square = ""
            want = _grid4(grid)
            name = _log_name(store)
            if want:
                for row in store.cached_rows():
                    if (row.get("band") or "") == (band or "") and _grid4(row.get("grid")) == want:
                        square = f" Grid {want} on {band} is in {name}."
                        break
            return Verdict(
                is_dupe=True,
                is_new_mult=bool(new_mult),
                need_reason=f"Already worked: {call} on {where}.{square}",
                mult_reason=mult_reason if new_mult else "",
                points=points,
            )
        name = _log_name(store)
        group = _GROUP_WORD.get(self.mode_group(mode), "")
        if (self.data.get("dupe_scope") or "") == "band+group" and group:
            need = f"Needed: {call} is not in {name} on {band} {group}."
        elif call:
            need = f"Needed: {call} is not in {name} on {band}."
        else:
            need = ""
        note = self._suffix_note(store, call, band)
        if note:
            need = (need + " " + note).strip()
        need += _window_clause(store)
        return Verdict(
            is_dupe=False,
            is_new_mult=bool(new_mult),
            need_reason=need,
            mult_reason=mult_reason if new_mult else "",
            points=points,
        )

    def _suffix_note(self, store, call: str, band: str) -> str:
        """Say when the log has this station under a different suffix.

        ``K1ABC`` and ``K1ABC/P`` are different calls. ``/R`` is a rover and
        can be worked again in a new grid. The note names the logged call so
        the roster can say why this one is still needed.
        """
        from wims.engine.geo import base_call
        want = _upper(call)
        base = base_call(want)
        if len(base) < 3:
            return ""
        scope = self.data.get("dupe_scope") or "band"
        for row in store.cached_rows():
            other = _upper(row.get("call"))
            if not other or other == want or base_call(other) != base:
                continue
            if scope != "all" and (row.get("band") or "") != (band or ""):
                continue
            where = band or "this band"
            return (
                f"{other} is in the log on {where}. "
                f"{want} is a different call, so this one is still needed."
            )
        return ""

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
    dxcc_lookup=None,
    custom_data: dict | None = None,
    log_label: str = "wsjtx_log.adi",
    cty=None,
) -> Resolved:
    """Pick the active rule. Does not override an explicit goal choice.

    Just operating uses the checklist. The log named by Log to use is the
    only log these rules read. ``cty`` is the country file when it was found.
    """
    from wims.engine.goal_rules import (
        AwardRules,
        ChecklistRules,
        goal_menu,
        legacy_contest,
        sanitize_selection,
        shape_choice,
    )

    choice = shape_choice(dict(choice or {}))
    explicit = bool(choice.get("explicit"))
    goal, goal_id = sanitize_selection(
        choice.get("goal") or "operating",
        choice.get("goal_id") or "",
        custom_available=bool(custom_data),
    )
    suggested = bool(choice.get("suggested"))
    suggested_from = ""
    # Same window as the old empty Contest menu: just operating, not an explicit pick.
    if (
        not explicit
        and goal == "operating"
        and goal_id == "checklist"
    ):
        sid, how = suggest_contest(contest_names or [], today)
        if sid:
            goal, goal_id = "contest", sid
            suggested = True
            suggested_from = how
    rules_obj: object
    label: str
    contest: str | None = legacy_contest(goal, goal_id)
    lookup = dxcc_lookup
    if lookup is None and cty is not None:
        lookup = cty.entity_name
    if goal == "contest":
        try:
            rules_obj = load_builtin(str(goal_id))
        except KeyError:
            rules_obj = load_builtin("arrl-vhf")
            goal_id = "arrl-vhf"
            contest = "arrl-vhf"
        label = rules_obj.title
    elif goal == "award":
        rules_obj = AwardRules(
            goal_id, dxcc_lookup=lookup, log_label=log_label,
        )
        label = rules_obj.title
        contest = None
    elif goal == "custom" and goal_id == "custom-file" and custom_data:
        rules_obj = FileRules(custom_data)
        label = "Custom rules"
        contest = "custom"
    else:
        # Just operating, or a custom checklist. The selected log is unchanged.
        title = "Custom checklist" if goal == "custom" else "Checklist"
        rules_obj = ChecklistRules(
            choice.get("checklist"),
            title=title,
            dxcc_lookup=lookup,
            log_label=log_label,
            cty=cty,
        )
        label = rules_obj.title
        contest = None
    choice["goal"] = goal
    choice["goal_id"] = goal_id
    choice["contest"] = contest
    menu_choice = dict(choice)
    extra = {
        "choice": {
            "contest": contest,
            "goal": goal,
            "goal_id": goal_id,
            "explicit": explicit,
            "suggested": suggested and not explicit,
            "fallback": "",
            "station_state": choice.get("station_state") or "",
            "station_county": choice.get("station_county") or "",
        },
        "custom_available": bool(custom_data),
        "goal": goal_menu(
            menu_choice,
            custom_available=bool(custom_data),
            cty_ok=cty is not None,
        ),
    }
    if suggested and not explicit and suggested_from:
        wrong = "Choose Just operating (not a contest) if that is wrong."
        if suggested_from == "date":
            extra["suggested_note"] = (
                f"Suggested from the date: {rules_obj.title}. {wrong}"
            )
        elif suggested_from == "log":
            extra["suggested_note"] = (
                f"Suggested from the log: {rules_obj.title}. {wrong}"
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
