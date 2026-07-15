"""Best-effort N1MM Logger+ config / presence probe (Windows + portable paths).

N1MM does not publish a stable documented settings schema for Broadcast Data.
We look for known install/document trees, contest databases, and any .ini that
mentions broadcast/UDP/12060 so the operator still gets a useful seat check.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def documents_n1mm_roots() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    for name in ("N1MM Logger+", "N1MM Logger", "N1MMLogger+"):
        p = home / "Documents" / name
        if p.is_dir():
            roots.append(p)
    # Common alternate: OneDrive Documents
    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if not base:
            continue
        for name in ("N1MM Logger+", "N1MM Logger"):
            p = Path(base) / "Documents" / name
            if p.is_dir() and p not in roots:
                roots.append(p)
            p2 = Path(base) / "OneDrive" / "Documents" / name
            if p2.is_dir() and p2 not in roots:
                roots.append(p2)
    return roots


def databases_dir() -> Path | None:
    for root in documents_n1mm_roots():
        d = root / "Databases"
        if d.is_dir():
            return d
    return None


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


def probe_n1mm() -> dict:
    """Structured N1MM presence + config hints for the agent report."""
    roots = documents_n1mm_roots()
    db_dir = databases_dir()
    s3db: list[str] = []
    if db_dir:
        try:
            s3db = [p.name for p in sorted(db_dir.glob("*.s3db"))[:20]]
        except OSError:
            s3db = []

    ini_files: list[dict] = []
    all_hints: list[str] = []
    for root in roots:
        for pattern in ("*.ini", "*.INI"):
            try:
                paths = list(root.rglob(pattern))
            except OSError:
                paths = []
            for p in paths[:30]:
                if p.stat().st_size > 2_000_000:
                    continue
                hints = _scan_ini_hints(p)
                if hints:
                    ini_files.append({"path": str(p), "hints": hints[:15]})
                    all_hints.extend(hints[:5])

    issues: list[dict] = []
    if not roots:
        issues.append({
            "severity": "warn",
            "message": (
                "N1MM Logger+ Documents folder not found — if N1MM is installed "
                "elsewhere, configure Broadcast Data manually "
                "(Config -> Configure Ports -> Broadcast Data)"
            ),
        })
    else:
        issues.append({
            "severity": "info",
            "message": (
                f"N1MM documents tree found ({roots[0]}) — verify Broadcast Data "
                "sends Contacts + Radio to WIMS host or 224.0.0.73:12060 "
                "(default 127.0.0.1 stays local-only)"
            ),
        })

    if db_dir is None:
        issues.append({
            "severity": "info",
            "message": "No N1MM Databases folder found — contest .s3db seed on server needs a copy",
        })
    elif not s3db:
        issues.append({
            "severity": "info",
            "message": f"Databases dir empty ({db_dir}) — create/open a contest in N1MM",
        })

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

    return {
        "found": bool(roots),
        "roots": [str(r) for r in roots],
        "databases_dir": str(db_dir) if db_dir else None,
        "s3db_files": s3db,
        "ini_files": ini_files,
        "issues": issues,
    }
