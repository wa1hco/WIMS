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

Awards and the checklist use logged contacts as the already-have list.
County and callsign prefix stay off: WIMS does not ship a county list or a
prefix list. ``log/pfx.py`` is a short zone table for N1MM inserts, not a
prefix award.
"""

from __future__ import annotations

from wims.engine.contest_rules import Verdict, _entity, _upper, catalog
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
            "Not a contest. WSJT-X Colors follows the color settings. "
            "Checklist is a short list of what is worth working."
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
        "WSJT-X Colors follows the color settings. Checklist lets you tick what is worth working."
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
CHECKLIST_KINDS = (
    {
        "id": "dxcc",
        "label": "New DXCC entity",
        "available": True,
        "tip": "A country or DXCC entity you do not already have in the log.",
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
        "id": "wsjtx-colors",
        "title": "WSJT-X Colors",
        "enabled": True,
        "tip": "Follow the WSJT-X color settings. You can change those under Advanced.",
    },
    {
        "id": "checklist",
        "title": "Checklist",
        "enabled": True,
        "tip": "Tick what is worth working. Each line can count overall, per band, or per mode.",
    },
)


def kind_available(kind: str) -> bool:
    row = KIND_BY_ID.get(kind)
    return bool(row and row["available"])


def award_available(award_id: str) -> bool:
    row = AWARD_BY_ID.get(award_id)
    return bool(row and row["available"])


def default_checklist() -> dict:
    """DXCC overall starts on. County and prefix stay off."""
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
    """Schema 3 ``contest`` value → (goal, goal_id)."""
    if contest in (None, "", "none", "None"):
        return "operating", "wsjtx-colors"
    if contest == "custom":
        return "custom", "custom-file"
    return "contest", str(contest)


def legacy_contest(goal: str, goal_id: str):
    """Value older code still understands. Awards and Colors stay empty."""
    if goal == "contest" and goal_id:
        return goal_id
    if goal == "custom" and goal_id == "custom-file":
        return "custom"
    return None


def shape_choice(data: dict | None) -> dict:
    """Schema-4 choice. A saved contest id is kept. Awards are not dropped."""
    from wims.rules.choice import default_choice

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
    checklist_raw = data.get("checklist") if "checklist" in data else None
    base.update({
        "schema": 4,
        "goal": goal,
        "goal_id": goal_id,
        "contest": legacy_contest(goal, goal_id),
        "explicit": bool(data.get("explicit")),
        "suggested": bool(data.get("suggested")),
        "fallback": data.get("fallback") or "wsjtx-colors",
        "wsjtx_override": data.get("wsjtx_override"),
        "gridtracker_path": data.get("gridtracker_path") or "",
        "station_state": data.get("station_state") or "",
        "station_county": data.get("station_county") or "",
        "checklist": normalize_checklist(checklist_raw),
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
        if goal_id not in {"wsjtx-colors", "checklist"}:
            goal_id = "wsjtx-colors"
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


def goal_menu(choice: dict, *, custom_available: bool) -> dict:
    """Dropdowns and the checklist for Setup. Plain-language tips included."""
    goal = choice.get("goal") or "operating"
    goal_id = choice.get("goal_id") or "wsjtx-colors"
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
        "checklist": _checklist_public(choice.get("checklist")),
        "scope_tip": SCOPE_TIP,
    }


def _checklist_public(raw) -> dict:
    items = normalize_checklist(raw)
    rows = []
    for kind in CHECKLIST_KINDS:
        saved = items[kind["id"]]
        rows.append({
            "kind": kind["id"],
            "label": kind["label"],
            "enabled": bool(saved["enabled"]) and kind["available"],
            "scope": saved["scope"],
            "available": kind["available"],
            "coming_soon": not kind["available"],
            "tip": kind["tip"],
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

    def __init__(self, award_id: str, *, dxcc_lookup=None, log_label: str = "the log"):
        self.award_id = award_id if award_id in AWARD_IDS else "dxcc"
        meta = AWARD_BY_ID[self.award_id]
        self.id = f"award-{self.award_id}"
        self.title = meta["title"].replace(" (coming soon)", "")
        self.rules_url = meta["rules_url"]
        self.dxcc_lookup = dxcc_lookup
        self.log_label = log_label or "the log"
        self._summary = meta["summary"]

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

    def _index(self, store) -> dict:
        gen = store.generation() if hasattr(store, "generation") else 0
        cache = getattr(self, "_cache", None)
        if cache and cache[0] == gen and cache[1] is store:
            return cache[2]
        dxcc: set[str] = set()
        states: set[str] = set()
        grids: set[str] = set()
        for row in store.cached_rows():
            for key in _entity_keys(row.get("call") or "", row.get("dxcc"), self.dxcc_lookup):
                dxcc.add(key)
            st = _row_state(row)
            if st:
                states.add(st)
            g = _grid4(row.get("grid"))
            if g:
                grids.add(g)
        built = {"dxcc": dxcc, "states": states, "grids": grids}
        self._cache = (gen, store, built)
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
            if keys & idx["dxcc"]:
                shown = _pretty_entity(keys)
                return Verdict(
                    True, False,
                    need_reason=f"Already have: {shown} is in {label}.",
                    points=1,
                )
            shown = _pretty_entity(keys)
            return Verdict(
                False, True,
                need_reason=f"Needed: new DXCC entity {shown} is not in {label}.",
                mult_reason=f"New mult: DXCC entity {shown}.",
                points=1,
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
            if g in idx["grids"]:
                return Verdict(
                    True, False,
                    need_reason=f"Already have: grid {g} is in {label}.",
                    points=1,
                )
            return Verdict(
                False, True,
                need_reason=f"Needed: new grid square {g} is not in {label}.",
                mult_reason=f"New mult: grid {g}.",
                points=1,
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
        if abbr in idx["states"]:
            return Verdict(
                True, False,
                need_reason=f"Already have: {name} is in {label}.",
                points=1,
            )
        return Verdict(
            False, True,
            need_reason=f"Needed: new state {name} is not in {label}.",
            mult_reason=f"New mult: {name}.",
            points=1,
        )

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

    def __init__(self, items, *, title: str, dxcc_lookup=None, log_label: str = "the log"):
        self.items = normalize_checklist(items)
        self.title = title or "Checklist"
        self.id = "custom-checklist" if "Custom" in self.title else "checklist"
        self.dxcc_lookup = dxcc_lookup
        self.log_label = log_label or "the log"

    def plain_summary(self) -> str:
        parts = []
        for kind in KIND_ORDER:
            row = self.items[kind]
            if not row["enabled"] or not kind_available(kind):
                continue
            scope_label = next(
                (s["label"] for s in SCOPES if s["id"] == row["scope"]), row["scope"],
            )
            parts.append(f"{KIND_BY_ID[kind]['label']} ({scope_label})")
        if not parts:
            line = "Nothing is checked, so no station will show as needed."
        else:
            line = "Needed when a station matches " + ", ".join(parts) + "."
        if self.items["dxcc"]["enabled"] and self.dxcc_lookup is None:
            line += " DXCC uses country numbers stored in the log."
        return line

    def _index(self, store) -> dict:
        gen = store.generation() if hasattr(store, "generation") else 0
        cache = getattr(self, "_cache", None)
        if cache and cache[0] == gen and cache[1] is store:
            return cache[2]
        built = {
            "dxcc": set(), "dxcc_band": set(), "dxcc_mode": set(),
            "grid": set(), "grid_band": set(), "grid_mode": set(),
            "state": set(), "state_band": set(), "state_mode": set(),
            "call": set(), "call_band": set(), "call_mode": set(),
        }
        for row in store.cached_rows():
            band = row.get("band") or ""
            mode = _row_mode(row)
            call = _upper(row.get("call"))
            if call:
                built["call"].add(call)
                if band:
                    built["call_band"].add((call, band))
                if mode:
                    built["call_mode"].add((call, mode))
            g = _grid4(row.get("grid"))
            if g:
                built["grid"].add(g)
                if band:
                    built["grid_band"].add((g, band))
                if mode:
                    built["grid_mode"].add((g, mode))
            st = _row_state(row)
            if st:
                built["state"].add(st)
                if band:
                    built["state_band"].add((st, band))
                if mode:
                    built["state_mode"].add((st, mode))
            for key in _entity_keys(row.get("call") or "", row.get("dxcc"), self.dxcc_lookup):
                built["dxcc"].add(key)
                if band:
                    built["dxcc_band"].add((key, band))
                if mode:
                    built["dxcc_mode"].add((key, mode))
        self._cache = (gen, store, built)
        return built

    def classify(self, store, call: str, band: str, mode: str | None, grid: str | None,
                 *, exchange: str | None = None, my_county: str | None = None,
                 state: str | None = None) -> Verdict:
        del my_county
        idx = self._index(store)
        call_u = _upper(call)
        mode_u = _upper(mode)
        unknowns: list[str] = []
        checked = 0
        for kind in KIND_ORDER:
            row = self.items[kind]
            if not row["enabled"] or not kind_available(kind):
                continue
            checked += 1
            scope = row["scope"]
            hit = self._hit(
                kind, scope, idx, call_u, band, mode_u, grid, state, exchange, unknowns,
            )
            if hit is None:
                continue
            if hit[0]:
                mult = kind in {"dxcc", "grid", "state"}
                return Verdict(
                    False, mult,
                    need_reason=hit[1],
                    mult_reason=hit[2] if mult else "",
                    points=1,
                )
        if checked and unknowns and len(unknowns) >= checked:
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
        return Verdict(
            True, False,
            need_reason=f"Not needed: nothing checked is new in {self.log_label}.",
            points=1,
        )

    def _hit(self, kind, scope, idx, call, band, mode, grid, state, exchange, unknowns):
        """Return (needed, reason, mult_reason) or None when this line does not match.

        None means the line was known and already worked, or it was skipped.
        Unknown values are recorded and the line does not count as needed.
        """
        label = self.log_label
        if kind == "call":
            if not call:
                unknowns.append("callsign")
                return None
            worked = _scoped(idx, "call", scope, call, band, mode)
            if worked is None:
                unknowns.append("callsign")
                return None
            if worked:
                return None
            return True, _need("call", call, scope, band, mode, label), ""
        if kind == "grid":
            g = _grid4(grid)
            if not g:
                unknowns.append("grid")
                return None
            worked = _scoped(idx, "grid", scope, g, band, mode)
            if worked is None:
                unknowns.append("grid")
                return None
            if worked:
                return None
            return (
                True,
                _need("grid", g, scope, band, mode, label),
                f"New mult: grid {g}.",
            )
        if kind == "state":
            abbr = canonical_place(state) or canonical_place(exchange)
            if not abbr:
                unknowns.append("state")
                return None
            worked = _scoped(idx, "state", scope, abbr, band, mode)
            if worked is None:
                unknowns.append("state")
                return None
            if worked:
                return None
            name = place_name(abbr)
            return (
                True,
                _need("state", name, scope, band, mode, label),
                f"New mult: {name}.",
            )
        keys = _entity_keys(call, None, self.dxcc_lookup)
        if not keys:
            unknowns.append("DXCC entity")
            return None
        worked = False
        known = False
        for key in keys:
            flag = _scoped(idx, "dxcc", scope, key, band, mode)
            if flag is None:
                continue
            known = True
            worked = worked or flag
        if not known:
            unknowns.append("DXCC entity")
            return None
        if worked:
            return None
        shown = _pretty_entity(keys)
        return (
            True,
            _need("dxcc", shown, scope, band, mode, label),
            f"New mult: DXCC entity {shown}.",
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


def _scoped(idx: dict, kind: str, scope: str, key, band: str, mode: str):
    """True if already worked, False if new, None if the scope cannot be checked."""
    if scope == "band":
        if not band:
            return None
        return (key, band) in idx[f"{kind}_band"]
    if scope == "mode":
        if not mode:
            return None
        return (key, mode) in idx[f"{kind}_mode"]
    return key in idx[kind]


def _need(kind: str, shown: str, scope: str, band: str, mode: str, label: str) -> str:
    where = ""
    if scope == "band" and band:
        where = f" on {band}"
    elif scope == "mode" and mode:
        where = f" on {mode}"
    if kind == "dxcc":
        what = f"new DXCC entity {shown}"
    elif kind == "grid":
        what = f"new grid {shown}"
    elif kind == "state":
        what = f"new state or province {shown}"
    else:
        what = f"new call {shown}"
    return f"Needed: {what}{where} is not in {label}."
