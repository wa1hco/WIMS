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

"""Find each log once. Shared paths, inodes, and identical files collapse.

A dead network path is given about two seconds to answer, then marked
unreadable. A file whose size and modification time match the last check
is not read again.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat as statmod
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from wims.adif import read_text, to_logged_qso
from wims.logaudit.check import (
    AuditQso,
    Report,
    SourceInfo,
    compare,
    filter_since,
    qsos_from_logged,
)

STAT_TIMEOUT_S = 2.0
NETWORK_READ_TIMEOUT_S = 20.0
CACHE_VERSION = 1

_NETWORK_FS = {"cifs", "nfs", "nfs4", "smb3", "fuse.sshfs", "fuse.rclone"}


@dataclass
class Candidate:
    label: str
    path: str
    kind: str = "adif"  # adif, n1mm, lotw
    contest_nr: int | None = None


@dataclass
class FileProbe:
    path: str
    status: str
    detail: str = ""
    realpath: str = ""
    dev: int | None = None
    ino: int | None = None
    size: int | None = None
    mtime_ns: int | None = None


@dataclass
class _Group:
    labels: list[str]
    path: str
    kind: str
    contest_nr: int | None
    probe: FileProbe
    how: str = ""
    probes: list[FileProbe] = field(default_factory=list)
    data: bytes | None = None
    digest: str | None = None
    rows: list[AuditQso] = field(default_factory=list)
    cached: bool = False
    problem: str = ""


def run_bounded(fn, timeout: float):
    """Run ``fn`` in a daemon thread. Return ``(kind, value)``.

    ``kind`` is ``ok``, ``timeout``, or ``error``. A timed-out call is left
    running; the caller does not wait for a dead drive.
    """
    outcome: dict = {}

    def runner() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — surfaced to the caller
            outcome["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return "timeout", None
    if "error" in outcome:
        return "error", outcome["error"]
    return "ok", outcome.get("value")


def is_network_path(path: str) -> bool:
    raw = str(path or "")
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    try:
        text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    mounts: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mount = parts[1].replace("\\040", " ")
        if parts[2] in _NETWORK_FS:
            mounts.append((mount, parts[2]))
    if not mounts:
        return False
    try:
        resolved = os.path.realpath(raw)
    except OSError:
        resolved = raw
    for mount, _fstype in mounts:
        if resolved == mount or resolved.startswith(mount.rstrip("/") + "/"):
            return True
    return False


def _os_problem(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "locked"
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if isinstance(exc, OSError):
        win = getattr(exc, "winerror", None)
        if win in (32, 33) or exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
            return "locked"
        if exc.errno == errno.ENOENT:
            return "missing"
        return "unreadable"
    return "unreadable"


def probe_path(path: str, *, timeout: float = STAT_TIMEOUT_S, stat_fn=None) -> FileProbe:
    """Stat one path. A call that exceeds ``timeout`` is a dead drive."""
    stat_fn = stat_fn or os.stat
    target = str(path)

    def work():
        st = stat_fn(target)
        real = os.path.realpath(target)
        return st, real

    kind, value = run_bounded(work, timeout)
    if kind == "timeout":
        return FileProbe(
            path=target,
            status="timeout",
            detail=(
                "Did not answer within 2 seconds. "
                "Connect that drive and check again."
            ),
        )
    if kind == "error":
        problem = _os_problem(value)
        if problem == "missing":
            return FileProbe(path=target, status="missing", detail="not found")
        if problem == "locked":
            return FileProbe(
                path=target, status="locked",
                detail="Another program has this file open, so it could not be read.",
            )
        return FileProbe(path=target, status="unreadable", detail="could not be read")
    st, real = value
    if not statmod.S_ISREG(st.st_mode):
        return FileProbe(path=target, status="missing", detail="not found")
    ino = int(getattr(st, "st_ino", 0) or 0)
    return FileProbe(
        path=target,
        status="ok",
        realpath=real or target,
        dev=int(getattr(st, "st_dev", 0) or 0),
        ino=ino or None,
        size=int(st.st_size),
        mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
    )


def default_cache_path() -> Path:
    env = (os.environ.get("WIMS_LOGCHECK_CACHE") or "").strip()
    if env:
        return Path(env)
    from wims.rules.choice import config_dir
    return config_dir() / "logcheck_cache.json"


def load_cache(path: Path | str | None) -> dict:
    empty = {"version": CACHE_VERSION, "files": {}}
    if not path:
        return empty
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return empty
    files = data.get("files")
    if not isinstance(files, dict):
        return empty
    return {"version": CACHE_VERSION, "files": files}


def save_cache(path: Path | str | None, cache: dict) -> None:
    if not path:
        return
    try:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
        tmp.replace(dest)
    except OSError:
        return


def _cache_hit(entry, size: int | None, mtime_ns: int | None) -> bool:
    if not isinstance(entry, dict) or size is None or mtime_ns is None:
        return False
    try:
        return int(entry.get("size")) == int(size) and str(entry.get("mtime_ns")) == str(mtime_ns)
    except (TypeError, ValueError):
        return False


def _rows_from_cache(items, source: str) -> list[AuditQso]:
    rows = []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        when = item.get("when")
        try:
            when_f = float(when) if when is not None else None
        except (TypeError, ValueError):
            when_f = None
        grid = (item.get("grid") or "") or None
        rows.append(AuditQso(
            call=str(item.get("call") or ""),
            band=str(item.get("band") or "?"),
            mode=str(item.get("mode") or ""),
            when=when_f,
            time_text=str(item.get("time") or "?"),
            grid=grid,
            source=source,
        ))
    return rows


def _rows_to_cache(rows: list[AuditQso]) -> list[dict]:
    return [
        {
            "call": row.call,
            "band": row.band,
            "mode": row.mode,
            "when": row.when,
            "time": row.time_text,
            "grid": row.grid or "",
        }
        for row in rows
    ]


def _read_bytes(path: str, *, network: bool, timeout: float, read_bytes) -> tuple[bytes | None, str]:
    def work():
        return read_bytes(path)

    if network:
        kind, value = run_bounded(work, timeout)
        if kind == "timeout":
            return None, "timeout"
        if kind == "error":
            return None, _os_problem(value)
        return value, ""
    try:
        return work(), ""
    except Exception as exc:  # noqa: BLE001
        return None, _os_problem(exc)


def _parse_adif(data: bytes, source: str, realpath: str) -> list[AuditQso]:
    text = data.decode("utf-8", errors="replace")
    qsos = []
    for rec in read_text(text):
        qso = to_logged_qso(rec, realpath=realpath or source, source="adif")
        if qso is not None:
            qsos.append(qso)
    return qsos_from_logged(qsos, source)


def _parse_n1mm(path: str, contest_nr: int | None, source: str) -> tuple[list[AuditQso], str]:
    try:
        from wims.integrations.n1mm import logdb
        qsos = logdb.read_dxlog(path, contest_nr=contest_nr)
    except Exception:
        return [], "unreadable"
    return qsos_from_logged(qsos, source), ""


def _say(progress, message: str) -> None:
    if progress is None:
        return
    try:
        progress(message)
    except Exception:
        return


def _merged_name(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if all(label == "WSJT-X" or label.startswith("WSJT-X ") for label in labels):
        return "WSJT-X"
    return labels[0]


class _Union:
    def __init__(self, count: int):
        self.parent = list(range(count))
        self.how = [""] * count

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int, how: str) -> None:
        ra, rb = self.find(left), self.find(right)
        if ra == rb:
            if how and not self.how[ra]:
                self.how[ra] = how
            return
        self.parent[rb] = ra
        rank = {"": 0, "contents": 1, "inode": 2, "path": 3}
        best = ""
        for item in (self.how[ra], self.how[rb], how):
            if rank.get(item, 0) >= rank.get(best, 0):
                best = item
        self.how[ra] = best


def run_audit(
    candidates: list[Candidate],
    *,
    cache_path: Path | str | None = None,
    progress=None,
    stat_timeout: float = STAT_TIMEOUT_S,
    read_timeout: float = NETWORK_READ_TIMEOUT_S,
    since: str = "",
    read_bytes=None,
    stat_fn=None,
    lotw_names: set[str] | None = None,
) -> Report:
    """Read each distinct log once and compare them."""
    started = time.perf_counter()
    reader = read_bytes or (lambda path: Path(path).read_bytes())
    names = set(lotw_names or ())
    _say(progress, "Looking for logs…")

    # One probe per path string, so six radios on one dead share wait once.
    order: list[str] = []
    buckets: dict[str, list[Candidate]] = {}
    for cand in candidates:
        key = str(Path(cand.path)) if cand.path else cand.label
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(cand)

    probes: dict[str, FileProbe] = {}
    for key in order:
        group = buckets[key]
        label = group[0].label
        _say(progress, f"Checking {label}…")
        if not group[0].path:
            probes[key] = FileProbe(path="", status="missing", detail="not found")
            continue
        probes[key] = probe_path(group[0].path, timeout=stat_timeout, stat_fn=stat_fn)
        if probes[key].status == "timeout":
            _say(progress, f"{label} did not answer.")

    nodes = list(order)
    union = _Union(len(nodes))
    index = {key: i for i, key in enumerate(nodes)}
    for key, group in buckets.items():
        if len(group) >= 2:
            union.how[index[key]] = "path"

    by_real: dict[str, int] = {}
    by_inode: dict[tuple[int, int], int] = {}
    for key in nodes:
        probe = probes[key]
        if probe.status != "ok":
            continue
        i = index[key]
        if probe.realpath:
            prev = by_real.get(probe.realpath)
            if prev is None:
                by_real[probe.realpath] = i
            else:
                union.union(prev, i, "path")
        if probe.ino:
            ident = (probe.dev or 0, probe.ino)
            prev = by_inode.get(ident)
            if prev is None:
                by_inode[ident] = i
            else:
                union.union(prev, i, "inode")

    members: dict[int, list[str]] = {}
    for key in nodes:
        members.setdefault(union.find(index[key]), []).append(key)

    groups: list[_Group] = []
    for root, keys in members.items():
        labels: list[str] = []
        kind = "adif"
        contest_nr = None
        path = ""
        probe = probes[keys[0]]
        ok_probes: list[FileProbe] = []
        for key in keys:
            for cand in buckets[key]:
                labels.append(cand.label)
                if cand.kind == "n1mm":
                    kind = "n1mm"
                    contest_nr = cand.contest_nr
                elif cand.kind == "lotw" and kind != "n1mm":
                    kind = "lotw"
                if cand.path and not path:
                    path = cand.path
            if probes[key].status == "ok":
                probe = probes[key]
                path = probes[key].path or path
                ok_probes.append(probes[key])
        how = union.how[root]
        if len(labels) >= 2 and how in {"path", "inode"}:
            rest = ", ".join(labels[1:])
            _say(progress, f"{rest} is the same file as {labels[0]}.")
        groups.append(_Group(
            labels=labels,
            path=path,
            kind=kind,
            contest_nr=contest_nr,
            probe=probe,
            probes=ok_probes,
            how=how if len(labels) >= 2 else "",
        ))

    cache = load_cache(cache_path)
    cache_files = cache["files"]
    dirty = False

    for group in groups:
        if group.probe.status != "ok":
            group.problem = group.probe.status
            continue
        name = _merged_name(group.labels)
        key = group.probe.realpath or group.path
        entry = cache_files.get(key)
        if _cache_hit(entry, group.probe.size, group.probe.mtime_ns):
            group.cached = True
            group.digest = (entry.get("digest") or None) if isinstance(entry, dict) else None
            group.rows = _rows_from_cache(entry.get("qsos") if isinstance(entry, dict) else None, name)
            _say(progress, f"{name} has not changed, so it was not read again.")
            continue
        _say(progress, f"Reading {name}…")
        if group.kind == "n1mm":
            network = is_network_path(group.path)
            if network:
                kind, value = run_bounded(
                    lambda g=group: _parse_n1mm(g.path, g.contest_nr, name),
                    read_timeout,
                )
                if kind == "timeout":
                    group.problem = "timeout"
                    _say(progress, f"{name} did not answer.")
                    continue
                if kind == "error":
                    group.problem = "unreadable"
                    continue
                rows, problem = value
            else:
                rows, problem = _parse_n1mm(group.path, group.contest_nr, name)
            if problem:
                group.problem = problem
                continue
            group.rows = rows
            cache_files[key] = {
                "size": group.probe.size,
                "mtime_ns": str(group.probe.mtime_ns),
                "digest": "",
                "qsos": _rows_to_cache(rows),
            }
            dirty = True
            continue
        network = is_network_path(group.path)
        data, problem = _read_bytes(
            group.path, network=network, timeout=read_timeout, read_bytes=reader,
        )
        if problem:
            group.problem = problem
            if problem == "timeout":
                _say(progress, f"{name} did not answer.")
            continue
        group.data = data or b""
        group.digest = hashlib.sha256(group.data).hexdigest()

    # Identical ADIF bytes are one log even when the paths differ.
    by_digest: dict[str, _Group] = {}
    merged_away: set[int] = set()
    for i, group in enumerate(groups):
        if group.problem or group.kind == "n1mm" or not group.digest:
            continue
        prior = by_digest.get(group.digest)
        if prior is None:
            by_digest[group.digest] = group
            continue
        rest = ", ".join(group.labels)
        _say(progress, f"{rest} matches {prior.labels[0]} byte for byte, so it is counted once.")
        prior.labels.extend(group.labels)
        prior.probes.extend(group.probes)
        if prior.how not in {"path", "inode"}:
            prior.how = "contents"
        if prior.kind == "lotw" and group.kind != "lotw":
            prior.kind = group.kind
        if not prior.rows and group.rows:
            prior.rows = group.rows
            prior.cached = group.cached
        if prior.data is None and group.data is not None:
            prior.data = group.data
        merged_away.add(i)

    kept_groups = [group for i, group in enumerate(groups) if i not in merged_away]
    for group in kept_groups:
        if group.problem or group.rows or group.kind == "n1mm":
            continue
        if group.data is None:
            continue
        name = _merged_name(group.labels)
        group.rows = _parse_adif(group.data, name, group.probe.realpath or group.path)
    for group in kept_groups:
        if group.problem or not group.rows or group.kind == "n1mm":
            continue
        if group.cached and len(group.probes) <= 1:
            continue
        for probe in group.probes or [group.probe]:
            if probe.status != "ok" or probe.size is None or probe.mtime_ns is None:
                continue
            key = probe.realpath or probe.path
            if not key:
                continue
            cache_files[key] = {
                "size": probe.size,
                "mtime_ns": str(probe.mtime_ns),
                "digest": group.digest or "",
                "qsos": _rows_to_cache(group.rows),
            }
            dirty = True

    if dirty:
        save_cache(cache_path, cache)

    _say(progress, "Comparing the logs…")
    paired: list[tuple[SourceInfo, list[AuditQso]]] = []
    for group in kept_groups:
        name = _merged_name(group.labels)
        shared = list(group.labels) if len(group.labels) >= 2 else []
        info = SourceInfo(
            name=name,
            path=group.probe.realpath or group.path,
            shared_by=shared,
            cached=group.cached,
            identity=group.how if shared else "",
        )
        if group.problem == "timeout" or group.probe.status == "timeout":
            info.status = "timeout"
            info.detail = group.probe.detail or (
                "Did not answer within 2 seconds. Connect that drive and check again."
            )
            paired.append((info, []))
            continue
        if group.problem == "locked" or group.probe.status == "locked":
            info.status = "locked"
            info.detail = group.probe.detail or "Another program has this file open, so it could not be read."
            paired.append((info, []))
            continue
        if group.problem or group.probe.status != "ok":
            info.status = "unreadable"
            info.detail = group.probe.detail or "could not be read"
            paired.append((info, []))
            continue
        for row in group.rows:
            row.source = name
        rows = filter_since(group.rows, since)
        info.count = len(rows)
        info.status = "ok"
        info.detail = "1 contact" if info.count == 1 else f"{info.count} contacts"
        if group.kind == "lotw":
            names.add(name)
        paired.append((info, rows))

    report = compare(paired, lotw_names=names)
    if since:
        report.window = f"since {since}"
    report.elapsed_s = time.perf_counter() - started
    _say(progress, "Done.")
    return report
