# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision stamp for operator-facing banners (SHA + commit date-time).

A git checkout uses ``git log``. A release tree has no ``.git``, so the
packager writes ``BUILD_STAMP`` (commit SHA + version) into the download.
When that file is also missing, the package version is used. ``?`` means
the revision is unknown.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Written into a release tarball / zip by tools/dev/package-release.sh.
STAMP_FILENAME = "BUILD_STAMP"

_GIT_TIMEOUT_S = 2
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _is_git_tree(root: Path) -> bool:
    """True only when *this* folder is a git checkout, not a parent folder."""
    return (root / ".git").exists()


def _git_output(root: Path, *args: str) -> str:
    out = subprocess.check_output(
        ["git", "-C", str(root), *args],
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=_GIT_TIMEOUT_S,
        creationflags=_CREATE_NO_WINDOW,
    )
    return (out or "").strip()


def read_build_stamp(root: Path) -> dict[str, str]:
    """Parse ``BUILD_STAMP`` at ``root``. Missing or unreadable → ``{}``."""
    path = Path(root) / STAMP_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        if key:
            fields[key] = value.strip()
    return fields


def write_build_stamp(
    root: Path,
    *,
    version: str,
    commit: str = "",
    stamp: str = "",
) -> Path:
    """Write ``BUILD_STAMP`` into ``root`` and return the path."""
    dest = Path(root) / STAMP_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    version = (version or "").strip()
    commit = (commit or "").strip()
    stamp = (stamp or "").strip()
    lines = [
        "# WS Hub build identity. Written by tools/dev/package-release.sh.",
        f"version={version}",
        f"commit={commit}",
        f"stamp={stamp}",
        "",
    ]
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def collect_build_identity(repo: Path, version: str) -> dict[str, str]:
    """Commit SHA and git-style stamp from ``repo``, plus ``version``."""
    version = (version or "").strip()
    commit = ""
    stamp = ""
    if _is_git_tree(Path(repo)):
        try:
            commit = _git_output(Path(repo), "rev-parse", "HEAD")
        except (OSError, subprocess.SubprocessError, ValueError):
            commit = ""
        try:
            stamp = _git_output(Path(repo), "log", "-1", "--format=%h %ci")
        except (OSError, subprocess.SubprocessError, ValueError):
            stamp = ""
    if not stamp and commit:
        stamp = commit[:7]
    return {"version": version, "commit": commit, "stamp": stamp}


def _version_fallback() -> str:
    try:
        from wims import __version__
        return (__version__ or "").strip() or "?"
    except Exception:
        return "?"


def _stamp_from_file(root: Path) -> str:
    fields = read_build_stamp(root)
    stamp = (fields.get("stamp") or "").strip()
    if stamp:
        return stamp
    commit = (fields.get("commit") or "").strip()
    if commit:
        return commit[:7]
    version = (fields.get("version") or "").strip()
    return version


def _read_git_stamp(root: Path) -> str:
    """Return ``abc1234 2026-09-05 14:42 -0400``, a stamp, a version, or ``?``."""
    if _is_git_tree(root):
        try:
            text = _git_output(root, "log", "-1", "--format=%h %ci")
            if text:
                return text
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    from_file = _stamp_from_file(root)
    if from_file:
        return from_file
    return _version_fallback()


@lru_cache(maxsize=1)
def git_stamp(repo: Path | None = None) -> str:
    """Revision cached for this process (the code it loaded).

    The site server records this once at start and keeps reporting it.
    Use :func:`git_stamp_fresh` to re-read the checkout on disk.
    """
    root = Path(repo) if repo is not None else _REPO
    return _read_git_stamp(root)


def git_stamp_fresh(repo: Path | None = None) -> str:
    """Re-read HEAD or the build stamp from disk. Does not reuse the cache.

    One ``git log -1`` on a checkout, or a read of ``BUILD_STAMP`` on a
    release tree. The launcher calls this on its periodic refresh and after
    an update, so a branch or install change shows up without restarting
    the window.
    """
    root = Path(repo) if repo is not None else _REPO
    return _read_git_stamp(root)


def git_short(repo: Path | None = None) -> str:
    """Short SHA (or version fallback) — first token of :func:`git_stamp`."""
    stamp = git_stamp(repo)
    token = stamp.split()[0] if stamp else ""
    return token if token and token != "?" else "?"
