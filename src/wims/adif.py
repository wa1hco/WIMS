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

"""Length-aware ADIF reader.

WIMS only reads logs. This module never writes an ADIF file. The parser is
independent of ``wims.log`` (that package inserts into N1MM).
"""

from __future__ import annotations

import errno
from datetime import date, datetime, timezone
from pathlib import Path

from wims.core.bands import band_label_mhz
from wims.integrations.n1mm.qso import LoggedQso


def iter_records(text: str):
    """Yield ADIF records as ``{tag_lower: value}`` dicts.

    Honors ``<TAG:N>`` and ``<TAG:N:TYPE>``. Text before ``<EOH>`` is a header.
    A ``<`` inside a counted value is data, not a new tag.
    """
    if not text:
        return
    lower = text.lower()
    eoh = lower.find("<eoh>")
    i = 0
    if eoh >= 0:
        i = eoh + 5
    else:
        # <eoh:0> and similar counted forms.
        marker = lower.find("<eoh:")
        if marker >= 0:
            end = text.find(">", marker)
            i = end + 1 if end >= 0 else 0
    n = len(text)
    rec: dict[str, str] = {}
    while i < n:
        if text[i] != "<":
            i += 1
            continue
        end = text.find(">", i + 1)
        if end < 0:
            break
        body = text[i + 1:end]
        i = end + 1
        parts = body.split(":")
        name = parts[0].strip().lower()
        if not name:
            continue
        if name in ("eoh", "eor"):
            if name == "eor" and rec:
                yield rec
                rec = {}
            continue
        length = 0
        if len(parts) >= 2:
            try:
                length = int(parts[1].strip() or "0")
            except ValueError:
                length = 0
        if length < 0:
            length = 0
        value = text[i:i + length]
        i += length
        rec[name] = value
    # A file that omits the final <eor> still has one record if tags were seen.
    if rec:
        yield rec


def read_text(text: str) -> list[dict[str, str]]:
    return list(iter_records(text))


def read_path(path: str | Path) -> tuple[list[dict[str, str]], str | None]:
    """Return ``(records, problem)``. ``problem`` is ``locked`` or ``unreadable``."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return [], "locked"
    except OSError as exc:
        win = getattr(exc, "winerror", None)
        if win in (32, 33) or exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
            return [], "locked"
        return [], "unreadable"
    return read_text(text), None


def mode_of(fields: dict[str, str]) -> str:
    """Submode wins when both are present (FT8 and FT4 stay distinct)."""
    sub = (fields.get("submode") or "").strip()
    mode = (fields.get("mode") or "").strip()
    return (sub or mode).upper()


def band_of(fields: dict[str, str]) -> str:
    """ADIF ``BAND`` when it already looks like a WIMS label, else ``FREQ`` MHz."""
    raw = (fields.get("band") or "").strip()
    if raw:
        label = raw.lower().replace(" ", "")
        # 6M / 70CM / 1.25M → the labels the roster already uses.
        if label.endswith("m") or label.endswith("cm"):
            return label
    freq = (fields.get("freq") or "").strip()
    if freq:
        try:
            return band_label_mhz(float(freq))
        except ValueError:
            pass
    return raw.lower() or "?"


def record_id(fields: dict[str, str], realpath: str) -> str:
    """One id for a file row and the UDP logged-QSO of the same contact."""
    call = (fields.get("call") or "").strip().upper()
    date = (fields.get("qso_date") or "").strip()
    tim = (fields.get("time_on") or "").strip()
    return (
        f"wsjtx|{realpath}|{date}|{tim}|{call}|{band_of(fields)}|{mode_of(fields)}"
    )


def qso_time(fields: dict[str, str]) -> tuple[str, float | None]:
    """``(display, utc epoch)`` from ``QSO_DATE`` + ``TIME_ON``. Epoch is None if unparsable."""
    d = (fields.get("qso_date") or "").strip()
    t = (fields.get("time_on") or "").strip().replace(":", "")
    if len(t) == 4:
        t = t + "00"
    if len(d) >= 8 and len(t) >= 4:
        text = f"{d[0:4]}-{d[4:6]}-{d[6:8]} {t[0:2]}:{t[2:4]}"
        if len(t) >= 6:
            text += f":{t[4:6]}"
    else:
        text = (d + " " + t).strip() or "?"
    if len(d) < 8 or len(t) < 6:
        return text, None
    try:
        dt = datetime.strptime(d[:8] + t[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return text, None
    return text, dt.timestamp()


def qt_datetime_to_adif(dt: dict | None) -> tuple[str, str]:
    """``(QSO_DATE yyyymmdd, TIME_ON hhmmss)`` from a WSJT-X QDateTime dict."""
    if not dt:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    try:
        d = date.fromordinal(int(dt["julian_day"]) - 1721425)
    except (ValueError, OverflowError, KeyError, TypeError):
        d = datetime.now(timezone.utc).date()
    msecs = int(dt.get("msecs") or 0)
    hh = (msecs // 3_600_000) % 24
    mm = (msecs // 60_000) % 60
    ss = (msecs // 1000) % 60
    return d.strftime("%Y%m%d"), f"{hh:02d}{mm:02d}{ss:02d}"


def _grid(value: str | None) -> str | None:
    s = (value or "").strip().upper()
    return s or None


def to_logged_qso(
    fields: dict[str, str],
    *,
    realpath: str,
    source: str = "adif",
) -> LoggedQso | None:
    """Build a log-copy row. A record with no call is ignored."""
    call = (fields.get("call") or "").strip().upper()
    if not call:
        return None
    mode = mode_of(fields)
    sub = (fields.get("submode") or "").strip().upper() or None
    text, epoch = qso_time(fields)
    ts = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if epoch else text
    dxcc = (fields.get("dxcc") or "").strip() or None
    return LoggedQso(
        id=record_id(fields, realpath),
        call=call,
        band=band_of(fields),
        grid=_grid(fields.get("gridsquare")),
        mode=mode or None,
        points=0,
        is_mult=False,
        contest=(fields.get("contest_id") or None),
        timestamp=ts,
        operator=(fields.get("operator") or fields.get("station_callsign") or None),
        rover_location=None,
        source=source,
        submode=sub,
        qso_date=(fields.get("qso_date") or "").strip() or None,
        time_on=(fields.get("time_on") or "").strip() or None,
        exchange=(
            (fields.get("srx_string") or fields.get("county") or fields.get("state") or "").strip()
            or None
        ),
        state=(fields.get("state") or "").strip().upper() or None,
        my_state=(fields.get("my_state") or "").strip().upper() or None,
        my_county=(fields.get("my_county") or fields.get("my_cnty") or "").strip().upper() or None,
        dxcc=dxcc,
        contest_id=(fields.get("contest_id") or "").strip() or None,
        cqz=(fields.get("cqz") or "").strip() or None,
        ituz=(fields.get("ituz") or "").strip() or None,
        cont=(fields.get("cont") or "").strip().upper() or None,
    )


def load_qsos(path: str | Path, *, source: str = "adif") -> tuple[list[LoggedQso], str | None]:
    """Read one ADIF file into log-copy rows. Same id collapses duplicates."""
    p = Path(path)
    try:
        real = str(p.resolve())
    except OSError:
        real = str(p)
    records, problem = read_path(p)
    if problem:
        return [], problem
    out: list[LoggedQso] = []
    seen: set[str] = set()
    for rec in records:
        q = to_logged_qso(rec, realpath=real, source=source)
        if q is None or q.id in seen:
            continue
        seen.add(q.id)
        out.append(q)
    return out, None
