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

"""LoTW confirmations GridTracker already downloaded.

GridTracker 2 keeps ``LoTW_QSL.adif`` under its config folder. GridTracker 1
kept ``LogbookOfTheWorld.adif`` in Documents. WIMS finds those files on its
own. The newest file is the one that counts. This module only reads. It
never writes a LoTW file and it never downloads one.

A logged contact is confirmed when a record matches the call, the band, the
LoTW mode group, and the start time within 30 minutes. FT8, DATA, and MFSK
are the same group. The grid, state, and DXCC entity on the record also
count as confirmed for that place.
"""

from __future__ import annotations

import bisect
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from wims.adif import band_of, mode_of, qso_time, read_text
from wims.rules.places import canonical_place

# LoTW matches two QSO descriptions when the start times are within 30 minutes.
TIME_WINDOW_S = 30 * 60

_NOT_FOUND = "LoTW confirmations: not found"
_UNREADABLE = "LoTW confirmations: from GridTracker, but the file could not be read"

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

# Mode groups from TQSL configuration data (LoTW key concepts). Exact modes
# match too. An unknown mode matches only itself, so a future mode is not
# folded into DATA by accident.
_PHONE = (
    "AM", "C4FM", "DIGITALVOICE", "DSTAR", "FM", "FREEDV", "LSB", "PHONE", "SSB", "USB",
)
_IMAGE = ("ATV", "FAX", "IMAGE", "SSTV")
_DATA = (
    "AMTOR", "ARDOP", "CHIP", "CLOVER", "CONTESTI", "DATA", "DOMINO", "FSK31",
    "FSK441", "FST4", "FST4W", "FT4", "FT8", "GTOR", "HELL", "HFSK", "ISCAT",
    "JS8", "JT4", "JT6M", "JT65", "JT9", "MFSK", "MFSK16", "MFSK8", "MINIRTTY",
    "MSK144", "MT63", "OLIVIA", "OPERA", "PACKET", "PACTOR", "PAX", "PSK",
    "PSK10", "PSK125", "PSK2K", "PSK31", "PSK63", "PSK63F", "PSKAM", "PSKFEC31",
    "Q15", "Q65", "QRA64", "ROS", "RTTY", "RTTYM", "T10", "THOR", "THROB",
    "VARA", "VARAC", "VOI", "WINMOR", "WSPR",
)

_MODE_GROUP: dict[str, str] = {}
for _mode in _PHONE:
    _MODE_GROUP[_mode] = "PHONE"
_MODE_GROUP["CW"] = "CW"
for _mode in _IMAGE:
    _MODE_GROUP[_mode] = "IMAGE"
for _mode in _DATA:
    _MODE_GROUP[_mode] = "DATA"

_GROUP_MODES: dict[str, frozenset[str]] = {}
for _mode, _group in _MODE_GROUP.items():
    _GROUP_MODES.setdefault(_group, set()).add(_mode)
_GROUP_MODES = {key: frozenset(val) for key, val in _GROUP_MODES.items()}

_override_on = False
_override_paths: list[Path] | None = None
_cache: tuple | None = None
_lock = threading.Lock()


class LotwQso:
    """One confirmation record. ``when`` is a UTC epoch, or None if the time is missing."""

    __slots__ = ("call", "band", "mode", "group", "when", "grid", "state", "dxcc")

    def __init__(self, call, band, mode, group, when, grid, state, dxcc):
        self.call = call
        self.band = band
        self.mode = mode
        self.group = group
        self.when = when
        self.grid = grid
        self.state = state
        self.dxcc = dxcc


class LotwIndex:
    """The file in use, or a not-found result. Safe to keep and reuse."""

    def __init__(self, *, found, line, updated, count, path, token, problem,
                 records, times):
        self.found = found
        self.line = line
        self.updated = updated
        self.count = count
        self.path = path
        self.token = token
        self.problem = problem
        self.records = records
        self._times = times

    def confirms(self, call: str, band: str, mode: str, when: float | None) -> bool:
        """True when a record matches this contact inside the LoTW time window."""
        if when is None or not self._times:
            return False
        call_u = (call or "").strip().upper()
        band_u = (band or "").strip().lower()
        group = mode_group(mode)
        if not call_u or not band_u or not group:
            return False
        epochs = self._times.get((call_u, band_u, group))
        if not epochs:
            return False
        lo = when - TIME_WINDOW_S
        i = bisect.bisect_left(epochs, lo)
        return i < len(epochs) and epochs[i] <= when + TIME_WINDOW_S

    def confirms_row(self, row: dict | None) -> bool:
        """True when this log-copy row matches a LoTW record."""
        if not row or not self._times:
            return False
        return self.confirms(
            str(row.get("call") or ""),
            str(row.get("band") or ""),
            str(row.get("submode") or row.get("mode") or ""),
            row_epoch(row),
        )


_EMPTY = LotwIndex(
    found=False, line=_NOT_FOUND, updated="", count=0, path="",
    token=("", 0, 0), problem="", records=(), times={},
)


def mode_group(mode: str | None) -> str:
    """LoTW mode group. An unknown mode is its own group."""
    name = (mode or "").strip().upper()
    if not name:
        return ""
    return _MODE_GROUP.get(name, name)


def modes_in_group(group: str | None) -> frozenset[str]:
    """Every mode LoTW treats as that group, including the group name itself."""
    name = (group or "").strip().upper()
    found = _GROUP_MODES.get(name)
    if found:
        return found
    if name:
        return frozenset((name,))
    return frozenset()


def format_updated(when: datetime) -> str:
    """Local time as ``Oct 21, 2026, 1:54 AM``. English month names, no locale."""
    hour = when.hour % 12 or 12
    ampm = "AM" if when.hour < 12 else "PM"
    return f"{_MONTHS[when.month - 1]} {when.day}, {when.year}, {hour}:{when.minute:02d} {ampm}"


def candidate_paths(home: Path, *, platform: str, environ: dict | None = None) -> list[Path]:
    """Files WIMS looks for. Missing files stay in the list; the caller skips them.

    No flag and no WIMS setting. ``APPDATA`` and ``XDG_CONFIG_HOME`` are the
    platform folders those programs already use, not a WIMS option.
    """
    env = environ if environ is not None else {}
    paths: list[Path] = []
    system = (platform or "").lower()
    if system.startswith("win"):
        appdata = (env.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        paths.append(base / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif")
        paths.append(home / "Documents" / "GridTracker" / "LogbookOfTheWorld.adif")
        paths.append(home / "OneDrive" / "Documents" / "GridTracker" / "LogbookOfTheWorld.adif")
    else:
        xdg = (env.get("XDG_CONFIG_HOME") or "").strip()
        if xdg:
            paths.append(Path(xdg) / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif")
        paths.append(home / ".config" / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif")
        if system == "darwin":
            paths.append(
                home / "Library" / "Application Support" / "GridTracker2"
                / "Ginternal" / "LoTW_QSL.adif"
            )
        else:
            paths.append(home / ".local" / "share" / "GridTracker2" / "Ginternal" / "LoTW_QSL.adif")
        paths.append(home / "Documents" / "GridTracker" / "LogbookOfTheWorld.adif")
    return _dedupe(paths)


def use_paths(paths: list[Path] | None) -> None:
    """Tests point discovery at these files. ``None`` restores this PC."""
    global _override_on, _override_paths, _cache
    with _lock:
        if paths is None:
            _override_on = False
            _override_paths = None
        else:
            _override_on = True
            _override_paths = list(paths)
        _cache = None


def current() -> LotwIndex:
    """The newest LoTW file, re-read when its modified time or size changes."""
    global _cache
    with _lock:
        chosen = _newest(_discover_locked())
        if chosen is None:
            _cache = ("", 0, 0, _EMPTY)
            return _EMPTY
        try:
            st = chosen.stat()
        except OSError:
            idx = _unreadable(chosen, ("", 0, 0))
            _cache = (*idx.token, idx)
            return idx
        token = (str(chosen), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), int(st.st_size))
        if _cache is not None and _cache[:3] == token:
            return _cache[3]
        idx = _load(chosen, token, st.st_mtime)
        _cache = (*token, idx)
        return idx


def status_public() -> dict:
    """Setup sentence. The path stays off this dict; the sentence is the source."""
    idx = current()
    return {
        "line": idx.line,
        "found": bool(idx.found and not idx.problem),
        "updated": idx.updated,
        "count": idx.count,
    }


def row_epoch(row: dict) -> float | None:
    """UTC epoch from ``QSO_DATE`` + ``TIME_ON``, else a ``YYYY-MM-DD HH:MM:SS`` timestamp."""
    _text, epoch = qso_time({
        "qso_date": str(row.get("qso_date") or ""),
        "time_on": str(row.get("time_on") or ""),
    })
    if epoch is not None:
        return epoch
    ts = str(row.get("timestamp") or "").strip()
    if len(ts) < 19:
        return None
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.timestamp()


def _discover_locked() -> list[Path]:
    if _override_on:
        return list(_override_paths or [])
    return candidate_paths(Path.home(), platform=sys.platform, environ=os.environ)


def _dedupe(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _newest(paths: list[Path]) -> Path | None:
    """Newest modified time. An equal time keeps the earlier candidate (GridTracker 2 first)."""
    best: tuple[int, int, Path] | None = None
    for i, path in enumerate(paths):
        try:
            if not path.is_file():
                continue
            st = path.stat()
        except OSError:
            continue
        mtime = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        # Smaller index wins a tie, so negate it under a reverse-style compare.
        rank = (mtime, -i)
        if best is None or rank > (best[0], best[1]):
            best = (mtime, -i, path)
    return None if best is None else best[2]


def _unreadable(path: Path, token: tuple) -> LotwIndex:
    return LotwIndex(
        found=True, line=_UNREADABLE, updated="", count=0, path=str(path),
        token=token, problem="unreadable", records=(), times={},
    )


def _load(path: Path, token: tuple, mtime: float) -> LotwIndex:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _unreadable(path, token)
    try:
        records = read_text(text)
    except Exception:
        return _unreadable(path, token)
    parsed = tuple(q for q in (_qso(rec) for rec in records) if q is not None)
    if not parsed and not _looks_like_adif(text):
        return _unreadable(path, token)
    times: dict[tuple[str, str, str], list[float]] = {}
    for qso in parsed:
        if qso.when is None or not qso.band or not qso.group:
            continue
        times.setdefault((qso.call, qso.band, qso.group), []).append(qso.when)
    for epochs in times.values():
        epochs.sort()
    updated = format_updated(datetime.fromtimestamp(mtime))
    return LotwIndex(
        found=True,
        line=f"LoTW confirmations: from GridTracker, updated {updated}",
        updated=updated,
        count=len(parsed),
        path=str(path),
        token=token,
        problem="",
        records=parsed,
        times=times,
    )


def _looks_like_adif(text: str) -> bool:
    low = text.lower()
    return "<eoh" in low or "<eor" in low


def _grid4(value: str | None) -> str | None:
    g = (value or "").strip().upper()
    if len(g) >= 4 and g[:2].isalpha() and g[2:4].isdigit():
        return g[:4]
    return None


def _dxcc(value: str | None) -> str | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.isdigit():
        return str(int(s))
    return s.upper()


def _qso(fields: dict) -> LotwQso | None:
    call = (fields.get("call") or "").strip().upper()
    if not call:
        return None
    mode = mode_of(fields)
    _text, when = qso_time(fields)
    band = band_of(fields)
    if band == "?":
        band = ""
    return LotwQso(
        call=call,
        band=band,
        mode=mode,
        group=mode_group(mode),
        when=when,
        grid=_grid4(fields.get("gridsquare")),
        state=canonical_place(fields.get("state")),
        dxcc=_dxcc(fields.get("dxcc")),
    )
