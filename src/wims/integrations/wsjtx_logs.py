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

"""Find each WSJT-X instance's ``wsjtx_log.adi`` and say when it cannot be read.

Log discovery does not reuse ``wsjtx_config.discover_ini_paths``. That glob
misses sibling ``WSJT-X - NAME`` data directories. This module only reads.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from wims.adif import load_qsos


def data_home() -> Path:
    if sys.platform == "win32":
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            return Path(local)
        return Path.home() / "AppData" / "Local"
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def config_home() -> Path:
    if sys.platform == "win32":
        return data_home()
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg)
    return Path.home() / ".config"


def app_name(udp_id: str | None) -> str:
    """``WSJT-X`` or ``WSJT-X - NAME`` for a UDP id / rig-name."""
    s = (udp_id or "").strip()
    if s in {"", "WSJT-X", "(active/default)"}:
        return "WSJT-X"
    if s.startswith("WSJT-X - "):
        return s
    return f"WSJT-X - {s}"


def instance_dir(udp_id: str | None, *, home: Path | None = None) -> Path:
    return (home or data_home()) / app_name(udp_id)


def adi_path(udp_id: str | None, *, home: Path | None = None) -> Path:
    return instance_dir(udp_id, home=home) / "wsjtx_log.adi"


def ini_path(udp_id: str | None, *, home: Path | None = None,
             config: Path | None = None) -> Path:
    app = app_name(udp_id)
    if sys.platform == "win32":
        return instance_dir(udp_id, home=home) / "WSJT-X.ini"
    base = config or config_home()
    if app == "WSJT-X":
        return base / "WSJT-X.ini"
    return base / f"{app}.ini"


def installed_dirs(home: Path | None = None) -> list[Path]:
    root = home or data_home()
    if not root.is_dir():
        return []
    found = []
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if child.name == "WSJT-X" or child.name.startswith("WSJT-X - "):
                found.append(child)
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name.lower())


def _id_from_dir(path: Path) -> str:
    name = path.name
    if name == "WSJT-X":
        return "WSJT-X"
    if name.startswith("WSJT-X - "):
        return name[len("WSJT-X - "):]
    return name


@dataclass
class LogAccess:
    instance: str
    path: str
    status: str
    message: str
    count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def assess(instance: str, path: Path) -> LogAccess:
    """One of the section 4.3 sentences."""
    parent = path.parent
    shown = str(path)
    try:
        parent_ok = parent.is_dir()
    except OSError:
        return LogAccess(
            instance, shown, "unreadable",
            f"The log for {instance} is not readable ({shown}). "
            "If this file is on a shared drive, connect that drive. "
            "Dupe checking is incomplete.",
        )
    if not parent_ok:
        return LogAccess(
            instance, str(parent), "missing_dir",
            f"WIMS hears {instance} but cannot find its WSJT-X folder ({parent}). "
            "Contacts from this radio will be missing from dupe checking. "
            "Set the log file under Setup → Logs.",
        )
    try:
        exists = path.is_file()
    except OSError:
        return LogAccess(
            instance, shown, "unreadable",
            f"The log for {instance} is not readable ({shown}). "
            "If this file is on a shared drive, connect that drive. "
            "Dupe checking is incomplete.",
        )
    if not exists:
        return LogAccess(
            instance, shown, "missing_file",
            f"{instance} has no wsjtx_log.adi yet. WSJT-X creates that file when "
            "you log the first contact. Until then, stations on this radio look needed.",
        )
    qsos, problem = load_qsos(path)
    if problem == "locked":
        return LogAccess(
            instance, shown, "locked",
            f"WSJT-X has {shown} open so WIMS cannot read it. WIMS will use contacts "
            "logged while WIMS is running, and will miss older ones.",
        )
    if problem:
        return LogAccess(
            instance, shown, "unreadable",
            f"The log for {instance} is not readable ({shown}). "
            "If this file is on a shared drive, connect that drive. "
            "Dupe checking is incomplete.",
        )
    n = len(qsos)
    return LogAccess(
        instance, shown, "ok",
        f"{instance}: {shown} ({n} contacts).",
        count=n,
    )


def discover_access(
    heard_ids: list[str] | None = None,
    *,
    home: Path | None = None,
    logs: dict | None = None,
) -> list[LogAccess]:
    """Per-instance access, plus a shared-file row when one path is configured.

    ``heard_ids`` are UDP ids. Installed data directories are always listed so
    a rig that is not on the air yet still shows up. A shared path replaces
    per-instance files as the log WIMS reads; the per-instance rows stay so
    the operator can see each radio.
    """
    logs = logs or {}
    overrides = logs.get("overrides") or {}
    rows: list[LogAccess] = []
    seen: set[str] = set()

    def add(instance: str, path: Path) -> None:
        key = f"{instance}|{path}"
        if key in seen:
            return
        seen.add(key)
        rows.append(assess(instance, path))

    ids = []
    for raw in heard_ids or []:
        if raw and raw not in ids:
            ids.append(raw)
    for folder in installed_dirs(home):
        ident = _id_from_dir(folder)
        if ident not in ids:
            ids.append(ident)
    if not ids:
        ids = ["WSJT-X"]
    for ident in ids:
        override = (overrides.get(ident) or "").strip()
        path = Path(override) if override else adi_path(ident, home=home)
        add(ident, path)

    shared = (logs.get("shared_path") or "").strip()
    if shared:
        add("shared log", Path(shared))

    # Two rigs, one resolved file.
    ok_paths: dict[str, list[str]] = {}
    for row in rows:
        if row.status != "ok":
            continue
        try:
            real = str(Path(row.path).resolve())
        except OSError:
            real = row.path
        ok_paths.setdefault(real, []).append(row.instance)
    for real, names in ok_paths.items():
        names = [n for n in names if n != "shared log"]
        if len(names) >= 2:
            label = " and ".join(names)
            rows.append(LogAccess(
                "shared",
                real,
                "ok",
                f"{label} write the same log file. WIMS counts each contact once.",
            ))
    return rows


def seed_files(
    heard_ids: list[str] | None = None,
    *,
    home: Path | None = None,
    logs: dict | None = None,
) -> list[Path]:
    """Files the log copy should read. A shared path is the only file."""
    logs = logs or {}
    shared = (logs.get("shared_path") or "").strip()
    if shared:
        return [Path(shared)]
    files: list[Path] = []
    seen: set[str] = set()
    for row in discover_access(heard_ids, home=home, logs=logs):
        if row.status != "ok" or row.instance == "shared":
            continue
        try:
            real = str(Path(row.path).resolve())
        except OSError:
            real = row.path
        if real in seen:
            continue
        seen.add(real)
        files.append(Path(row.path))
    return files


def gridtracker_dirs() -> list[Path]:
    roots = []
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        roots.append(base / "GridTracker2")
    else:
        roots.append(Path.home() / ".config" / "GridTracker2")
        roots.append(Path.home() / ".local" / "share" / "GridTracker2")
    return roots


def discover_gridtracker_adif(extra: list[str] | None = None) -> list[Path]:
    """``*.adi`` / ``*.adif`` under GridTracker folders. Filename is not fixed."""
    found: list[Path] = []
    seen: set[str] = set()

    def take(path: Path) -> None:
        if path.suffix.lower() not in {".adi", ".adif"}:
            return
        try:
            if not path.is_file():
                return
            key = str(path.resolve())
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for raw in extra or []:
        if raw:
            take(Path(raw))
    for root in gridtracker_dirs():
        if not root.is_dir():
            continue
        # Stay shallow. A Chromium profile can be huge; LevelDB is out of scope.
        try:
            for path in root.glob("*.adi"):
                take(path)
            for path in root.glob("*.adif"):
                take(path)
            for child in root.iterdir():
                if not child.is_dir() or child.name in {"Cache", "GPUCache", "Code Cache"}:
                    continue
                for path in child.glob("*.adi"):
                    take(path)
                for path in child.glob("*.adif"):
                    take(path)
        except OSError:
            continue
        if len(found) >= 40:
            break
    return found
