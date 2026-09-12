# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect whether this install is behind GitHub (Releases and/or git).

Lab clones still use ``git fetch origin/main``. Every startup also asks
GitHub Releases (stdlib HTTP) so ZIP trees and PCs without git see a
tagged update. Cutting a Release is a tag (``vX.Y.Z`` / ``-tester`` /
``-rcN``), not every push to main.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wims import __version__ as _PKG_VERSION

_DEFAULT_GITHUB_REPO = "wa1hco/WIMS"
_TAG_VER = re.compile(
    r"^v?(?P<base>\d+\.\d+\.\d+)(?:-(?P<suffix>tester|rc(?P<rc>[1-9]\d*)))?$"
)


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
    source: str = "git"    # git | release
    release_tag: str = ""
    release_url: str = ""

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


def _git_env() -> dict[str, str]:
    """Never wait on Git Credential Manager in a hidden launcher child."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _git(
    repo: Path,
    args: list[str],
    *,
    timeout: float = 30.0,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-c", "credential.helper=", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_git_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    fetch_timeout: float = 8.0,
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
        source="git",
    )


def github_repo() -> str:
    env = (os.environ.get("WIMS_GITHUB_REPO") or "").strip()
    if env:
        return env.removeprefix("https://github.com/").strip("/")
    return _DEFAULT_GITHUB_REPO


def _http_json(url: str, *, timeout: float = 8.0):
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"wims-update-check/{_PKG_VERSION}",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — GitHub API
            raw = resp.read(1_000_000)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
        return None, str(e)
    try:
        return json.loads(raw.decode("utf-8")), ""
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, str(e)


def _version_key(tag_or_ver: str) -> tuple[int, int, int, int, int] | None:
    """Sort key: numeric base, then GA (2) > rc (1) > tester (0), then rc N."""
    m = _TAG_VER.match((tag_or_ver or "").strip())
    if not m:
        return None
    major, minor, patch = (int(x) for x in m.group("base").split("."))
    suffix = m.group("suffix")
    if suffix is None:
        return (major, minor, patch, 2, 0)
    if suffix == "tester":
        return (major, minor, patch, 0, 0)
    return (major, minor, patch, 1, int(m.group("rc") or 0))


def _local_sha(root: Path) -> str:
    if (root / ".git").exists():
        code, sha = _git(root, ["rev-parse", "HEAD"])
        if code == 0 and sha and sha != "?":
            return sha.strip()
    for path in (root / "manifest.json", root / "src" / "manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        sha = str(data.get("git_sha") or "").strip()
        if sha and sha != "unknown":
            return sha
    return ""


def _local_version(root: Path) -> str:
    for path in (root / "manifest.json", root / "src" / "manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        ver = str(data.get("version") or data.get("version_base") or "").strip()
        if ver:
            return ver
    return _PKG_VERSION


def _sha_compare(repo: str, release_sha: str, local_sha: str) -> str:
    """Return GitHub compare status: behind|ahead|identical|diverged|unknown."""
    if not release_sha or not local_sha:
        return "unknown"
    if release_sha.lower() == local_sha.lower() or (
        len(local_sha) >= 7 and release_sha.lower().startswith(local_sha.lower()[:7])
    ) or (
        len(release_sha) >= 7 and local_sha.lower().startswith(release_sha.lower()[:7])
    ):
        return "identical"
    url = (
        f"https://api.github.com/repos/{repo}/compare/"
        f"{release_sha[:40]}...{local_sha[:40]}"
    )
    data, err = _http_json(url)
    if not isinstance(data, dict):
        return "unknown"
    status = str(data.get("status") or "").strip().lower()
    return status if status in ("behind", "ahead", "identical", "diverged") else "unknown"


def check_github_release(
    repo: Path | None = None,
    *,
    github: str | None = None,
) -> UpdateInfo:
    """Compare this tree to the newest GitHub Release (GA, else latest prerelease)."""
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    gh = (github or github_repo()).strip("/")
    local_sha = _local_sha(root)
    local_ver = _local_version(root)
    is_git = (root / ".git").exists()
    dirty = False
    if is_git:
        code_d, dirty_out = _git(root, ["status", "--porcelain"])
        dirty = bool(dirty_out) if code_d == 0 else False

    latest, err = _http_json(f"https://api.github.com/repos/{gh}/releases/latest")
    if not isinstance(latest, dict):
        listing, err2 = _http_json(
            f"https://api.github.com/repos/{gh}/releases?per_page=5"
        )
        if isinstance(listing, list) and listing:
            latest = listing[0] if isinstance(listing[0], dict) else None
            err = ""
        else:
            latest = None
            err = err or err2 or "no releases"

    if not isinstance(latest, dict):
        return UpdateInfo(
            available=False,
            local_sha=local_sha,
            detail=f"GitHub Releases: {err}",
            is_git=is_git,
            dirty=dirty,
            source="release",
        )

    tag = str(latest.get("tag_name") or "").strip()
    html = str(latest.get("html_url") or "").strip()
    subject = str(latest.get("name") or tag).strip()
    rel_date = str(latest.get("published_at") or "").replace("T", " ").replace("Z", " UTC")

    commit, _cerr = _http_json(
        f"https://api.github.com/repos/{gh}/commits/{tag}"
    )
    remote_sha = ""
    if isinstance(commit, dict):
        remote_sha = str(commit.get("sha") or "").strip()

    behind = False
    detail = "up to date with GitHub Release"
    cmp = _sha_compare(gh, remote_sha, local_sha) if (remote_sha and local_sha) else ""
    if cmp == "behind":
        behind = True
        detail = "update available (GitHub Release)"
    elif cmp in ("ahead", "identical"):
        behind = False
        detail = "up to date with GitHub Release" if cmp == "identical" else (
            "local newer than GitHub Release"
        )
    else:
        loc_k = _version_key(local_ver)
        rem_k = _version_key(tag)
        if loc_k is not None and rem_k is not None and rem_k > loc_k:
            behind = True
            detail = "update available (GitHub Release)"
        elif loc_k is not None and rem_k is not None and rem_k == loc_k:
            detail = "up to date with GitHub Release"
        elif loc_k is not None and rem_k is not None:
            detail = "local newer than GitHub Release"

    return UpdateInfo(
        available=behind,
        local_sha=local_sha,
        remote_sha=remote_sha,
        remote_subject=subject,
        detail=detail,
        is_git=is_git,
        dirty=dirty,
        local_date="",
        remote_date=rel_date,
        source="release",
        release_tag=tag,
        release_url=html or f"https://github.com/{gh}/releases",
    )


def check_for_update(
    repo: Path | None = None,
    *,
    fetch: bool = True,
) -> UpdateInfo:
    """Git behind origin/main (lab) **or** behind the newest GitHub Release.

    Git clones with a working fetch use origin/main only. A newer Release tag
    than ``__version__`` must not keep offering after ``git pull`` already
    matched main (that loop started when Releases were added for ZIP PCs).
    ZIP / no-git trees, and git clones whose fetch failed, use Releases.
    """
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    git_info = check_git_update(root, fetch=fetch)
    git_usable = git_info.is_git and "fetch failed" not in (git_info.detail or "")
    if git_usable:
        return git_info
    rel_info = check_github_release(root)
    if rel_info.available:
        return rel_info
    if rel_info.detail and "GitHub Releases" not in (rel_info.detail or ""):
        return rel_info
    if rel_info.detail:
        return rel_info
    return git_info


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
