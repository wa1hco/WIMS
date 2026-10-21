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

"""Goal selector: contest, award, just operating, or a custom checklist.

Just operating is the checklist. A saved WSJT-X Colors choice is converted
once into the matching checklist lines. Awards and the checklist use the
log chosen under Log to use as the already-have list.

County and callsign prefix stay off: WIMS does not ship a county list or a
prefix list. ``log/pfx.py`` is a short zone table for N1MM inserts, not a
prefix award. Continent, CQ zone, and ITU zone need the country file
(``cty.dat``). When that file is missing those three stay off.
"""

from __future__ import annotations

from wims.engine.contest_rules import Verdict, _entity, _upper, catalog
from wims.rules.cty import continent_name
from wims.rules.places import (
    canonical_place,
    is_us_state,
    place_name,
    place_word,
)

GOAL_TYPES = (
    {
        "id": "contest",
        "title": "Contest",
        "tip": (
            "Use one contest's rules for duplicates and points. "
            "Pick the contest in the next menu."
        ),
    },
    {
        "id": "award",
        "title": "Award",
        "tip": (
            "Chase an award. A station looks needed when it would be a new one "
            "for that award. The contacts already in the log are the ones you have."
        ),
    },
    {
        "id": "operating",
        "title": "Just operating (not a contest)",
        "tip": (
            "Not a contest. Checklist is the list of what is worth working. "
            "Each line can count the first time, on each band, or on each mode."
        ),
    },
    {
        "id": "custom",
        "title": "Custom",
        "tip": (
            "Your own checklist. If you saved contest rules under Advanced, "
            "they stay in the next menu."
        ),
    },
)

GOAL_TYPE_IDS = frozenset(row["id"] for row in GOAL_TYPES)

DETAIL_LABELS = {
    "contest": "Contest",
    "award": "Award",
    "operating": "Worth working",
    "custom": "Your list",
}

DETAIL_TIPS = {
    "contest": (
        "Which contest. WIMS follows that contest's rules for what counts as a new contact."
    ),
    "award": (
        "Which award. A station is new when that place is not already in the log."
    ),
    "operating": (
        "Checklist is what is worth working. Each line counts the first time, on each band, or on each mode."
    ),
    "custom": (
        "My checklist is yours to edit. Saved contest rules are the ones from Advanced."
    ),
}

AWARDS = (
    {
        "id": "dxcc",
        "title": "DXCC",
        "available": True,
        "rules_url": "https://www.arrl.org/dxcc",
        "summary": "Needed when the DXCC entity is not already in the log.",
        "tip": (
            "A new country or DXCC entity. "
            "WIMS treats contacts already in the log as the entities you have."
        ),
    },
    {
        "id": "was",
        "title": "Worked All States",
        "available": True,
        "rules_url": "https://www.arrl.org/was",
        "summary": "Needed when the US state is not already in the log.",
        "tip": (
            "A new US state. Fifty states. "
            "Canadian provinces do not count for Worked All States."
        ),
    },
    {
        "id": "vucc",
        "title": "VUCC (grid squares)",
        "available": True,
        "rules_url": "https://www.arrl.org/vucc",
        "summary": "Needed when the four-character grid square is not already in the log.",
        "tip": (
            "A new grid square, four characters such as FN42. "
            "The same square on another band is not a new square."
        ),
    },
    {
        "id": "county",
        "title": "County hunting (coming soon)",
        "available": False,
        "rules_url": "",
        "summary": "County hunting is not available yet. WIMS does not have a county list.",
        "tip": "Coming soon. WIMS does not have a county list yet, so this stays off.",
    },
)

AWARD_IDS = frozenset(row["id"] for row in AWARDS)
AWARD_BY_ID = {row["id"]: row for row in AWARDS}

# Checklist kinds. County and prefix are shown and not selectable.
# Continent and the two zone lines need cty.dat. They stay on the list either way.
CHECKLIST_KINDS = (
    {
        "id": "dxcc",
        "label": "New DXCC entity",
        "available": True,
        "tip": "A country or DXCC entity you do not already have in the log.",
    },
    {
        "id": "continent",
        "label": "New continent",
        "available": True,
        "needs_cty": True,
        "tip": "A continent you do not already have in the log.",
    },
    {
        "id": "cq",
        "label": "New CQ zone",
        "available": True,
        "needs_cty": True,
        "tip": "A CQ zone you do not already have in the log.",
    },
    {
        "id": "itu",
        "label": "New ITU zone",
        "available": True,
        "needs_cty": True,
        "tip": "An ITU zone you do not already have in the log.",
    },
    {
        "id": "grid",
        "label": "New grid",
        "available": True,
        "tip": "A grid square you do not already have in the log. Four characters, such as FN42.",
    },
    {
        "id": "state",
        "label": "New state or province",
        "available": True,
        "tip": "A US state, DC, or Canadian province you do not already have in the log.",
    },
    {
        "id": "county",
        "label": "New county",
        "available": False,
        "tip": "Coming soon. WIMS does not have a county list yet, so this stays off.",
    },
    {
        "id": "prefix",
        "label": "New callsign prefix",
        "available": False,
        "tip": "Coming soon. WIMS does not have a callsign-prefix list yet, so this stays off.",
    },
    {
        "id": "call",
        "label": "New call",
        "available": True,
        "tip": "A callsign you do not already have in the log.",
    },
)

KIND_BY_ID = {row["id"]: row for row in CHECKLIST_KINDS}
KIND_ORDER = tuple(row["id"] for row in CHECKLIST_KINDS)

SCOPES = (
    {"id": "overall", "label": "overall"},
    {"id": "band", "label": "per band"},
    {"id": "mode", "label": "per mode"},
)
SCOPE_IDS = frozenset(row["id"] for row in SCOPES)
SCOPE_TIP = (
    "Overall means the first time ever. Per band means each band can count again. "
    "Per mode means each mode can count again."
)

OPERATING_OPTIONS = (
    {
        "id": "checklist",
        "title": "Checklist",
        "enabled": True,
        "tip": "Tick what is worth working. Each line can count overall, per band, or per mode.",
    },
)

# WSJT-X factory color categories, used only when a saved Colors choice has
# no edited list. New DXCC and New DXCC on Band are the factory pair.
# Highlight by mode was never read from an ini here: several WSJT-X instances
# do not share one ini. It is kept only when the operator saved it in WIMS.
_COLOR_KEYS = (
    "new_dxcc",
    "new_dxcc_band",
    "new_grid",
    "new_grid_band",
    "new_call",
    "new_call_band",
)
DEFAULT_COLOR_CATEGORIES = {
    "new_dxcc": True,
    "new_dxcc_band": True,
    "new_grid": False,
    "new_grid_band": False,
    "new_call": False,
    "new_call_band": False,
}
_CTY_MISSING_TIP = (
    "WIMS could not find the country list (cty.dat) that WSJT-X keeps, so this stays off."
)
_PLACE_KINDS = ("dxcc", "continent", "cq", "itu", "grid", "state", "call")
_MULT_KINDS = frozenset({"dxcc", "continent", "cq", "itu", "grid", "state"})


def kind_available(kind: str) -> bool:
    row = KIND_BY_ID.get(kind)
    return bool(row and row["available"])


def award_available(award_id: str) -> bool:
    row = AWARD_BY_ID.get(award_id)
    return bool(row and row["available"])


def colors_to_checklist(categories, highlight_by_mode: bool = False) -> dict:
    """Colors categories → one checklist line per kind.

    ``new_dxcc`` is DXCC overall, ``new_dxcc_band`` is DXCC per band, and the
    same pattern maps grid and call. When both the overall and the per-band
    category are on, the line is per band: that still marks the first one
    and also marks a new band.

    Highlight by mode applies to call only. That is the category the Colors
    rule treated as per mode. A call line then becomes per mode, including
    a "new call on band" line. Per mode still marks a new mode on the same
    band. A new band in a mode already worked is not marked; the checklist
    stores one scope, and the saved flag asked for mode.

    Only grid fields sought is not a checklist scope. Grid stays the
    four-character square.
    """
    flags = {key: False for key in _COLOR_KEYS}
    for key, val in (categories or {}).items():
        if key in flags:
            flags[key] = bool(val)
    requested: dict[str, set[str]] = {"dxcc": set(), "grid": set(), "call": set()}
    pairs = (
        ("new_dxcc", "dxcc", "overall"),
        ("new_dxcc_band", "dxcc", "band"),
        ("new_grid", "grid", "overall"),
        ("new_grid_band", "grid", "band"),
        ("new_call", "call", "overall"),
        ("new_call_band", "call", "band"),
    )
    for cat, kind, scope in pairs:
        if not flags.get(cat):
            continue
        if highlight_by_mode and kind == "call":
            requested[kind].add("mode")
        else:
            requested[kind].add(scope)
    out = {}
    for kind in KIND_ORDER:
        out[kind] = {"enabled": False, "scope": "overall"}
    for kind, scopes in requested.items():
        if not scopes:
            continue
        if "mode" in scopes:
            # Highlight by mode asked for this. It replaces overall and band
            # on the call line, because the checklist keeps one scope.
            scope = "mode"
        elif "band" in scopes:
            scope = "band"
        else:
            scope = "overall"
        out[kind] = {"enabled": True, "scope": scope}
    return out


def default_checklist() -> dict:
    """DXCC overall starts on. County, prefix, continent, and zones start off."""
    out = {}
    for kind in KIND_ORDER:
        out[kind] = {
            "enabled": kind == "dxcc" and kind_available(kind),
            "scope": "overall",
        }
    return out


def normalize_checklist(raw) -> dict:
    """Stored checklist. Unavailable kinds cannot be turned on."""
    base = default_checklist()
    if raw is None:
        return base
    items: dict = {}
    if isinstance(raw, dict):
        items = raw
    elif isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("kind"):
                items[str(row["kind"])] = row
    else:
        return base
    # An explicit object replaces the default ticks. Missing kinds stay off
    # so a saved "all clear" list is not filled back in.
    for kind in KIND_ORDER:
        base[kind] = {"enabled": False, "scope": "overall"}
    for kind in KIND_ORDER:
        row = items.get(kind)
        if not isinstance(row, dict):
            continue
        scope = row.get("scope") or "overall"
        if scope not in SCOPE_IDS:
            scope = "overall"
        enabled = bool(row.get("enabled")) and kind_available(kind)
        base[kind] = {"enabled": enabled, "scope": scope}
    return base


def goal_from_legacy(contest) -> tuple[str, str]:
    """Schema 3 ``contest`` value → (goal, goal_id).

    An empty menu was the Colors fallback. ``shape_choice`` turns that into
    checklist lines before anything is saved.
    """
    if contest in (None, "", "none", "None"):
        return "operating", "wsjtx-colors"
    if contest == "custom":
        return "custom", "custom-file"
    return "contest", str(contest)


def legacy_contest(goal: str, goal_id: str):
    """Value older code still understands. Awards and the checklist stay empty."""
    if goal == "contest" and goal_id:
        return goal_id
    if goal == "custom" and goal_id == "custom-file":
        return "custom"
    return None


def _colors_checklist(data: dict) -> dict:
    """Saved Colors categories, or the factory defaults when none were saved."""
    override = data.get("wsjtx_override")
    if isinstance(override, dict) and isinstance(override.get("categories"), dict):
        cats = override["categories"]
    else:
        cats = DEFAULT_COLOR_CATEGORIES
    highlight = bool(override.get("highlight_by_mode")) if isinstance(override, dict) else False
    return colors_to_checklist(cats, highlight)


def shape_choice(data: dict | None) -> dict:
    """Current choice. A saved contest id is kept. Awards are not dropped.

    ``goal_id`` ``wsjtx-colors`` (and the older empty Contest menu, which
    meant the same thing) is converted once into checklist lines. The log
    is not part of this file.
    """
    from wims.rules.choice import SCHEMA, default_choice

    base = default_choice()
    if not isinstance(data, dict):
        return base
    schema = int(data.get("schema") or 0)
    contest = data.get("contest")
    if contest == "":
        contest = None
    trust_goal = (
        data.get("goal") in GOAL_TYPE_IDS
        and bool(data.get("goal_id"))
        and (schema >= 4 or "goal" in data)
    )
    # A schema-3 file that somehow also has goal still follows the contest field.
    if schema and schema < 4:
        trust_goal = False
    if trust_goal:
        goal = str(data["goal"])
        goal_id = str(data["goal_id"])
    else:
        goal, goal_id = goal_from_legacy(contest)
    if goal_id == "wsjtx-colors":
        goal = "operating"
        goal_id = "checklist"
        checklist = _colors_checklist(data)
    else:
        checklist_raw = data.get("checklist") if "checklist" in data else None
        checklist = normalize_checklist(checklist_raw)
    base.update({
        "schema": SCHEMA,
        "goal": goal,
        "goal_id": goal_id,
        "contest": legacy_contest(goal, goal_id),
        "explicit": bool(data.get("explicit")),
        "suggested": bool(data.get("suggested")),
        "fallback": "",
        "wsjtx_override": None,
        "gridtracker_path": data.get("gridtracker_path") or "",
        "station_state": data.get("station_state") or "",
        "station_county": data.get("station_county") or "",
        "checklist": checklist,
        "count_unconfirmed": _count_unconfirmed(data.get("count_unconfirmed")),
    })
    return base


def sanitize_selection(goal: str, goal_id: str, *, custom_available: bool) -> tuple[str, str]:
    """Drop unknown ids. County stays selectable so the screen can explain it."""
    if goal not in GOAL_TYPE_IDS:
        goal = "operating"
    goal_id = str(goal_id or "")
    if goal == "contest":
        ids = {row["id"] for row in catalog()}
        if goal_id not in ids:
            goal_id = "arrl-vhf" if "arrl-vhf" in ids else (sorted(ids)[0] if ids else "")
    elif goal == "award":
        if goal_id not in AWARD_IDS:
            goal_id = "dxcc"
    elif goal == "custom":
        if goal_id == "custom-file" and not custom_available:
            goal_id = "checklist"
        elif goal_id not in {"checklist", "custom-file"}:
            goal_id = "checklist"
    else:
        goal_id = "checklist"
    return goal, goal_id


def _option(row: dict, *, enabled: bool | None = None) -> dict:
    flag = row.get("enabled") if enabled is None else enabled
    if "available" in row and enabled is None:
        flag = bool(row["available"])
    title = row.get("title") or row.get("label") or row["id"]
    return {
        "id": row["id"],
        "title": title,
        "enabled": bool(flag),
        "tip": row.get("tip") or "",
    }


def goal_menu(choice: dict, *, custom_available: bool, cty_ok: bool = False) -> dict:
    """Dropdowns and the checklist for Setup. Plain-language tips included."""
    goal = choice.get("goal") or "operating"
    goal_id = choice.get("goal_id") or "checklist"
    contests = []
    for row in catalog():
        contests.append({
            "id": row["id"],
            "title": row["title"],
            "enabled": True,
            "tip": row.get("summary") or "",
        })
    awards = [_option(row) for row in AWARDS]
    operating = [_option(row) for row in OPERATING_OPTIONS]
    custom_opts = [_option({
        "id": "checklist",
        "title": "My checklist",
        "enabled": True,
        "tip": "Your own list of what is worth working.",
    })]
    if custom_available:
        custom_opts.append(_option({
            "id": "custom-file",
            "title": "Saved contest rules",
            "enabled": True,
            "tip": "The contest rules saved under Advanced.",
        }))
    menus = {
        "contest": {
            "label": DETAIL_LABELS["contest"],
            "tip": DETAIL_TIPS["contest"],
            "options": contests,
        },
        "award": {
            "label": DETAIL_LABELS["award"],
            "tip": DETAIL_TIPS["award"],
            "options": awards,
        },
        "operating": {
            "label": DETAIL_LABELS["operating"],
            "tip": DETAIL_TIPS["operating"],
            "options": operating,
        },
        "custom": {
            "label": DETAIL_LABELS["custom"],
            "tip": DETAIL_TIPS["custom"],
            "options": custom_opts,
        },
    }
    current = menus.get(goal) or menus["operating"]
    show = (
        (goal == "operating" and goal_id == "checklist")
        or (goal == "custom" and goal_id == "checklist")
    )
    # Awards and the checklist chase a place. Contest rules do not.
    show_unconfirmed = show or (goal == "award" and goal_id != "county")
    return {
        "type": goal,
        "id": goal_id,
        "types": [
            {"id": row["id"], "title": row["title"], "tip": row["tip"]}
            for row in GOAL_TYPES
        ],
        "detail_label": current["label"],
        "detail_tip": current["tip"],
        "options": current["options"],
        "menus": menus,
        "show_checklist": show,
        "show_unconfirmed": show_unconfirmed,
        "count_unconfirmed": _count_unconfirmed(choice.get("count_unconfirmed")),
        "checklist": _checklist_public(choice.get("checklist"), cty_ok=cty_ok),
        "scope_tip": SCOPE_TIP,
    }


def _checklist_public(raw, *, cty_ok: bool = False) -> dict:
    items = normalize_checklist(raw)
    rows = []
    for kind in CHECKLIST_KINDS:
        saved = items[kind["id"]]
        needs_cty = bool(kind.get("needs_cty"))
        runnable = bool(kind["available"]) and (cty_ok or not needs_cty)
        if needs_cty and not cty_ok:
            tip = _CTY_MISSING_TIP
        else:
            tip = kind["tip"]
        rows.append({
            "kind": kind["id"],
            "label": kind["label"],
            "enabled": bool(saved["enabled"]) and runnable,
            "stored": bool(saved["enabled"]),
            "scope": saved["scope"],
            "available": runnable,
            "coming_soon": not kind["available"],
            "tip": tip,
        })
    return {"rows": rows, "scopes": [dict(row) for row in SCOPES]}


def _grid4(grid: str | None) -> str | None:
    g = _upper(grid)
    if len(g) >= 4 and g[:2].isalpha() and g[2:4].isdigit():
        return g[:4]
    return None


def _row_mode(row: dict) -> str:
    return _upper(row.get("submode")) or _upper(row.get("mode"))


def _row_state(row: dict) -> str | None:
    found = canonical_place(row.get("state"))
    if found:
        return found
    return canonical_place(row.get("exchange"))


class AwardRules:
    """One award. Logged contacts are the already-have list."""

    def __init__(self, award_id: str, *, dxcc_lookup=None, log_label: str = "the log",
                 count_unconfirmed: bool = True):
        self.award_id = award_id if award_id in AWARD_IDS else "dxcc"
        meta = AWARD_BY_ID[self.award_id]
        self.id = f"award-{self.award_id}"
        self.title = meta["title"].replace(" (coming soon)", "")
        self.rules_url = meta["rules_url"]
        self.dxcc_lookup = dxcc_lookup
        self.log_label = log_label or "the log"
        self._summary = meta["summary"]
        self.count_unconfirmed = bool(count_unconfirmed)

    def plain_summary(self) -> str:
        line = self._summary
        if self.award_id == "dxcc" and self.dxcc_lookup is None:
            line += (
                " WIMS does not have a country list for callsigns, "
                "so a station counts only when the log stores a country number."
            )
        elif self.award_id == "was":
            line += " A station counts only when its state is known."
        elif self.award_id == "county":
            line = AWARD_BY_ID["county"]["summary"]
            return line
        return line + _confirm_tail(self.count_unconfirmed)

    def _index(self, store) -> dict:
        gen = store.generation() if hasattr(store, "generation") else 0
        lotw = _lotw_index()
        cache = getattr(self, "_cache", None)
        if cache and cache[0] == gen and cache[1] is store and cache[2] == lotw.token:
            return cache[3]
        built: dict = {"_worked_calls": set(), "_confirmed_calls": set()}
        for name in ("dxcc", "states", "grids"):
            _blank_buckets(built, name, scopes=False)
        for row in store.cached_rows():
            call = row.get("call") or ""
            confirmed = _row_is_confirmed(row, lotw)
            _note_station(built, call, confirmed)
            for key in _entity_keys(call, row.get("dxcc"), self.dxcc_lookup):
                _remember(built, "dxcc", key, "", "", call, confirmed)
            st = _row_state(row)
            if st:
                _remember(built, "states", st, "", "", call, confirmed)
            g = _grid4(row.get("grid"))
            if g:
                _remember(built, "grids", g, "", "", call, confirmed)
        _apply_lotw_places(
            built, lotw, self.dxcc_lookup, grid_kind="grids", state_kind="states",
        )
        self._cache = (gen, store, lotw.token, built)
        return built

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None,
                 state: str | None = None) -> Verdict:
        del my_county
        if not award_available(self.award_id):
            return Verdict(
                True, False,
                need_reason=(
                    "County hunting is not available yet. WIMS does not have a county list."
                ),
                points=1,
            )
        idx = self._index(store)
        label = self.log_label
        if self.award_id == "dxcc":
            keys = _entity_keys(call, None, self.dxcc_lookup)
            if not keys:
                return Verdict(
                    True, False,
                    need_reason=(
                        "WIMS does not know this station's DXCC entity, "
                        "so it is not marked needed."
                    ),
                    points=1,
                )
            shown = _pretty_entity(keys)
            mark = _mark_any(idx, "dxcc", "overall", keys, "", "", call)
            return self._from_mark(
                mark,
                need=f"Needed: new DXCC entity {shown} is not in {label}.",
                have=f"Already have: {shown} is in {label}.",
                mult=f"New mult: DXCC entity {shown}.",
                open_text=f"DXCC entity {shown} is worked but not confirmed.",
                nonconfirmer=_known_nonconfirmer(idx, call),
            )
        if self.award_id == "vucc":
            g = _grid4(grid)
            if not g:
                if _upper(grid):
                    reason = (
                        "This grid is only a field. VUCC counts the four-character square."
                    )
                else:
                    reason = "No grid, so this is not a new grid square."
                return Verdict(True, False, need_reason=reason, points=1)
            return self._from_mark(
                _mark(idx, "grids", "overall", g, "", "", call),
                need=f"Needed: new grid square {g} is not in {label}.",
                have=f"Already have: grid {g} is in {label}.",
                mult=f"New mult: grid {g}.",
                open_text=f"Grid {g} is worked but not confirmed.",
                nonconfirmer=_known_nonconfirmer(idx, call),
            )
        abbr = canonical_place(state) or canonical_place(exchange)
        if not abbr:
            return Verdict(
                True, False,
                need_reason=(
                    "WIMS does not know this station's state, so it is not marked as a new state."
                ),
                points=1,
            )
        if not is_us_state(abbr):
            name = place_name(abbr)
            word = place_word(abbr)
            return Verdict(
                True, False,
                need_reason=(
                    f"{name} is a {word}, not a US state, "
                    "so it does not count for Worked All States."
                ),
                points=1,
            )
        name = place_name(abbr)
        return self._from_mark(
            _mark(idx, "states", "overall", abbr, "", "", call),
            need=f"Needed: new state {name} is not in {label}.",
            have=f"Already have: {name} is in {label}.",
            mult=f"New mult: {name}.",
            open_text=f"{name} is worked but not confirmed.",
            nonconfirmer=_known_nonconfirmer(idx, call),
        )

    def _from_mark(self, mark, *, need, have, mult, open_text,
                   nonconfirmer: bool = False) -> Verdict:
        """New stays needed. Confirmed, or the same station, stays not needed.

        A station who has never confirmed any contact is not chased just to
        confirm a place. A place that is actually new is still needed.
        """
        if mark == "new":
            return Verdict(
                False, True,
                need_reason=need,
                mult_reason=mult,
                points=1,
                chase="needed",
            )
        if mark == "unconfirmed" and nonconfirmer:
            return Verdict(
                True, False,
                need_reason=_NEVER_CONFIRMED,
                points=1,
            )
        if mark == "unconfirmed":
            include = bool(self.count_unconfirmed)
            return Verdict(
                not include, False,
                need_reason=open_text,
                points=1,
                chase="unconfirmed",
            )
        if mark == "same" and nonconfirmer:
            return Verdict(True, False, need_reason=_same_never(have), points=1)
        return Verdict(True, False, need_reason=have, points=1)

    def public(self, *, source_label: str | None = None, n1mm: bool = False,
               extra: dict | None = None) -> dict:
        out = {
            "id": self.id,
            "title": self.title,
            "source_label": source_label or self.title,
            "n1mm_authoritative": bool(n1mm),
            "summary": self.plain_summary(),
            "rules_url": self.rules_url,
            "rules_version": "",
            "catalog": catalog(),
        }
        if extra:
            out.update(extra)
        return out


class ChecklistRules:
    """Just-operating or custom checklist. First matching line wins."""

    def __init__(self, items, *, title: str, dxcc_lookup=None, log_label: str = "the log",
                 cty=None, count_unconfirmed: bool = True):
        self.items = normalize_checklist(items)
        self.title = title or "Checklist"
        self.id = "custom-checklist" if "Custom" in self.title else "checklist"
        self.cty = cty
        if dxcc_lookup is None and cty is not None:
            dxcc_lookup = cty.entity_name
        self.dxcc_lookup = dxcc_lookup
        self.log_label = log_label or "the log"
        self.count_unconfirmed = bool(count_unconfirmed)

    def _line_on(self, kind: str) -> bool:
        row = self.items.get(kind) or {}
        if not row.get("enabled") or not kind_available(kind):
            return False
        if KIND_BY_ID[kind].get("needs_cty") and self.cty is None:
            return False
        return True

    def plain_summary(self) -> str:
        parts = []
        held = []
        for kind in KIND_ORDER:
            row = self.items[kind]
            if not row["enabled"] or not kind_available(kind):
                continue
            if KIND_BY_ID[kind].get("needs_cty") and self.cty is None:
                held.append(KIND_BY_ID[kind]["label"])
                continue
            scope_label = next(
                (s["label"] for s in SCOPES if s["id"] == row["scope"]), row["scope"],
            )
            parts.append(f"{KIND_BY_ID[kind]['label']} ({scope_label})")
        if not parts:
            line = "Nothing is checked, so no station will show as needed."
        else:
            line = (
                "Needed when a station matches " + ", ".join(parts) + "."
                + _confirm_tail(self.count_unconfirmed)
            )
        if self.items["dxcc"]["enabled"] and self.dxcc_lookup is None:
            line += " DXCC uses country numbers stored in the log."
        if held:
            line += " " + ", ".join(held) + " is off because the country list was not found."
            if len(held) > 1:
                line = line.replace(" is off because", " are off because", 1)
        return line

    def _index(self, store) -> dict:
        gen = store.generation() if hasattr(store, "generation") else 0
        lotw = _lotw_index()
        cache = getattr(self, "_cache", None)
        if cache and cache[0] == gen and cache[1] is store and cache[2] == lotw.token:
            return cache[3]
        built = {"_worked_calls": set(), "_confirmed_calls": set()}
        for kind in _PLACE_KINDS:
            _blank_buckets(built, kind)
        for row in store.cached_rows():
            band = row.get("band") or ""
            mode = _row_mode(row)
            call = _upper(row.get("call"))
            confirmed = _row_is_confirmed(row, lotw)
            _note_station(built, call, confirmed)
            if call:
                _remember(built, "call", call, band, mode, call, confirmed)
            g = _grid4(row.get("grid"))
            if g:
                _remember(built, "grid", g, band, mode, call, confirmed)
            st = _row_state(row)
            if st:
                _remember(built, "state", st, band, mode, call, confirmed)
            for key in _entity_keys(row.get("call") or "", row.get("dxcc"), self.dxcc_lookup):
                _remember(built, "dxcc", key, band, mode, call, confirmed)
            place = self._describe(
                row.get("call") or "",
                row.get("grid"),
                cqz=row.get("cqz"),
                ituz=row.get("ituz"),
                cont=row.get("cont"),
            )
            if place is None:
                continue
            if place.continent:
                _remember(built, "continent", place.continent, band, mode, call, confirmed)
            if place.cq is not None and not place.cq_uncertain:
                _remember(built, "cq", place.cq, band, mode, call, confirmed)
            if place.itu is not None and not place.itu_uncertain:
                _remember(built, "itu", place.itu, band, mode, call, confirmed)
        _apply_lotw_places(
            built, lotw, self.dxcc_lookup, grid_kind="grid", state_kind="state",
        )
        self._cache = (gen, store, lotw.token, built)
        return built

    def _describe(self, call, grid, *, cqz=None, ituz=None, cont=None):
        if self.cty is None:
            return None
        return self.cty.describe(call, grid, cqz=cqz, ituz=ituz, cont=cont)

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None,
                 state: str | None = None) -> Verdict:
        del my_county
        idx = self._index(store)
        call_u = _upper(call)
        mode_u = _upper(mode)
        place = self._describe(call_u, grid)
        unknowns: list[str] = []
        worked_notes: list[str] = []
        uncertain: list[str] = []
        checked = 0
        first = None
        first_open = None
        saw_same = False
        saw_confirmed = False
        quiet = _known_nonconfirmer(idx, call_u)
        for kind in KIND_ORDER:
            if not self._line_on(kind):
                continue
            checked += 1
            scope = self.items[kind]["scope"]
            hit = self._hit(
                kind, scope, idx, call_u, band, mode_u, grid, state, exchange, place,
            )
            tag = hit[0]
            if tag == "need" and first is None:
                first = (kind, hit[1], hit[2])
            elif tag == "unconfirmed" and first_open is None:
                first_open = hit[1]
            elif tag == "same":
                saw_same = True
                worked_notes.append(hit[1])
            elif tag == "worked":
                saw_confirmed = True
                worked_notes.append(hit[1])
            elif tag == "unknown":
                unknowns.append(hit[1])
            elif tag == "uncertain":
                uncertain.append(hit[1])
        if first is not None:
            kind, reason, mult_reason = first
            return Verdict(
                False, kind in _MULT_KINDS,
                need_reason=_with_uncertain(reason, uncertain),
                mult_reason=mult_reason if kind in _MULT_KINDS else "",
                points=1,
                chase="needed",
            )
        if first_open is not None and quiet:
            return Verdict(
                True, False,
                need_reason=_with_uncertain(_NEVER_CONFIRMED, uncertain),
                points=1,
            )
        if first_open is not None:
            include = bool(self.count_unconfirmed)
            return Verdict(
                not include, False,
                need_reason=_with_uncertain(first_open, uncertain),
                points=1,
                chase="unconfirmed",
            )
        if checked and not worked_notes and len(unknowns) + len(uncertain) >= checked:
            if uncertain:
                return Verdict(
                    True, False,
                    need_reason=_uncertain_sentence(uncertain),
                    points=1,
                )
            return Verdict(
                True, False,
                need_reason="WIMS cannot tell yet: " + ", ".join(unknowns) + ".",
                points=1,
            )
        if not checked:
            return Verdict(
                True, False,
                need_reason="Nothing is checked, so no station will show as needed.",
                points=1,
            )
        if worked_notes:
            note = "Not needed: " + "; ".join(worked_notes) + "."
            if saw_same and not saw_confirmed and quiet:
                note += " " + _NEVER_CONFIRMED
        else:
            note = f"Not needed: nothing checked is new in {self.log_label}."
        return Verdict(
            True, False,
            need_reason=_with_uncertain(note, uncertain),
            points=1,
        )

    def _hit(self, kind, scope, idx, call, band, mode, grid, state, exchange, place):
        """``(tag, text, mult_reason)``.

        ``need`` marks a new unit. ``unconfirmed`` is a worked unit that is not
        confirmed, heard from a station that is not already in that unit
        for this scope. ``same`` is that station again in this scope.
        ``worked`` is a confirmed unit. ``unknown`` and ``uncertain`` do not
        claim needed. ``uncertain`` is the zone-uncertain case: the country
        is known and the zone is not.
        """
        label = self.log_label
        where = _where(scope, band, mode)
        if kind == "call":
            if not call:
                return ("unknown", "callsign", "")
            worked = _scoped(idx, "call", scope, call, band, mode)
            if worked is None:
                return ("unknown", "callsign", "")
            if worked:
                return ("worked", f"call {call}{where} is already in {label}", "")
            return ("need", _need("call", call, scope, band, mode, label), "")
        if kind == "grid":
            g = _grid4(grid)
            if not g:
                return ("unknown", "grid", "")
            return self._place_mark(
                "grid", scope, idx, g, band, mode, call,
                have=f"grid {g}{where} is already in {label}",
                need=_need("grid", g, scope, band, mode, label),
                mult=f"New mult: grid {g}{where} in {label}.",
                open_text=_open_text("grid", g, scope, band, mode),
                unknown="grid",
            )
        if kind == "state":
            abbr = canonical_place(state) or canonical_place(exchange)
            if not abbr:
                return ("unknown", "state", "")
            name = place_name(abbr)
            return self._place_mark(
                "state", scope, idx, abbr, band, mode, call,
                have=f"{name}{where} is already in {label}",
                need=_need("state", name, scope, band, mode, label),
                mult=f"New mult: {name}{where} in {label}.",
                open_text=_open_text("state", name, scope, band, mode),
                unknown="state",
            )
        if kind in {"continent", "cq", "itu"}:
            return self._place_hit(kind, scope, idx, band, mode, place, call)
        keys = _entity_keys(call, None, self.dxcc_lookup)
        if not keys:
            return ("unknown", "DXCC entity", "")
        mark = _mark_any(idx, "dxcc", scope, keys, band, mode, call)
        if mark is None:
            return ("unknown", "DXCC entity", "")
        shown = _pretty_entity(keys)
        return self._tag_mark(
            mark,
            have=f"DXCC entity {shown}{where} is already in {label}",
            need=_need("dxcc", shown, scope, band, mode, label),
            mult=f"New mult: DXCC entity {shown}{where} in {label}.",
            open_text=_open_text("dxcc", shown, scope, band, mode),
            unknown="DXCC entity",
        )

    def _place_mark(self, kind, scope, idx, key, band, mode, call, *,
                    have, need, mult, open_text, unknown):
        mark = _mark(idx, kind, scope, key, band, mode, call)
        return self._tag_mark(
            mark, have=have, need=need, mult=mult,
            open_text=open_text, unknown=unknown,
        )

    def _tag_mark(self, mark, *, have, need, mult, open_text, unknown):
        if mark is None:
            return ("unknown", unknown, "")
        if mark == "new":
            return ("need", need, mult)
        if mark == "unconfirmed":
            return ("unconfirmed", open_text, "")
        if mark == "same":
            return ("same", have, "")
        return ("worked", have, "")

    def _place_hit(self, kind, scope, idx, band, mode, place, call):
        label = self.log_label
        where = _where(scope, band, mode)
        if place is None:
            return ("unknown", _place_word(kind), "")
        if kind == "continent":
            code = place.continent
            if not code:
                return ("unknown", "continent", "")
            shown = continent_name(code)
            key = code
            need = f"Need: continent {shown}{where} in {label}."
            mult = f"New mult: continent {shown}{where} in {label}."
            have = f"continent {shown}{where} is already in {label}"
        elif kind == "cq":
            if place.cq_uncertain:
                return ("uncertain", "CQ zone uncertain", "")
            if place.cq is None:
                return ("unknown", "CQ zone", "")
            key = place.cq
            need = f"Need: CQ zone {key}{where} in {label}."
            mult = f"New mult: CQ zone {key}{where} in {label}."
            have = f"CQ zone {key}{where} is already in {label}"
        else:
            if place.itu_uncertain:
                return ("uncertain", "ITU zone uncertain", "")
            if place.itu is None:
                return ("unknown", "ITU zone", "")
            key = place.itu
            need = f"Need: ITU zone {key}{where} in {label}."
            mult = f"New mult: ITU zone {key}{where} in {label}."
            have = f"ITU zone {key}{where} is already in {label}"
        shown_open = shown if kind == "continent" else key
        return self._place_mark(
            kind, scope, idx, key, band, mode, call,
            have=have, need=need, mult=mult,
            open_text=_open_text(kind, shown_open, scope, band, mode),
            unknown=_place_word(kind),
        )

    def public(self, *, source_label: str | None = None, n1mm: bool = False,
               extra: dict | None = None) -> dict:
        out = {
            "id": self.id,
            "title": self.title,
            "source_label": source_label or self.title,
            "n1mm_authoritative": bool(n1mm),
            "summary": self.plain_summary(),
            "rules_url": "",
            "rules_version": "",
            "catalog": catalog(),
        }
        if extra:
            out.update(extra)
        return out


def _count_unconfirmed(value) -> bool:
    """Missing means include worked-but-unconfirmed in Needed."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _confirm_tail(include: bool) -> str:
    if include:
        return " A worked place that is not confirmed still counts as needed."
    return " A worked place that is not confirmed stays off the needed list."


def _row_confirmed(row: dict) -> bool:
    return bool(row.get("confirmed"))


def _lotw_index():
    """GridTracker LoTW file, if this PC has one. Re-read when it changes."""
    from wims.lotw import current
    return current()


def _row_is_confirmed(row: dict, lotw) -> bool:
    """The log's own QSL yes, or a matching LoTW record."""
    if _row_confirmed(row):
        return True
    return bool(lotw is not None and lotw.confirms_row(row))


def _lotw_entity_keys(call: str, dxcc: str | None, lookup) -> set[str]:
    keys: set[str] = set()
    if dxcc:
        keys.add(f"dxcc:{dxcc}")
    named = _entity(call, None, lookup)
    if named:
        keys.add(named)
    return keys


def _apply_lotw_places(built, lotw, lookup, *, grid_kind: str, state_kind: str) -> None:
    """A LoTW record's own grid, state, and DXCC confirm that place.

    The record's band is the band. Every mode in its LoTW mode group counts
    as confirmed where that place was already worked, so FT8 in the log and
    DATA or MFSK on the LoTW record are the same confirmation.
    """
    if lotw is None or not getattr(lotw, "records", None):
        return
    from wims.lotw import modes_in_group
    for rec in lotw.records:
        _note_station(built, rec.call, True)
        extras = [m for m in modes_in_group(rec.group) if m and m != rec.mode]

        def add(kind: str, key, extras=extras) -> None:
            _remember(built, kind, key, rec.band, rec.mode, rec.call, True)
            if not extras:
                return
            slot = built.setdefault(kind + "_mode_ok", set())
            for mode in extras:
                slot.add((key, mode))

        if rec.grid:
            add(grid_kind, rec.grid)
        if rec.state:
            add(state_kind, rec.state)
        for key in _lotw_entity_keys(rec.call, rec.dxcc, lookup):
            add("dxcc", key)


# Shown under All when this station is not chased for a confirmation.
_NEVER_CONFIRMED = "Worked before, never confirmed."


def _same_never(have: str) -> str:
    text = have.rstrip()
    if text.endswith("."):
        return text + " " + _NEVER_CONFIRMED
    return text + ". " + _NEVER_CONFIRMED


def _note_station(built: dict, call: str, confirmed: bool) -> None:
    """Any contact, on any band, counts toward 'worked before'."""
    call_u = _upper(call)
    if not call_u:
        return
    built.setdefault("_worked_calls", set()).add(call_u)
    if confirmed:
        built.setdefault("_confirmed_calls", set()).add(call_u)


def _known_nonconfirmer(idx: dict, call: str) -> bool:
    """True when this station has contacts and none of them are confirmed.

    The check is the whole log, not the goal scope. One confirmed contact
    anywhere means the station is not a known non-confirmer.
    """
    call_u = _upper(call)
    if not call_u or call_u not in (idx.get("_worked_calls") or ()):
        return False
    return call_u not in (idx.get("_confirmed_calls") or ())


def _norm_band(band: str) -> str:
    return (band or "").strip().lower()


def _blank_buckets(built: dict, kind: str, *, scopes: bool = True) -> None:
    built[kind] = set()
    built[kind + "_calls"] = {}
    built[kind + "_ok"] = set()
    if not scopes:
        return
    for suffix in ("_band", "_mode"):
        built[kind + suffix] = set()
        built[kind + suffix + "_calls"] = {}
        built[kind + suffix + "_ok"] = set()


def _remember(built: dict, kind: str, key, band: str, mode: str,
              call: str, confirmed: bool) -> None:
    """Record a worked unit and the station that worked it.

    The overall bucket is any band and any mode. The band bucket is that
    band only. The mode bucket is that mode only. Confirmation is separate
    from who worked it.
    """
    call_u = _upper(call)
    band_u = _norm_band(band)
    mode_u = _upper(mode)

    def note(bucket, token) -> None:
        built.setdefault(bucket, set()).add(token)
        slot = built.setdefault(bucket + "_calls", {}).setdefault(token, set())
        if call_u:
            slot.add(call_u)
        if confirmed:
            built.setdefault(bucket + "_ok", set()).add(token)

    note(kind, key)
    if band_u:
        note(f"{kind}_band", (key, band_u))
    if mode_u:
        note(f"{kind}_mode", (key, mode_u))


def _where(scope: str, band: str, mode: str) -> str:
    band_u = _norm_band(band)
    mode_u = _upper(mode)
    if scope == "band" and band_u:
        return f" on {band_u}"
    if scope == "mode" and mode_u:
        return f" on {mode_u}"
    return ""


def _place_word(kind: str) -> str:
    if kind == "cq":
        return "CQ zone"
    if kind == "itu":
        return "ITU zone"
    return "continent"


def _uncertain_sentence(notes: list[str]) -> str:
    """Hover text. The words ``zone uncertain`` are the conservative mark."""
    return ". ".join(notes) + "."


def _with_uncertain(reason: str, notes: list[str]) -> str:
    if not notes:
        return reason
    extra = _uncertain_sentence(notes)
    if "zone uncertain" in reason:
        return reason
    text = reason.rstrip()
    if text.endswith("."):
        return text + " " + extra
    return text + ". " + extra


def _entity_keys(call: str, dxcc, lookup) -> set[str]:
    keys: set[str] = set()
    one = _entity(call, dxcc, None)
    if one:
        keys.add(one)
    named = _entity(call, None, lookup)
    if named:
        keys.add(named)
    return keys


def _pretty_entity(keys: set[str]) -> str:
    names = [k.split(":", 1)[1] for k in sorted(keys) if k.startswith("name:")]
    if names:
        return names[0]
    nums = [k.split(":", 1)[1] for k in sorted(keys) if k.startswith("dxcc:")]
    if nums:
        return f"DXCC {nums[0]}"
    return "this entity"


def _scope_bucket(kind: str, scope: str) -> str:
    if scope == "band":
        return f"{kind}_band"
    if scope == "mode":
        return f"{kind}_mode"
    return kind


def _scope_token(scope: str, key, band: str, mode: str):
    """Overall ignores band and mode. Per band is that band. Per mode is that mode."""
    if scope == "band":
        return (key, _norm_band(band))
    if scope == "mode":
        return (key, _upper(mode))
    return key


def _mark(idx: dict, kind: str, scope: str, key, band: str, mode: str, call: str):
    """``new``, ``confirmed``, ``same``, ``unconfirmed``, or None.

    None means this scope cannot be checked (no band, or no mode).
    ``same`` is an unconfirmed unit heard from a station already worked for
    that unit in this scope: overall means any band or mode, per band means
    that band, per mode means that mode.
    """
    flag = _scoped(idx, kind, scope, key, band, mode)
    if flag is None:
        return None
    if not flag:
        return "new"
    token = _scope_token(scope, key, band, mode)
    bucket = _scope_bucket(kind, scope)
    if token in (idx.get(bucket + "_ok") or ()):
        return "confirmed"
    calls = (idx.get(bucket + "_calls") or {}).get(token) or set()
    if _upper(call) and _upper(call) in calls:
        return "same"
    return "unconfirmed"


def _mark_any(idx, kind, scope, keys, band, mode, call):
    """One entity can match more than one stored key. Confirmed wins."""
    saw = False
    opened = False
    same = False
    for key in keys:
        mark = _mark(idx, kind, scope, key, band, mode, call)
        if mark is None:
            continue
        saw = True
        if mark == "confirmed":
            return "confirmed"
        if mark == "same":
            same = True
        elif mark == "unconfirmed":
            opened = True
    if not saw:
        return None
    if same:
        return "same"
    if opened:
        return "unconfirmed"
    return "new"


def _open_text(kind: str, shown, scope: str, band: str, mode: str) -> str:
    where = _where(scope, band, mode)
    if kind == "dxcc":
        what = f"DXCC entity {shown}"
    elif kind == "grid":
        what = f"Grid {shown}"
    elif kind == "state":
        what = str(shown)
    elif kind == "continent":
        what = f"Continent {shown}"
    elif kind == "cq":
        what = f"CQ zone {shown}"
    elif kind == "itu":
        what = f"ITU zone {shown}"
    else:
        what = str(shown)
    return f"{what}{where} is worked but not confirmed."


def _scoped(idx: dict, kind: str, scope: str, key, band: str, mode: str):
    """True if already worked, False if new, None if the scope cannot be checked.

    Overall is any band and any mode. Per band is that band only. Per mode
    is that mode only.
    """
    if scope == "band":
        band_u = _norm_band(band)
        if not band_u:
            return None
        return (key, band_u) in idx[f"{kind}_band"]
    if scope == "mode":
        mode_u = _upper(mode)
        if not mode_u:
            return None
        return (key, mode_u) in idx[f"{kind}_mode"]
    return key in idx[kind]


def _need(kind: str, shown: str, scope: str, band: str, mode: str, label: str) -> str:
    where = ""
    band_u = _norm_band(band)
    mode_u = _upper(mode)
    if scope == "band" and band_u:
        where = f" on {band_u}"
    elif scope == "mode" and mode_u:
        where = f" on {mode_u}"
    if kind == "dxcc":
        what = f"new DXCC entity {shown}"
    elif kind == "grid":
        what = f"new grid {shown}"
    elif kind == "state":
        what = f"new state or province {shown}"
    else:
        what = f"new call {shown}"
    return f"Needed: {what}{where} is not in {label}."
