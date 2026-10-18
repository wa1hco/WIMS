# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect whether this install is behind GitHub (Releases, tags, and/or git).

Lab clones still use ``git fetch origin/main``. Every startup also asks
GitHub (stdlib HTTP) so ZIP trees and PCs without git see a tagged update.
The Updates list merges published Releases with version tags that have no
Release, so a tag such as ``v1.0.16`` still appears. Cutting a Release is a
tag (``vX.Y.Z`` / ``-tester`` / ``-rcN``), not every push to main.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
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
    """One version in the Updates list.

    A published Release, or a version tag that has no Release. ``body`` is
    the release notes, or a short summary of the commits since the previous tag.
    """

    tag: str
    name: str
    published: str  # local calendar day (YYYY-MM-DD)
    body: str
    html_url: str
    prerelease: bool
    relation: str  # newer | current | older | other
    stamp: str = ""  # local date and time for the row tip

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
    date = (entry.stamp or entry.published or "").strip() or "date not published"
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


def _raw_day(raw: object) -> str:
    """Date slice used when a stamp cannot be read. Never raises."""
    try:
        text = str(raw or "").strip()
    except Exception:
        return ""
    if "T" in text:
        text = text.split("T", 1)[0]
    return text[:10]


def _parse_instant(raw: str) -> datetime | None:
    """Timezone-aware instant from a GitHub ISO stamp, or None.

    ``Z`` is UTC. Python 3.10's ``fromisoformat`` does not accept ``Z``.
    Fractional seconds are dropped; the row shows the minute.
    """
    text = raw.strip()
    if not text:
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    elif len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    text = re.sub(r"\.\d+", "", text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _local_dates(raw: object, tz: tzinfo | None = None) -> tuple[str, str]:
    """Local calendar day, and the row tip (day plus local time).

    ``tz`` None is this PC's time zone. A date with no clock is left as
    written. An unreadable stamp falls back to the raw date. This does
    not raise.
    """
    try:
        original = str(raw or "").strip()
    except Exception:
        return "", ""
    fallback = _raw_day(original)
    if not original or ("T" not in original and ":" not in original):
        return fallback, fallback
    try:
        instant = _parse_instant(original)
        if instant is None:
            return fallback, fallback
        local = instant.astimezone(tz)
        day = local.strftime("%Y-%m-%d")
        hour12 = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        return day, f"{day} {hour12}:{local.minute:02d} {ampm}"
    except Exception:
        return fallback, fallback


def _published_day(raw: object, tz: tzinfo | None = None) -> str:
    """Local calendar day for an Updates row. Never raises."""
    day, _stamp = _local_dates(raw, tz=tz)
    return day


def releases_from_payload(
    payload: object,
    *,
    local_version: str,
    tz: tzinfo | None = None,
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
        day, stamp = _local_dates(str(item.get("published_at") or ""), tz=tz)
        rows.append(ReleaseEntry(
            tag=tag,
            name=str(item.get("name") or tag).strip(),
            published=day,
            body=str(item.get("body") or ""),
            html_url=str(item.get("html_url") or "").strip(),
            prerelease=bool(item.get("prerelease")),
            relation=release_relation(tag, local_version),
            stamp=stamp,
        ))

    def sort_key(entry: ReleaseEntry) -> tuple:
        key = _version_key(entry.tag) or (0, 0, 0, 0, 0)
        return (key, entry.published)

    rows.sort(key=sort_key, reverse=True)
    return tuple(rows)


# GitHub list pages. 100 is the API maximum; a single page of 20 used to
# hide older versions once the project grew past that.
_PAGE_SIZE = 100
_MAX_PAGES = 10

# Commit summaries for tags that have no Release. Kept for this process so
# Check now does not repeat the compare calls. The first value is the GitHub
# timestamp (still UTC); the row converts it to this PC's local time.
_TAG_SUMMARY_CACHE: dict[str, tuple[str, str]] = {}


def clear_release_note_cache() -> None:
    """Drop cached tag summaries. Tests use this; the window does not."""
    _TAG_SUMMARY_CACHE.clear()


def _paged_list(url: str) -> tuple[list | None, str, float]:
    """Every page of a GitHub list.

    ``(None, notice, wait)`` when the first page cannot be read. A later
    page that repeats or comes back short ends the list. Notice is
    ``offline`` or ``rate_limit``.
    """
    items: list = []
    seen: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        joiner = "&" if "?" in url else "?"
        result = github_get(f"{url}{joiner}per_page={_PAGE_SIZE}&page={page}")
        if result.rate_limited:
            return None, "rate_limit", float(result.retry_after_s or 0.0)
        if result.data is None or not isinstance(result.data, list):
            if page == 1:
                return None, "offline", 0.0
            break
        fresh = 0
        for item in result.data:
            key = ""
            if isinstance(item, dict):
                key = str(
                    item.get("tag_name") or item.get("name") or item.get("sha") or ""
                ).strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            items.append(item)
            fresh += 1
        if fresh == 0 or len(result.data) < _PAGE_SIZE:
            break
    return items, "", 0.0


def _version_tags(payload: list) -> list[tuple[str, str]]:
    """Version tags ``(name, sha)``, oldest first. Other tags are skipped."""
    rows: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if _version_key(name) is None:
            continue
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        sha = str(commit.get("sha") or "").strip()
        rows.append((name, sha))
    rows.sort(key=lambda pair: _version_key(pair[0]) or (0, 0, 0, 0, 0))
    return rows


def _note_spans(
    tag_rows: list[tuple[str, str]],
    have_notes: set[str],
) -> list[tuple[str | None, list[tuple[str, str]]]]:
    """Contiguous tags that still need a summary, each with the previous tag.

    One span is one compare call (previous tag … newest tag in the span).
    """
    spans: list[tuple[str | None, list[tuple[str, str]]]] = []
    span: list[tuple[str, str]] = []
    base: str | None = None
    for name, sha in tag_rows:
        if name in have_notes:
            if span:
                spans.append((base, span))
                span = []
            base = name
            continue
        span.append((name, sha))
    if span:
        spans.append((base, span))
    return spans


def _sha_same(left: str, right: str) -> bool:
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    n = min(len(a), len(b))
    return n >= 7 and a[:n] == b[:n]


def _commit_message_date(commit: dict) -> tuple[str, str]:
    inner = commit.get("commit") if isinstance(commit.get("commit"), dict) else commit
    if not isinstance(inner, dict):
        return "", ""
    message = str(inner.get("message") or "")
    committer = inner.get("committer") if isinstance(inner.get("committer"), dict) else {}
    author = inner.get("author") if isinstance(inner.get("author"), dict) else {}
    when = str((committer or {}).get("date") or (author or {}).get("date") or "")
    return message, when


def _bucket_commits(
    commits: list,
    span: list[tuple[str, str]],
) -> tuple[dict[str, list[str]], dict[str, str], set[str]]:
    """Split compare commits across the tags in ``span`` (oldest first).

    Commits up to and including a tag's own commit belong to that tag.
    """
    subjects: dict[str, list[str]] = {name: [] for name, _sha in span}
    dates: dict[str, str] = {}
    matched: set[str] = set()
    if not span:
        return subjects, dates, matched
    index = 0
    current, target = span[0]
    for commit in commits:
        if index >= len(span) or not isinstance(commit, dict):
            continue
        message, when = _commit_message_date(commit)
        subjects[current].append(message)
        csha = str(commit.get("sha") or "")
        if _sha_same(csha, target):
            matched.add(current)
            if when:
                dates[current] = when
            index += 1
            if index < len(span):
                current, target = span[index]
    return subjects, dates, matched


def notes_from_subjects(subjects: list[str]) -> str:
    """First lines of commit messages, short enough for the summary."""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in subjects:
        line = (raw or "").strip().splitlines()[0].strip() if raw else ""
        line = line.lstrip("-*• ").strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= 8:
            break
    return " ".join(lines)


def _compare_commits(gh: str, base: str, head: str) -> tuple[list | None, str]:
    """Commits from ``base`` to ``head``. Status is ``""``, ``offline``, or ``rate_limit``."""
    url = (
        f"https://api.github.com/repos/{gh}/compare/"
        f"{quote(base, safe='')}...{quote(head, safe='')}"
    )
    result = github_get(url)
    if result.rate_limited:
        return None, "rate_limit"
    if not isinstance(result.data, dict):
        return None, "offline"
    commits = result.data.get("commits")
    if not isinstance(commits, list):
        return None, "offline"
    total = result.data.get("total_commits")
    if isinstance(total, int) and total > len(commits):
        return None, "truncated"
    return commits, ""


def _commit_note(gh: str, ref: str) -> tuple[str, str, str]:
    """``(timestamp, summary, status)`` for one commit. Status ``""`` on success.

    The timestamp stays the GitHub value. The list converts it to local
    time when the row is built.
    """
    result = github_get(
        f"https://api.github.com/repos/{gh}/commits/{quote(ref, safe='')}"
    )
    if result.rate_limited:
        return "", "", "rate_limit"
    if not isinstance(result.data, dict):
        return "", "", "offline"
    message, when = _commit_message_date(result.data)
    return when, notes_from_subjects([message]), ""


def _cache_span_notes(
    gh: str,
    span: list[tuple[str, str]],
    subjects: dict[str, list[str]],
    dates: dict[str, str],
    matched: set[str],
) -> bool:
    """Store summaries. False means stop (offline or rate limit)."""
    for name, sha in span:
        if name in matched:
            _TAG_SUMMARY_CACHE[name] = (
                dates.get(name) or "",
                notes_from_subjects(subjects.get(name) or []),
            )
            continue
        when, body, status = _commit_note(gh, sha or name)
        if status:
            return False
        _TAG_SUMMARY_CACHE[name] = (when, body)
    return True


def _fill_span(gh: str, base: str | None, span: list[tuple[str, str]]) -> bool:
    """One compare for the span when a previous tag exists. False stops further spans."""
    if base:
        commits, status = _compare_commits(gh, base, span[-1][0])
        if status in ("rate_limit", "offline"):
            return False
        if commits is not None:
            subjects, dates, matched = _bucket_commits(commits, span)
            return _cache_span_notes(gh, span, subjects, dates, matched)
    prev = base
    for name, sha in span:
        if prev:
            commits, status = _compare_commits(gh, prev, name)
            if status in ("rate_limit", "offline"):
                return False
            if commits is not None:
                subjects, dates, matched = _bucket_commits(commits, [(name, sha)])
                if not _cache_span_notes(gh, [(name, sha)], subjects, dates, matched):
                    return False
                prev = name
                continue
        when, body, status = _commit_note(gh, sha or name)
        if status:
            return False
        _TAG_SUMMARY_CACHE[name] = (when, body)
        prev = name
    return True


def _fill_tag_note_cache(
    gh: str,
    tag_rows: list[tuple[str, str]],
    released: set[str],
) -> None:
    have = set(released) | set(_TAG_SUMMARY_CACHE)
    for base, span in _note_spans(tag_rows, have):
        if not _fill_span(gh, base, span):
            return


def _entries_with_tags(
    releases: tuple[ReleaseEntry, ...],
    tag_rows: list[tuple[str, str]],
    *,
    local_version: str,
    github: str,
    tz: tzinfo | None = None,
) -> tuple[ReleaseEntry, ...]:
    """Releases plus version tags that have no Release, newest version first."""
    by_tag = {entry.tag: entry for entry in releases}
    for name, _sha in tag_rows:
        if name in by_tag:
            continue
        when, body = _TAG_SUMMARY_CACHE.get(name, ("", ""))
        published, stamp = _local_dates(when, tz=tz)
        key = _version_key(name)
        by_tag[name] = ReleaseEntry(
            tag=name,
            name=name,
            published=published,
            body=body,
            html_url=f"https://github.com/{github}/releases/tag/{name}",
            prerelease=bool(key is not None and key[3] < 2),
            relation=release_relation(name, local_version),
            stamp=stamp,
        )
    rows = list(by_tag.values())

    def sort_key(entry: ReleaseEntry) -> tuple:
        key = _version_key(entry.tag) or (0, 0, 0, 0, 0)
        return (key, entry.published)

    rows.sort(key=sort_key, reverse=True)
    return tuple(rows)


def _list_versions(
    repo: Path | None,
    github: str | None,
    tz: tzinfo | None = None,
) -> tuple[tuple[ReleaseEntry, ...], str, float]:
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    gh = (github or github_repo()).strip("/")
    local = _local_version(root)
    releases_raw, notice, wait = _paged_list(
        f"https://api.github.com/repos/{gh}/releases"
    )
    if notice:
        return (), notice, wait
    tags_raw, notice, wait = _paged_list(
        f"https://api.github.com/repos/{gh}/tags"
    )
    if notice:
        return (), notice, wait
    entries = releases_from_payload(releases_raw or [], local_version=local, tz=tz)
    tag_rows = _version_tags(tags_raw or [])
    _fill_tag_note_cache(gh, tag_rows, {entry.tag for entry in entries})
    merged = _entries_with_tags(
        entries, tag_rows, local_version=local, github=gh, tz=tz,
    )
    if not merged:
        return (), "empty", 0.0
    return merged, "", 0.0


def list_github_releases(
    repo: Path | None = None,
    *,
    github: str | None = None,
    tz: tzinfo | None = None,
) -> tuple[tuple[ReleaseEntry, ...], str, float]:
    """Releases and version tags, plus a quiet notice.

    Notice is ``""``, ``offline``, ``rate_limit``, or ``empty``.
    The third value is how long a rate limit asked us to wait.
    A tag with no release notes uses the commits since the previous tag.
    Those summaries are cached for this process. Does not install.
    Offline and rate limits return a result; they do not raise.
    """
    try:
        return _list_versions(repo, github, tz=tz)
    except Exception as exc:
        if isinstance(exc, (AssertionError, KeyboardInterrupt, SystemExit)):
            raise
        return (), "offline", 0.0


_NOTICE_TEXT = {
    "offline": "No network. The update list is unchanged.",
    "rate_limit": "GitHub is limiting checks right now. WIMS will try again later.",
    "empty": "No versions to show yet.",
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
