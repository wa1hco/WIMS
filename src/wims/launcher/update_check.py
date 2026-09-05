# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect whether this git checkout is behind origin/main (stdlib only)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateInfo:
    """Result of a git update probe."""

    available: bool
    local_sha: str = ""
    remote_sha: str = ""
    remote_subject: str = ""
    detail: str = ""
    is_git: bool = False
    dirty: bool = False
    local_date: str = ""   # committer date-time for local HEAD
    remote_date: str = ""  # committer date-time for remote tip

    @property
    def local_short(self) -> str:
        return (self.local_sha or "")[:7]

    @property
    def remote_short(self) -> str:
        return (self.remote_sha or "")[:7]

    @property
    def local_label(self) -> str:
        s = self.local_short
        return f"{s} {self.local_date}".strip() if self.local_date else s

    @property
    def remote_label(self) -> str:
        s = self.remote_short
        return f"{s} {self.remote_date}".strip() if self.remote_date else s


def _git(
    repo: Path,
    args: list[str],
    *,
    timeout: float = 30.0,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    out = (proc.stdout or "").strip()
    if not out and proc.stderr:
        out = proc.stderr.strip()
    return int(proc.returncode), out


def check_git_update(
    repo: Path | None = None,
    *,
    remote: str = "origin",
    branch: str = "main",
    fetch: bool = True,
    fetch_timeout: float = 25.0,
) -> UpdateInfo:
    """Return whether ``repo`` is behind ``remote/branch``.

    Soft-fails (``available=False``) when not a git tree, offline, or git missing.
    """
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return UpdateInfo(available=False, detail="not a git checkout", is_git=False)

    code, local = _git(root, ["rev-parse", "HEAD"])
    if code != 0 or not local:
        return UpdateInfo(available=False, detail=f"rev-parse failed: {local}", is_git=True)
    _, local_date = _git(root, ["log", "-1", "--format=%ci", "HEAD"])

    code_d, dirty_out = _git(root, ["status", "--porcelain"])
    dirty = bool(dirty_out) if code_d == 0 else False

    if fetch:
        # Non-fatal if offline.
        fcode, ferr = _git(
            root,
            ["fetch", "--quiet", remote, branch],
            timeout=fetch_timeout,
        )
        if fcode != 0:
            return UpdateInfo(
                available=False,
                local_sha=local,
                local_date=local_date,
                detail=f"fetch failed (offline?): {ferr}",
                is_git=True,
                dirty=dirty,
            )

    ref = f"{remote}/{branch}"
    code, remote_sha = _git(root, ["rev-parse", ref])
    if code != 0 or not remote_sha:
        return UpdateInfo(
            available=False,
            local_sha=local,
            local_date=local_date,
            detail=f"missing {ref}",
            is_git=True,
            dirty=dirty,
        )
    _, remote_date = _git(root, ["log", "-1", "--format=%ci", ref])

    if remote_sha == local:
        return UpdateInfo(
            available=False,
            local_sha=local,
            remote_sha=remote_sha,
            local_date=local_date,
            remote_date=remote_date,
            detail="up to date",
            is_git=True,
            dirty=dirty,
        )

    # Is local an ancestor of remote? (behind) vs diverged.
    code_b, _ = _git(root, ["merge-base", "--is-ancestor", local, remote_sha])
    behind = code_b == 0
    if not behind:
        return UpdateInfo(
            available=False,
            local_sha=local,
            remote_sha=remote_sha,
            local_date=local_date,
            remote_date=remote_date,
            detail="local not behind remote (diverged or ahead)",
            is_git=True,
            dirty=dirty,
        )

    code_s, subject = _git(root, ["log", "-1", "--pretty=%s", remote_sha])
    return UpdateInfo(
        available=True,
        local_sha=local,
        remote_sha=remote_sha,
        remote_subject=subject if code_s == 0 else "",
        local_date=local_date,
        remote_date=remote_date,
        detail="update available",
        is_git=True,
        dirty=dirty,
    )


def apply_git_update(
    repo: Path | None = None,
    *,
    remote: str = "origin",
    branch: str = "main",
    reset_hard: bool = False,
) -> tuple[bool, str]:
    """Pull (ff-only) or optionally reset --hard to remote/branch.

    Returns (ok, message). Prefer ``Update-Wims.ps1`` on Windows seats;
    this helper is for the launcher / tests.
    """
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return False, "not a git checkout"

    code, out = _git(root, ["fetch", "--quiet", remote, branch], timeout=60.0)
    if code != 0:
        return False, f"git fetch failed: {out}"

    if reset_hard:
        code, out = _git(root, ["reset", "--hard", f"{remote}/{branch}"])
        if code != 0:
            return False, f"git reset --hard failed: {out}"
        return True, f"reset to {remote}/{branch}"

    # Try pull with upstream; fall back to explicit ref.
    code, out = _git(root, ["pull", "--ff-only", remote, branch], timeout=60.0)
    if code != 0:
        return False, f"git pull --ff-only failed: {out}"
    return True, out or "pulled"


def update_script_path(repo: Path | None = None) -> Path:
    """Path to Windows Update-Wims.cmd (may not exist on Linux)."""
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    return root / "scripts" / "windows" / "Update-Wims.cmd"


def env_skip_update_check() -> bool:
    return (os.environ.get("WIMS_SKIP_UPDATE_CHECK") or "").strip() in (
        "1", "true", "yes", "YES", "True",
    )
