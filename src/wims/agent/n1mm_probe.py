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

"""Best-effort N1MM Logger+ config / presence probe (Windows + portable paths).

N1MM does not publish a stable documented settings schema for Broadcast Data.
Database location is often **not** Documents\\N1MM Logger+\\Databases — many
installs set UserDir (registry / portable layout) so contest .s3db files live
in ``{UserDir}\\Databases`` (e.g. C:\\Users\\…\\Databases\\N2OY.s3db).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _win_user_dir() -> Path | None:
    """N1MM Logger+ UserDir from HKCU (where Databases / ini actually live)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    for key_path in (
        r"Software\N1MM Logger+",
        r"Software\N1MM Logger",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                val, _ = winreg.QueryValueEx(k, "UserDir")
            if val:
                p = Path(str(val))
                if p.is_dir():
                    return p
        except OSError:
            continue
    return None


def n1mm_user_dirs() -> list[Path]:
    """N1MM UserDir and Documents trees (not the entire user profile).

    UserDir itself is the N1MM data root (ini + Databases live under it) when set
    via registry. We do **not** treat plain HOME as a scan root for recursive
    walks — only explicit N1MM subfolders and UserDir.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp in seen or not p.is_dir():
            return
        seen.add(rp)
        found.append(p)

    add(_win_user_dir())

    home = Path.home()
    for name in ("N1MM Logger+", "N1MM Logger", "N1MMLogger+"):
        add(home / "Documents" / name)
        add(home / "OneDrive" / "Documents" / name)

    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if not base:
            continue
        for name in ("N1MM Logger+", "N1MM Logger"):
            add(Path(base) / "Documents" / name)
            add(Path(base) / "OneDrive" / "Documents" / name)

    return found

def documents_n1mm_roots() -> list[Path]:
    """Backward-compatible alias: N1MM document/user roots (not only Documents)."""
    return n1mm_user_dirs()


def database_dirs() -> list[Path]:
    """All candidate Databases folders that exist on this host.

    Same multi-path scan the server uses for log seed (registry UserDir\\Databases,
    Documents, OneDrive, profile Databases).
    """
    from wims.integrations.n1mm.logdb import candidate_database_dirs
    return candidate_database_dirs()

def databases_dir() -> Path | None:
    """Primary Databases folder (first found). Prefer UserDir\\Databases."""
    dirs = database_dirs()
    return dirs[0] if dirs else None


def _list_s3db(db_dir: Path) -> list[dict]:
    """List contest-ish .s3db files in a Databases folder."""
    out: list[dict] = []
    try:
        paths = sorted(db_dir.glob("*.s3db"))
    except OSError:
        return out

    # N1MM app-wide DBs that are not the operator contest log.
    skip = {
        "n1mm admin.s3db",
        "n1mm dxlog.s3db",
        "n1mm packet spots.s3db",
        "admin.s3db",
        "dxlog.s3db",
        "packet spots.s3db",
        "ham.s3db",
    }

    for p in paths[:40]:
        name = p.name
        low = name.lower()
        kind = "contest"
        if low in skip or low.startswith("n1mm admin") or low.startswith("n1mm packet"):
            kind = "system"
        elif low.startswith("n1mm dxlog"):
            kind = "system"
        # WAL present often means N1MM has (or recently had) the DB open.
        wal = p.with_name(p.name + "-wal")
        wal_bytes = 0
        try:
            if wal.is_file():
                wal_bytes = wal.stat().st_size
        except OSError:
            pass
        try:
            mtime = p.stat().st_mtime
            size = p.stat().st_size
        except OSError:
            mtime = None
            size = None
        out.append({
            "name": name,
            "path": str(p),
            "kind": kind,
            "size": size,
            "mtime": mtime,
            "wal_bytes": wal_bytes,
            "likely_open": bool(wal_bytes and wal_bytes > 0),
        })
    return out


def _scan_ini_hints(path: Path, limit: int = 40) -> list[str]:
    """Return short lines that look like networking / broadcast settings."""
    hints: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hints
    keys = re.compile(
        r"(broadcast|udp|12060|wsjt|jtdx|multicast|224\.0\.|external)",
        re.I,
    )
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if keys.search(line):
            hints.append(line[:160])
            if len(hints) >= limit:
                break
    return hints


def _find_ini_files(roots: list[Path]) -> list[Path]:
    """Locate N1MM Logger.ini (UserDir root and N1MM Documents trees only)."""
    found: list[Path] = []
    seen: set[Path] = set()
    names = (
        "N1MM Logger.ini",
        "n1mm logger.ini",
        "N1MMLogger.ini",
    )

    def add_file(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if p.is_file() and rp not in seen:
            seen.add(rp)
            found.append(p)

    # UserDir: ini sits next to Databases\, not under Documents.
    ud = _win_user_dir()
    if ud is not None:
        for name in names:
            add_file(ud / name)

    home = Path.home()
    for name in names:
        add_file(home / name)

    for root in roots:
        for name in names:
            add_file(root / name)
        # Shallow scan only under folders that look like N1MM docs (not whole profile).
        try:
            if "n1mm" not in str(root).lower() and root != ud:
                continue
            for p in root.rglob("*.ini"):
                if len(found) >= 40:
                    return found
                if p.stat().st_size > 2_000_000:
                    continue
                low = p.name.lower()
                if "n1mm" in low or "logger" in low:
                    add_file(p)
        except OSError:
            continue
    return found

def probe_n1mm() -> dict:
    """Structured N1MM presence + config hints for the agent report."""
    roots = n1mm_user_dirs()
    user_dir = _win_user_dir()
    db_dirs = database_dirs()
    primary_db = db_dirs[0] if db_dirs else None

    s3db_entries: list[dict] = []
    for d in db_dirs:
        s3db_entries.extend(_list_s3db(d))

    contest_dbs = [e for e in s3db_entries if e.get("kind") == "contest"]
    openish = [e for e in s3db_entries if e.get("likely_open")]
    # Prefer contest DBs that look open (WAL) for the headline.
    open_contest = [e for e in openish if e.get("kind") == "contest"]

    ini_files: list[dict] = []
    all_hints: list[str] = []
    for p in _find_ini_files(roots):
        hints = _scan_ini_hints(p)
        if hints:
            ini_files.append({"path": str(p), "hints": hints[:15]})
            all_hints.extend(hints[:5])
        elif p.name.lower().startswith("n1mm"):
            ini_files.append({"path": str(p), "hints": []})

    issues: list[dict] = []
    if not roots and not db_dirs:
        issues.append({
            "severity": "warn",
            "message": (
                "N1MM Logger+ user data not found — if N1MM is installed "
                "elsewhere, configure Broadcast Data manually "
                "(Config -> Configure Ports -> Broadcast Data)"
            ),
        })
    else:
        where = str(user_dir) if user_dir else (str(roots[0]) if roots else "?")
        issues.append({
            "severity": "info",
            "message": (
                f"N1MM user data under {where} — verify Broadcast Data "
                "sends Contacts + Radio to WIMS host or 224.0.0.73:12060 "
                "(default 127.0.0.1 stays local-only)"
            ),
        })

    if not db_dirs:
        issues.append({
            "severity": "warn",
            "message": (
                "No N1MM Databases folder found (checked UserDir\\Databases and "
                "Documents\\N1MM Logger+\\Databases). Open a contest log in N1MM "
                "or set File locations so .s3db files are visible."
            ),
        })
    elif not contest_dbs:
        issues.append({
            "severity": "info",
            "message": (
                f"Databases folder(s) found but no contest .s3db yet "
                f"({', '.join(str(d) for d in db_dirs)}) — create/open a contest in N1MM"
            ),
        })
    else:
        names = ", ".join(e["name"] for e in contest_dbs[:8])
        msg = f"Contest database(s): {names}"
        if open_contest:
            msg += f" · likely open: {', '.join(e['name'] for e in open_contest[:4])} (WAL active)"
        issues.append({"severity": "info", "message": msg})

    # Heuristic: loopback broadcast mentions
    for h in all_hints:
        if re.search(r"127\.0\.0\.1|localhost", h, re.I) and re.search(r"12060|broadcast|udp", h, re.I):
            issues.append({
                "severity": "warn",
                "message": (
                    "Config text mentions 127.0.0.1 with broadcast/UDP — multi-host WIMS "
                    "needs External Broadcast to the WIMS host or 224.0.0.73:12060"
                ),
            })
            break

    # Flat name list for older UI / summary
    s3db_names = [e["name"] for e in contest_dbs]
    if not s3db_names:
        s3db_names = [e["name"] for e in s3db_entries if e.get("kind") != "system"]

    return {
        "found": bool(roots or db_dirs),
        "user_dir": str(user_dir) if user_dir else None,
        "roots": [str(r) for r in roots],
        "databases_dir": str(primary_db) if primary_db else None,
        "databases_dirs": [str(d) for d in db_dirs],
        "s3db_files": s3db_names,
        "s3db": s3db_entries,
        "open_databases": [e["name"] for e in openish],
        "ini_files": ini_files,
        "issues": issues,
    }
