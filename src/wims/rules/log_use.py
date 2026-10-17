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

"""Which log needed/dupe uses, plus an optional time window.

The log, the start time, and the optional end time are separate. The goal
may suggest a log when the operator has not chosen one. It never replaces
a saved choice. The window changes which contacts the lookup sees.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Presets the operator can pick without typing a date. "custom" is a stored
# window that did not come from one of these (tests, or a later end time).
CUTOFF_CHOICES = (
    {"id": "whole", "title": "Whole log"},
    {"id": "start_now", "title": "Start now"},
    {"id": "this_year", "title": "This year"},
)

SUGGESTED_ID = "auto"

WSJTX_CONTEST_NOTE = (
    "This WSJT-X log does not store a contest name or an exchange. "
    "A county, section, or contest-name check cannot be completed from it. "
    "Choose the contest log from your logger when you need those."
)


def contest_name_matches(goal_id: str, contest_name: str) -> bool:
    """True when an N1MM contest name belongs to this rules file."""
    token = _upper(contest_name)
    if not token or not goal_id:
        return False
    try:
        from wims.engine.contest_rules import load_builtin
        rules = load_builtin(str(goal_id))
    except (KeyError, OSError):
        return False
    aliases = [_upper(a) for a in (rules.data.get("aliases") or []) if _upper(a)]
    aliases.append(_upper(rules.id))
    aliases.append(_upper(getattr(rules, "title", "") or ""))
    for alias in aliases:
        if not alias:
            continue
        if token == alias:
            return True
        if len(alias) >= 4 and alias in token:
            return True
        if len(token) >= 4 and token in alias:
            return True
    return False


def goal_title(goal: str, goal_id: str) -> str:
    if goal == "contest" and goal_id:
        try:
            from wims.engine.contest_rules import load_builtin
            return load_builtin(str(goal_id)).title
        except (KeyError, OSError):
            return "this contest"
    if goal == "award":
        return "this award"
    if goal == "custom":
        return "your list"
    return "Just operating"


def catalog_from_parts(
    *,
    contests: list[dict] | None = None,
    access: list[dict] | None = None,
    seed_paths: list[str] | None = None,
    gridtracker: list[dict] | None = None,
    shared_path: str = "",
) -> list[dict]:
    """Selectable logs. Counts are contacts in the file, before any time window."""
    options: list[dict] = []
    for contest in contests or []:
        path = str(contest.get("db_path") or "").strip()
        if not path:
            continue
        name = str(contest.get("contest_name") or "").strip() or "Contest"
        nr = contest.get("contest_nr")
        try:
            nr_i = int(nr) if nr is not None else 0
        except (TypeError, ValueError):
            nr_i = 0
        count = int(contest.get("qso_count") or 0)
        label = name
        db_label = str(contest.get("db_label") or "").strip()
        title = f"N1MM · {contest.get('label') or name}"
        if db_label and db_label not in title:
            title = f"{title} · {db_label}"
        options.append({
            "id": f"n1mm|{nr_i}|{path}",
            "kind": "n1mm",
            "path": path,
            "paths": [path],
            "label": label,
            "title": f"{title} · {count} contacts",
            "count": count,
            "file_count": count,
            "contest_nr": nr_i,
            "contest_name": name,
            "start_date": str(contest.get("start_date") or ""),
            "status": "ok" if count or path else "empty",
        })

    paths = [str(p) for p in (seed_paths or []) if str(p).strip()]
    counts: dict[str, int] = {}
    for row in access or []:
        if row.get("status") == "ok":
            counts[str(row.get("path") or "")] = int(row.get("count") or 0)
    total = 0
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        total += counts.get(path, 0)
    shared = (shared_path or "").strip()
    if shared and not paths:
        paths = [shared]
    ws_label = "WSJT-X shared log" if shared else "WSJT-X log"
    if len(paths) > 1 and not shared:
        ws_label = "WSJT-X logs"
    options.append({
        "id": "wsjtx",
        "kind": "wsjtx",
        "path": paths[0] if len(paths) == 1 else (shared or (paths[0] if paths else "")),
        "paths": list(paths),
        "label": ws_label,
        "title": f"{ws_label} · {total} contacts",
        "count": total,
        "file_count": total,
        "contest_nr": None,
        "contest_name": "",
        "start_date": "",
        "status": "ok" if paths else "missing",
    })

    for row in access or []:
        instance = str(row.get("instance") or "")
        if instance in {"", "shared", "shared log"}:
            continue
        path = str(row.get("path") or "")
        count = int(row.get("count") or 0)
        label = f"WSJT-X — {instance}"
        options.append({
            "id": f"adif|{path}",
            "kind": "adif",
            "path": path,
            "paths": [path] if path else [],
            "label": label,
            "title": f"{label} · {count} contacts",
            "count": count,
            "file_count": count,
            "contest_nr": None,
            "contest_name": "",
            "start_date": "",
            "status": str(row.get("status") or ""),
            "message": str(row.get("message") or ""),
        })

    for item in gridtracker or []:
        path = str(item.get("path") or "")
        if not path:
            continue
        count = int(item.get("count") or 0)
        name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        problem = str(item.get("problem") or "")
        label = f"GridTracker {name}"
        options.append({
            "id": f"gridtracker|{path}",
            "kind": "gridtracker",
            "path": path,
            "paths": [path],
            "label": label,
            "title": f"{label} · {count} contacts",
            "count": count,
            "file_count": count,
            "contest_nr": None,
            "contest_name": "",
            "start_date": "",
            "status": "unreadable" if problem else "ok",
            "message": problem,
        })
    return options


def resolve_use(
    logs: dict,
    *,
    goal: str,
    goal_id: str,
    catalog: list[dict],
) -> dict:
    """Pick the log. A saved choice wins. Otherwise the goal only suggests.

    Returns the chosen catalog row (or a stand-in when the file is gone),
    the plain reason, and whether the operator chose it.
    """
    logs = logs or {}
    explicit = bool(logs.get("explicit"))
    selection = logs.get("selection") if isinstance(logs.get("selection"), dict) else None
    primary = str(logs.get("primary") or "auto")
    title = goal_title(goal, goal_id)
    chosen = None
    why = ""
    if explicit and selection:
        chosen = _match(catalog, selection) or _phantom(selection)
        why = "You chose this log. It stays until you choose another."
    elif explicit and primary == "wsjtx":
        chosen = _by_id(catalog, "wsjtx") or _phantom({
            "id": "wsjtx",
            "kind": "wsjtx",
            "path": str(logs.get("shared_path") or ""),
            "label": "WSJT-X log",
        })
        why = "You chose the WSJT-X log. It stays until you choose another."
    elif explicit and primary == "n1mm" and not selection:
        pool = [o for o in catalog if o.get("kind") == "n1mm"]
        chosen = _newest(pool)
        if chosen:
            why = "You chose N1MM. This is the newest contest log."
        else:
            why = "You chose N1MM, but no contest log was found on this computer."
    else:
        explicit = False
        chosen, why = _suggest(goal, goal_id, catalog, title)
    return {
        "chosen": chosen,
        "why": why,
        "explicit": explicit,
        "goal": goal,
        "goal_id": goal_id,
        "goal_title": title,
    }


def _suggest(goal: str, goal_id: str, catalog: list[dict], title: str):
    if goal == "contest":
        matches = [
            o for o in catalog
            if o.get("kind") == "n1mm"
            and contest_name_matches(goal_id, str(o.get("contest_name") or ""))
        ]
        best = _newest(matches)
        if best:
            return best, (
                f"Suggested because the goal is {title}. "
                "This is the newest matching contest log."
            )
        return None, (
            f"No {title} log was found on this computer. "
            "Start a new log in N1MM or your logger, then choose it here. "
            "A leftover contest log is not used."
        )
    chosen = _by_id(catalog, "wsjtx")
    if chosen:
        return chosen, (
            f"Suggested because the goal is {title}. WSJT-X is the log."
        )
    return None, (
        "No WSJT-X log was found. WSJT-X creates that file when you log the first contact."
    )


def menu_options(catalog: list[dict], *, goal: str, goal_id: str) -> list[dict]:
    """Dropdown rows. Suggested stays first. Order follows the goal; every log stays listed."""
    rest = [o for o in catalog if o.get("id") != SUGGESTED_ID]
    if goal == "contest":
        matches, others = [], []
        for opt in rest:
            if opt.get("kind") == "n1mm" and contest_name_matches(
                goal_id, str(opt.get("contest_name") or ""),
            ):
                matches.append(opt)
            else:
                others.append(opt)
        matches.sort(key=_recency, reverse=True)
        ordered = matches + _casual_first(others)
    else:
        ordered = _casual_first(rest)
    rows = [{
        "id": SUGGESTED_ID,
        "title": "Suggested for this goal",
        "kind": "auto",
    }]
    for opt in ordered:
        rows.append({"id": opt.get("id") or "", "title": opt.get("title") or opt.get("label") or "Log"})
    return rows


def _casual_first(options: list[dict]) -> list[dict]:
    rank = {"wsjtx": 0, "adif": 1, "gridtracker": 2, "n1mm": 3}
    return sorted(options, key=lambda o: (rank.get(o.get("kind"), 9), _recency(o)[0] == "", str(o.get("title") or "")))


def cutoff_bounds(preset: str, *, now: datetime | None = None) -> tuple[str, str, str]:
    """``(cutoff id, count_since, count_until)``. Presets leave the end open."""
    if preset == "start_now":
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        stamp = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return "start_now", stamp, ""
    if preset == "this_year":
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local = moment.astimezone()
        start = local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        stamp = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return "this_year", stamp, ""
    return "whole", "", ""


def cutoff_phrase(since: str, until: str, cutoff: str) -> str:
    if cutoff == "whole" or (not since and not until):
        return "whole log"
    bits = []
    if since:
        bits.append("since " + pretty_time(since))
    if until:
        bits.append("through " + pretty_time(until))
    span = "contacts " + " ".join(bits) if bits else "whole log"
    if cutoff == "start_now":
        return "start now, " + span
    if cutoff == "this_year":
        return "this year, " + span
    return span


def pretty_time(stamp: str) -> str:
    dt = _parse_stamp(stamp)
    if dt is None:
        return stamp
    local = dt.astimezone()
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    if local.hour == 0 and local.minute == 0 and local.second == 0:
        return f"{months[local.month - 1]} {local.day}, {local.year}"
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{months[local.month - 1]} {local.day}, {local.year}, {hour}:{local.minute:02d} {ampm}"


def in_use_line(chosen: dict | None, count: int, phrase: str, *, file_count: int | None = None) -> str:
    if not chosen:
        return f"Log in use: no log yet, 0 contacts, {phrase}"
    name = chosen.get("label") or "Log"
    paths = [p for p in (chosen.get("paths") or []) if p]
    if not paths and chosen.get("path"):
        paths = [str(chosen["path"])]
    if len(paths) == 1:
        where = paths[0]
    elif len(paths) > 1:
        where = f"{len(paths)} files, including {paths[0]}"
    else:
        where = "no file yet"
    extra = ""
    if file_count is not None and file_count != count:
        extra = f" ({file_count} in the file)"
    return f"Log in use: {name}, {where}, {count} contacts{extra}, {phrase}"


def qso_epoch(qso) -> float | None:
    """UTC epoch for a log row, or None when the contact has no time."""
    if isinstance(qso, dict):
        qdate = qso.get("qso_date") or ""
        tim = qso.get("time_on") or ""
        ts = qso.get("timestamp") or ""
    else:
        qdate = getattr(qso, "qso_date", None) or ""
        tim = getattr(qso, "time_on", None) or ""
        ts = getattr(qso, "timestamp", None) or ""
    ep = _adif_epoch(str(qdate), str(tim))
    if ep is not None:
        return ep
    return _text_epoch(str(ts or ""))


def qso_in_window(qso, since: str, until: str) -> bool:
    """Needed/dupe sees this contact only inside the window.

    A contact with no time is kept when the window is open. When a start or
    end is set, an undated contact from a file does not count. A contact that
    just arrived on the air (source ``live``) with no clock counts as now.
    """
    if not since and not until:
        return True
    ep = qso_epoch(qso)
    if ep is None:
        source = qso.get("source") if isinstance(qso, dict) else getattr(qso, "source", "")
        if source == "live":
            ep = datetime.now(timezone.utc).timestamp()
        else:
            return False
    start = _parse_stamp(since)
    end = _parse_stamp(until)
    if start is not None and ep < start.timestamp():
        return False
    if end is not None and ep > end.timestamp():
        return False
    return True


def warnings_for(
    *,
    chosen: dict | None,
    qsos: list,
    problem: str | None,
    mtime: float | None,
    since: str,
    until: str,
    today,
    goal: str,
    why: str,
) -> tuple[list[dict], list[dict]]:
    """``(warnings, notes)``. Warnings are missing, unreadable, empty, or stale."""
    warns: list[dict] = []
    notes: list[dict] = []
    if chosen is None:
        warns.append({
            "level": "warn",
            "message": why or "No log is selected. Every station will look needed.",
        })
        return warns, notes
    kind = chosen.get("kind") or ""
    if problem in {"missing", "missing_file", "missing_dir"}:
        path = chosen.get("path") or "that folder"
        warns.append({
            "level": "warn",
            "message": (
                f"This log is missing ({path}). Connect the drive or choose another log. "
                "Every station will look needed."
            ),
        })
    elif problem in {"unreadable", "locked"}:
        path = chosen.get("path") or "that file"
        if problem == "locked":
            text = (
                f"WIMS cannot read this log because another program has it open ({path}). "
                "Contacts already logged in this session can still count. Older ones will be missing."
            )
        else:
            text = (
                f"WIMS cannot read this log ({path}). "
                "If it is on a shared drive, connect that drive, or choose another log."
            )
        warns.append({"level": "warn", "message": text})
    else:
        kept = [q for q in qsos if qso_in_window(q, since, until)]
        if not kept:
            if since:
                end = f" through {pretty_time(until)}" if until else ""
                warns.append({
                    "level": "warn",
                    "message": (
                        f"No contacts in this log since {pretty_time(since)}{end}. "
                        "Every station looks needed until you log one in that span."
                    ),
                })
            else:
                warns.append({
                    "level": "warn",
                    "message": "This log has no contacts. Every station will look needed.",
                })
        else:
            stale = _stale_message(qsos, mtime, today)
            if stale:
                warns.append({"level": "warn", "message": stale})
    if goal == "contest" and kind in {"wsjtx", "adif"}:
        notes.append({"level": "note", "message": WSJTX_CONTEST_NOTE})
    elif goal == "contest" and kind == "gridtracker":
        notes.append({
            "level": "note",
            "message": (
                "This GridTracker file may not include a contest name or an exchange. "
                "A county or section check needs those fields."
            ),
        })
    return warns, notes


def guidance_text(goal: str) -> str:
    parts = []
    if goal == "contest":
        parts.append(
            "A new contest needs a new log in N1MM or your other logger. "
            "WIMS reads that log and does not create it. When the new log appears, choose it here."
        )
    parts.append(
        "Whole log counts every contact. Start now counts only contacts you log after you pick it. "
        "This year counts contacts since January 1. Earlier contacts in the chosen log do not count."
    )
    return " ".join(parts)


def public_view(
    *,
    decision: dict,
    logs: dict,
    catalog: list[dict],
    qsos: list,
    problem: str | None,
    mtime: float | None,
    today,
) -> dict:
    chosen = decision.get("chosen")
    since = str(logs.get("count_since") or "")
    until = str(logs.get("count_until") or "")
    cutoff = str(logs.get("cutoff") or "whole")
    phrase = cutoff_phrase(since, until, cutoff)
    kept = [q for q in qsos if qso_in_window(q, since, until)] if chosen else []
    file_count = len(qsos) if chosen else 0
    if chosen and not qsos:
        file_count = int(chosen.get("file_count") or chosen.get("count") or 0)
    count = len(kept)
    goal = decision.get("goal") or "operating"
    options = menu_options(catalog, goal=goal, goal_id=decision.get("goal_id") or "")
    if decision.get("explicit") and chosen and chosen.get("id"):
        if not any(row.get("id") == chosen.get("id") for row in options):
            options.append({
                "id": chosen.get("id"),
                "title": chosen.get("title") or chosen.get("label") or "Chosen log",
            })
    cutoffs = list(CUTOFF_CHOICES)
    if cutoff == "custom":
        cutoffs.append({"id": "custom", "title": phrase})
    warns, notes = warnings_for(
        chosen=chosen, qsos=qsos, problem=problem, mtime=mtime,
        since=since, until=until, today=today, goal=goal,
        why=decision.get("why") or "",
    )
    paths = []
    if chosen:
        paths = [p for p in (chosen.get("paths") or []) if p]
        if not paths and chosen.get("path"):
            paths = [str(chosen["path"])]
    return {
        "line": in_use_line(
            chosen, count, phrase,
            file_count=file_count if phrase != "whole log" else None,
        ),
        "why": decision.get("why") or "",
        "name": (chosen or {}).get("label") or "",
        "path": paths[0] if len(paths) == 1 else "",
        "paths": paths,
        "count": count,
        "file_count": file_count,
        "cutoff": cutoff if cutoff in {"whole", "start_now", "this_year", "custom"} else "custom",
        "cutoff_label": phrase,
        "count_since": since,
        "count_until": until,
        "explicit": bool(decision.get("explicit")),
        "selected_id": (chosen or {}).get("id") or "" if decision.get("explicit") else SUGGESTED_ID,
        "kind": (chosen or {}).get("kind") or "",
        "warnings": warns,
        "notes": notes,
        "guidance": guidance_text(goal),
        "options": options,
        "cutoffs": cutoffs,
        "shared_path": str(logs.get("shared_path") or ""),
    }


def selection_record(chosen: dict) -> dict:
    return {
        "id": chosen.get("id") or "",
        "kind": chosen.get("kind") or "",
        "path": chosen.get("path") or "",
        "label": chosen.get("label") or "",
        "contest_nr": chosen.get("contest_nr"),
        "contest_name": chosen.get("contest_name") or "",
    }


def _match(catalog: list[dict], selection: dict) -> dict | None:
    ident = str(selection.get("id") or "")
    if ident:
        found = _by_id(catalog, ident)
        if found:
            return found
    kind = selection.get("kind")
    path = str(selection.get("path") or "")
    nr = selection.get("contest_nr")
    for opt in catalog:
        if opt.get("kind") != kind:
            continue
        if path and str(opt.get("path") or "") != path and path not in (opt.get("paths") or []):
            continue
        if kind == "n1mm" and nr is not None and opt.get("contest_nr") != nr:
            continue
        if path or kind == "wsjtx":
            return opt
    return None


def _phantom(selection: dict) -> dict:
    path = str(selection.get("path") or "")
    return {
        "id": selection.get("id") or "",
        "kind": selection.get("kind") or "adif",
        "path": path,
        "paths": [path] if path else [],
        "label": selection.get("label") or "Chosen log",
        "title": selection.get("label") or "Chosen log",
        "count": 0,
        "file_count": 0,
        "contest_nr": selection.get("contest_nr"),
        "contest_name": selection.get("contest_name") or "",
        "start_date": "",
        "status": "missing",
        "missing": True,
    }


def _by_id(catalog: list[dict], ident: str) -> dict | None:
    for opt in catalog:
        if opt.get("id") == ident:
            return opt
    return None


def _newest(options: list[dict]) -> dict | None:
    if not options:
        return None
    return max(options, key=_recency)


def _recency(opt: dict):
    sd = str(opt.get("start_date") or "").strip()
    if not sd or sd.startswith("1900"):
        sd = ""
    return (sd, int(opt.get("file_count") or opt.get("count") or 0))


def _stale_message(qsos: list, mtime: float | None, today) -> str:
    epochs = [ep for ep in (qso_epoch(q) for q in qsos) if ep is not None]
    if epochs:
        newest = max(epochs)
        day = datetime.fromtimestamp(newest, timezone.utc).astimezone().date()
        if day < today:
            shown = _day_text(day)
            return (
                f"The newest contact in this log is from {shown}, "
                "before today's operating session. "
                "If this is the wrong log, choose another one."
            )
        return ""
    if mtime:
        day = datetime.fromtimestamp(mtime, timezone.utc).astimezone().date()
        if day < today:
            shown = _day_text(day)
            return (
                f"This log was last changed on {shown}, before today's operating session. "
                "If this is the wrong log, choose another one."
            )
    return ""


def _day_text(day) -> str:
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{months[day.month - 1]} {day.day}, {day.year}"


def _upper(value) -> str:
    return str(value or "").strip().upper()


def _adif_epoch(qdate: str, tim: str) -> float | None:
    d = (qdate or "").strip()
    t = (tim or "").strip().replace(":", "")
    if len(t) == 4:
        t += "00"
    if len(d) < 8 or len(t) < 6:
        return None
    try:
        dt = datetime.strptime(d[:8] + t[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.timestamp()


def _text_epoch(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw or raw == "?":
        return None
    if raw.endswith("Z"):
        raw = raw[:-1]
    raw = raw.replace("T", " ")
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            dt = datetime.strptime(raw[:size], fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return None


def _parse_stamp(stamp: str) -> datetime | None:
    raw = (stamp or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1]
    raw = raw.replace("T", " ")
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)
