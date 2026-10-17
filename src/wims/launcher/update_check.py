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
import sys
import time
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


@dataclass(frozen=True)
class HttpResult:
    """One GitHub HTTP call. Rate limits stay data, not a traceback."""

    data: object = None
    error: str = ""
    status: int = 0
    rate_limited: bool = False
    retry_after_s: float = 0.0


def _retry_after_seconds(headers) -> float:
    if headers is None:
        return 0.0
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    reset = headers.get("X-RateLimit-Reset") if hasattr(headers, "get") else None
    if reset:
        try:
            return max(0.0, float(reset) - time.time())
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _rate_limited(status: int, body: str, headers) -> bool:
    if status == 429:
        return True
    text = (body or "").lower()
    if status == 403 and "rate limit" in text:
        return True
    if headers is not None and hasattr(headers, "get"):
        remaining = headers.get("X-RateLimit-Remaining")
        if str(remaining or "") == "0" and status in (403, 429):
            return True
    return False


def github_get(url: str, *, timeout: float = 8.0) -> HttpResult:
    """GET JSON from GitHub. Offline and rate limits return a result, no raise."""
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
            status = int(getattr(resp, "status", 200) or 200)
            headers = getattr(resp, "headers", None)
    except HTTPError as e:
        body = ""
        try:
            body = e.read(4000).decode("utf-8", "replace")
        except Exception:
            body = str(e)
        status = int(getattr(e, "code", 0) or 0)
        headers = getattr(e, "headers", None)
        limited = _rate_limited(status, body, headers)
        return HttpResult(
            data=None,
            error=body or str(e),
            status=status,
            rate_limited=limited,
            retry_after_s=_retry_after_seconds(headers) if limited else 0.0,
        )
    except (URLError, TimeoutError, OSError, ValueError) as e:
        return HttpResult(data=None, error=str(e), status=0)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return HttpResult(data=None, error=str(e), status=status)
    return HttpResult(data=data, error="", status=status, retry_after_s=0.0)


def _http_json(url: str, *, timeout: float = 8.0):
    result = github_get(url, timeout=timeout)
    if result.data is None:
        return None, result.error or "no response"
    return result.data, ""


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


# While the WIMS window is open. A few hours, and never faster than the floor
# even if a setting asks for a tighter loop. Check now ignores the interval.
DEFAULT_CHECK_INTERVAL_S = 3 * 60 * 60
MIN_CHECK_INTERVAL_S = 15 * 60
INITIAL_CHECK_DELAY_S = 4.0

# Background checks look only. Install runs from the Install button.
AUTO_INSTALL = False


def clamp_check_interval(
    seconds: float,
    *,
    minimum_s: float = MIN_CHECK_INTERVAL_S,
) -> float:
    """Seconds between looks. Anything under the floor becomes the floor."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = DEFAULT_CHECK_INTERVAL_S
    if value < minimum_s:
        return float(minimum_s)
    return value


def seconds_until_next_check(
    *,
    elapsed_s: float,
    interval_s: float,
    rate_limit_wait_s: float = 0.0,
    force: bool = False,
) -> float:
    """How long to wait before the next background look.

    ``force`` is Check now: wait zero. A rate-limit pause never shortens the
    normal interval; it can only lengthen it. This does not install.
    """
    if force:
        return 0.0
    interval = clamp_check_interval(interval_s)
    try:
        elapsed = max(0.0, float(elapsed_s))
    except (TypeError, ValueError):
        elapsed = 0.0
    remaining = max(0.0, interval - elapsed)
    try:
        limited = max(0.0, float(rate_limit_wait_s or 0.0))
    except (TypeError, ValueError):
        limited = 0.0
    return max(remaining, limited)


@dataclass(frozen=True)
class ReleaseEntry:
    """One published GitHub release, for the Updates list."""

    tag: str
    name: str
    published: str
    body: str
    html_url: str
    prerelease: bool
    relation: str  # newer | current | older | other

    def line(self) -> str:
        mark = {
            "newer": "available",
            "current": "this copy",
            "older": "older",
            "other": "",
        }.get(self.relation, "")
        date = self.published or "no date"
        extra = f"    {mark}" if mark else ""
        return f"{self.tag}    {date}{extra}"

    def summary(self) -> str:
        return summarize_notes(self.body, limit=280)


def summarize_notes(body: str, *, limit: int = 280) -> str:
    """Short plain text from release notes. Empty notes say so."""
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        return "No notes were published with this release."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = " ".join(lines)
    if len(joined) <= limit:
        return joined
    return joined[: limit - 3].rstrip() + "..."


def notes_tooltip(entry: ReleaseEntry) -> str:
    date = entry.published or "date not published"
    return f"{entry.tag}  {date}\n\n{summarize_notes(entry.body, limit=700)}"


def release_relation(tag: str, local_version: str) -> str:
    remote = _version_key(tag)
    local = _version_key(local_version)
    if remote is None or local is None:
        return "other"
    if remote > local:
        return "newer"
    if remote == local:
        return "current"
    return "older"


def _published_day(raw: str) -> str:
    text = (raw or "").strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return text[:10]


def releases_from_payload(
    payload: object,
    *,
    local_version: str,
) -> tuple[ReleaseEntry, ...]:
    """Turn a GitHub releases JSON list into list rows, newest version first."""
    if not isinstance(payload, list):
        return ()
    rows: list[ReleaseEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag_name") or "").strip()
        if not tag:
            continue
        rows.append(ReleaseEntry(
            tag=tag,
            name=str(item.get("name") or tag).strip(),
            published=_published_day(str(item.get("published_at") or "")),
            body=str(item.get("body") or ""),
            html_url=str(item.get("html_url") or "").strip(),
            prerelease=bool(item.get("prerelease")),
            relation=release_relation(tag, local_version),
        ))

    def sort_key(entry: ReleaseEntry) -> tuple:
        key = _version_key(entry.tag) or (0, 0, 0, 0, 0)
        return (key, entry.published)

    rows.sort(key=sort_key, reverse=True)
    return tuple(rows)


def list_github_releases(
    repo: Path | None = None,
    *,
    github: str | None = None,
) -> tuple[tuple[ReleaseEntry, ...], str, float]:
    """Published releases plus a quiet notice.

    Notice is ``""``, ``offline``, ``rate_limit``, or ``empty``.
    The third value is how long a rate limit asked us to wait.
    Does not install.
    """
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    gh = (github or github_repo()).strip("/")
    result = github_get(
        f"https://api.github.com/repos/{gh}/releases?per_page=20"
    )
    if result.rate_limited:
        return (), "rate_limit", float(result.retry_after_s or 0.0)
    if result.data is None:
        return (), "offline", 0.0
    if not isinstance(result.data, list):
        return (), "offline", 0.0
    entries = releases_from_payload(result.data, local_version=_local_version(root))
    if not entries:
        return (), "empty", 0.0
    return entries, "", 0.0


_NOTICE_TEXT = {
    "offline": "No network. The update list is unchanged.",
    "rate_limit": "GitHub is limiting checks right now. WIMS will try again later.",
    "empty": "No published releases yet.",
}


@dataclass(frozen=True)
class UpdateSnapshot:
    """One background look: banner info, release list, quiet notice."""

    info: UpdateInfo
    releases: tuple[ReleaseEntry, ...] = ()
    notice: str = ""
    notice_text: str = ""
    retry_after_s: float = 0.0


def gather_updates(
    repo: Path | None = None,
    *,
    fetch: bool = True,
) -> UpdateSnapshot:
    """Look for updates. Does not install, even when something newer exists."""
    if AUTO_INSTALL:
        raise RuntimeError("background update check must not install")
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    info = check_for_update(root, fetch=fetch)
    releases, notice, retry = list_github_releases(root)
    return UpdateSnapshot(
        info=info,
        releases=releases,
        notice=notice,
        notice_text=_NOTICE_TEXT.get(notice, ""),
        retry_after_s=retry,
    )


def wims_config_dir() -> Path:
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims"
    return Path.home() / ".config" / "wims"


def rollback_path() -> Path:
    env = (os.environ.get("WIMS_UPDATE_ROLLBACK") or "").strip()
    if env:
        return Path(env)
    return wims_config_dir() / "update_rollback.json"


def read_rollback(path: Path | None = None) -> dict | None:
    file = Path(path) if path is not None else rollback_path()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sha = str(data.get("sha") or "").strip()
    if not sha:
        return None
    return data


def _write_rollback(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _say(on_progress, message: str) -> None:
    if on_progress is not None:
        on_progress(message)


def _tree_dirty(root: Path) -> bool:
    code, out = _git(root, ["status", "--porcelain"])
    return bool(out) if code == 0 else False


def apply_release(
    repo: Path | None,
    tag: str,
    *,
    remote: str = "origin",
    rollback_file: Path | None = None,
    on_progress=None,
) -> tuple[bool, str]:
    """Switch this git tree to ``tag``. Saves the current copy first.

    A tree that is not a git checkout is left unchanged. Local edits block
    the switch. This runs only when the operator picks Install.
    """
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    wanted = (tag or "").strip()
    if not wanted:
        return False, "Select an update in the list first."
    if not (root / ".git").exists():
        _say(on_progress, "This copy cannot switch versions by itself.")
        return False, (
            "This copy was not installed from git, so WIMS cannot switch it "
            "in place. The release page has the download. Keep your seat "
            "files when you replace the folder."
        )
    if _tree_dirty(root):
        _say(on_progress, "Local edits are in the way.")
        return False, (
            "This copy has local edits. WIMS left it unchanged. "
            "Install is available after those edits are put away."
        )
    _say(on_progress, f"Getting {wanted}.")
    code, _out = _git(
        root, ["fetch", "--quiet", remote, "tag", wanted], timeout=60.0,
    )
    if code != 0:
        return False, "Could not reach GitHub. This copy is unchanged."

    code_b, branch = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    code_s, sha = _git(root, ["rev-parse", "HEAD"])
    if code_s != 0 or not sha:
        return False, "Could not remember this copy. Nothing was changed."
    _say(on_progress, "Saving this copy so you can go back.")
    dest = Path(rollback_file) if rollback_file is not None else rollback_path()
    try:
        _write_rollback(dest, {
            "schema": 1,
            "sha": sha.strip(),
            "branch": branch.strip() if code_b == 0 else "",
            "tag": wanted,
        })
    except OSError:
        return False, "Could not save the previous copy. Nothing was changed."

    _say(on_progress, f"Switching to {wanted}.")
    code, _out = _git(root, ["checkout", "--detach", wanted])
    if code != 0:
        return False, "Could not switch to that release. This copy is unchanged."
    return True, f"Now on {wanted}. Restarting the WIMS window."


def rollback_release(
    repo: Path | None = None,
    *,
    rollback_file: Path | None = None,
    on_progress=None,
) -> tuple[bool, str]:
    """Return to the copy saved by the last install. Does not run by itself."""
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    dest = Path(rollback_file) if rollback_file is not None else rollback_path()
    saved = read_rollback(dest)
    if not saved:
        return False, (
            "There is no saved previous copy yet. "
            "WIMS remembers one when you install an update."
        )
    if not (root / ".git").exists():
        return False, "This copy cannot switch versions by itself."
    if _tree_dirty(root):
        return False, (
            "This copy has local edits. WIMS left it unchanged."
        )
    sha = str(saved.get("sha") or "").strip()
    branch = str(saved.get("branch") or "").strip()
    _say(on_progress, "Restoring the previous copy.")
    restored = False
    if branch and branch not in ("HEAD", ""):
        code, tip = _git(root, ["rev-parse", branch])
        if code == 0 and tip.strip() == sha:
            code_c, _out = _git(root, ["checkout", branch])
            restored = code_c == 0
    if not restored:
        code_c, _out = _git(root, ["checkout", "--detach", sha])
        restored = code_c == 0
    if not restored:
        return False, "Could not go back. This copy is unchanged."
    return True, "Back on the previous copy. Restarting the WIMS window."
