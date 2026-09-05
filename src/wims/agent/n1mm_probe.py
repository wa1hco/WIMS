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
import subprocess
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

    Prefer paths under agent-visible N1MM roots (registry UserDir, Documents,
    …) so a monkeypatched or portable UserDir is enough for the seat probe.
    Then merge the shared server scan (logdb.candidate_database_dirs) so the
    agent and log seed still see the same real-machine locations.
    """
    from wims.integrations.n1mm.logdb import candidate_database_dirs

    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            if not p.is_dir():
                return
            rp = p.resolve()
        except OSError:
            return
        if rp in seen:
            return
        seen.add(rp)
        found.append(p)

    # Agent UserDir / Documents roots first (testable; matches seat layout).
    for root in n1mm_user_dirs():
        add(root / "Databases")
    # Shared host scan used by server log seed (may add more, e.g. HOME/Databases).
    for d in candidate_database_dirs():
        add(d)
    return found

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

# Default fleet plane A is 2237 only; keep legacy ports as "known" for audits.
_FLEET_UDP_PORTS = frozenset({2237, 2238, 2239, 2241, 2242, 2243})


def _ini_truthy(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _parse_wsjt_udp_reader_from_ini(text: str) -> list[dict]:
    """Extract WSJT/JTDX UDP reader enable/IP/port from N1MM Logger.ini text.

    Keys live under [ExternalProgramInput] (documented in wims_networking.md §4.9):
    EnableWSJTJTDXUDPReader / Reader2, WSJTJTDXUDPIP / IP2, WSJTJTDXUDPPort / Port2.
    """
    # Flatten key=value ignoring sections (keys are unique enough).
    kv: dict[str, str] = {}
    raw_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip().lower()
        val = v.strip()
        kv[key] = val
        if "wsjt" in key and "udp" in key:
            raw_lines.append(f"{k.strip()}={val}")

    out: list[dict] = []
    for suffix, label in (("", "Radio1"), ("2", "Radio2")):
        en_key = f"enablewsjtjtdxudpreader{suffix}"
        ip_key = f"wsjtjtdxudpip{suffix}"
        port_key = f"wsjtjtdxudpport{suffix}"
        if suffix == "2" and en_key not in kv and ip_key not in kv and port_key not in kv:
            continue
        enabled = _ini_truthy(kv.get(en_key)) if en_key in kv else False
        ip = kv.get(ip_key)
        port_raw = kv.get(port_key)
        port: int | None = None
        if port_raw:
            try:
                port = int(str(port_raw).strip())
            except ValueError:
                port = None
        # When enabled and port omitted, N1MM historically defaults to 2237.
        if enabled and port is None:
            port = 2237
        out.append({
            "radio": label,
            "enabled": enabled,
            "ip": ip,
            "port": port,
            "key_present": en_key in kv,
            "enable_raw": kv.get(en_key),
        })
    # Attach raw_lines on first row for diagnostics (avoid changing return type).
    if out:
        out[0] = {**out[0], "raw_lines": raw_lines[:12]}
    return out


def _n1mm_pids() -> set[int]:
    """PIDs whose image name looks like N1MM Logger+."""
    pids: set[int] = set()
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in out.splitlines():
                low = line.lower()
                if "n1mmlogger" not in low:
                    continue
                # "N1MMLogger.net.exe","1234",...
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 2 and parts[1].isdigit():
                    pids.add(int(parts[1]))
        else:
            out = subprocess.check_output(
                ["ps", "-eo", "pid,comm"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            for line in out.splitlines()[1:]:
                parts = line.split(None, 1)
                if len(parts) == 2 and "n1mm" in parts[1].lower():
                    pids.add(int(parts[0]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()
    return pids


def n1mm_fleet_udp_binds() -> list[dict]:
    """Runtime: fleet UDP ports currently held by an N1MM process (if detectable)."""
    n1mm_pids = _n1mm_pids()
    if not n1mm_pids:
        return []
    hits: list[dict] = []
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "udp"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # UDP    0.0.0.0:2237    *:*    1234
            for line in out.splitlines():
                if "UDP" not in line.upper():
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                local, pid_s = parts[1], parts[-1]
                if not pid_s.isdigit():
                    continue
                pid = int(pid_s)
                if pid not in n1mm_pids:
                    continue
                port_s = local.rsplit(":", 1)[-1]
                if not port_s.isdigit():
                    continue
                port = int(port_s)
                if port in _FLEET_UDP_PORTS:
                    hits.append({"port": port, "pid": pid, "local": local})
        else:
            out = subprocess.check_output(
                ["ss", "-ulnp"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            for line in out.splitlines():
                if "n1mm" not in line.lower():
                    continue
                for port in _FLEET_UDP_PORTS:
                    if f":{port}" in line:
                        hits.append({"port": port, "pid": None, "local": line.strip()[:120]})
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return hits


def _choose_n1mm_ini(paths: list[Path]) -> Path | None:
    """Prefer UserDir\\N1MM Logger.ini, then exact name, then newest with reader keys."""
    if not paths:
        return None
    ud = _win_user_dir()
    exact: list[Path] = []
    for p in paths:
        if p.name.lower() == "n1mm logger.ini":
            if ud is not None:
                try:
                    if p.resolve().parent == ud.resolve():
                        return p
                except OSError:
                    pass
            exact.append(p)
    if exact:
        try:
            return sorted(exact, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        except OSError:
            return exact[0]

    scored: list[tuple[float, Path]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "enablewsjtjtdxudpreader" not in text.lower():
            continue
        try:
            scored.append((p.stat().st_mtime, p))
        except OSError:
            scored.append((0.0, p))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    try:
        return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    except OSError:
        return paths[0]


def probe_wsjt_udp_reader() -> dict:
    """Check whether N1MM's WSJT/JTDX UDP *fleet* reader is active.

    Prefer **runtime** binds (N1MM process holding :2237/…). Ini Enable flags are
    supporting evidence only — alternate/stale ini files often disagree with the UI.
    """
    paths = _find_ini_files(n1mm_user_dirs())
    chosen = _choose_n1mm_ini(paths)
    readers: list[dict] = []
    raw_lines: list[str] = []
    used_paths: list[str] = []
    if chosen is not None:
        used_paths = [str(chosen)]
        try:
            text = chosen.read_text(encoding="utf-8", errors="replace")
            readers = _parse_wsjt_udp_reader_from_ini(text)
            if readers:
                raw_lines = list(readers[0].get("raw_lines") or [])
        except OSError:
            readers = []

    runtime_hits = n1mm_fleet_udp_binds()
    ini_fleet = [
        r for r in readers
        if r.get("enabled") and r.get("port") in _FLEET_UDP_PORTS
    ]

    # Authoritative for "is it on?": runtime. Ini alone does not yellow-warn.
    fleet_conflict = bool(runtime_hits)
    detail_ini = ""
    if readers:
        bits = []
        for r in readers:
            if not r.get("key_present") and r.get("radio") == "Radio2":
                continue
            raw = r.get("enable_raw")
            bits.append(
                f"{r['radio']} Enable="
                + (repr(raw) if raw is not None else "(absent)")
                + (f" port={r.get('port')}" if r.get("port") else "")
            )
        detail_ini = "; ".join(bits)
        if used_paths:
            detail_ini += f" [{used_paths[0]}]"

    if runtime_hits:
        ports = sorted({h["port"] for h in runtime_hits})
        summary = (
            "N1MM process is bound to fleet UDP port(s) "
            + ", ".join(f":{p}" for p in ports)
            + " — turn OFF Configurer > WSJT/JTDX Setup UDP Enable for Radio 1/2."
        )
        if detail_ini:
            summary += f" Ini: {detail_ini}"
    elif ini_fleet:
        # UI/runtime off, but an ini still says True — do not yell; explain.
        summary = (
            "N1MM is not bound to fleet UDP ports (readers look off at runtime). "
            f"Stale/alternate ini still has Enable=True: {detail_ini}"
        )
        fleet_conflict = False
    elif not used_paths and not paths:
        summary = "N1MM Logger.ini not found; no N1MM fleet UDP binds seen."
    elif not any(r.get("enabled") for r in readers):
        summary = "N1MM WSJT/JTDX UDP reader off (runtime clear"
        if detail_ini:
            summary += f"; {detail_ini}"
        summary += ")."
    else:
        en = [r for r in readers if r.get("enabled")]
        parts = [f"{r['radio']} port {r.get('port')}" for r in en]
        summary = (
            "N1MM WSJT/JTDX UDP reader enabled on non-fleet port(s): "
            + ", ".join(parts)
            + " (OK for local ADIF ingest)."
        )

    return {
        "found_ini": bool(paths),
        "ini_paths": used_paths or [str(p) for p in paths[:3]],
        "readers": readers,
        "raw_lines": raw_lines,
        "runtime_binds": runtime_hits,
        "fleet_conflict": fleet_conflict,
        "summary": summary,
    }


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
