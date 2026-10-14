# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Slim seat-profile.json reader/writer for home H2 (TX-capable marks).

File location (same as shared-trx design):

  * Windows: ``%LOCALAPPDATA%\\WIMS\\seat-profile.json``
  * Linux / macOS: ``~/.local/share/wims/seat-profile.json``

H2 uses only ``station_class`` and ``wsjt_instances[{id, tx_capable, rf_path}]``.
Unset ``tx_capable`` means **true** (fleet-safe default). CAT fields may exist
in the same file later; this module leaves unknown keys intact on save.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SHARED_TRX_CLASSES = frozenset({
    "shared_trx_second_rx",
    "shared_trx_dual_rx",
})

VALID_RF_PATHS = frozenset({"trx", "sdr_rx"})


@dataclass(frozen=True)
class WsjtInstanceMark:
    """One WSJT-X id mark from the seat profile."""

    id: str
    tx_capable: bool = True
    rf_path: str | None = None
    modes: tuple[str, ...] = ()


@dataclass
class SeatProfile:
    """Loaded seat profile (missing file → empty, all instances TX-capable)."""

    path: Path
    exists: bool = False
    station_class: str | None = None
    instances: dict[str, WsjtInstanceMark] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def is_shared_trx(self) -> bool:
        return (self.station_class or "") in SHARED_TRX_CLASSES

    def tx_capable(self, instance_id: str) -> bool:
        """Unset mark → True. Explicit false → False."""
        mark = self.instances.get(instance_id or "")
        if mark is None:
            return True
        return bool(mark.tx_capable)

    def rf_path(self, instance_id: str) -> str | None:
        mark = self.instances.get(instance_id or "")
        return mark.rf_path if mark else None

    def mark_for(self, instance_id: str) -> WsjtInstanceMark | None:
        return self.instances.get(instance_id or "")

    def checks(self, *, live_ids: list[str] | None = None) -> list[dict[str, str]]:
        """Config check rows for Setup / solo. severity: info | warn | error."""
        out: list[dict[str, str]] = []
        marks = list(self.instances.values())
        tx_marks = [m for m in marks if m.tx_capable]
        decode_marks = [m for m in marks if not m.tx_capable]

        if not self.exists:
            out.append({
                "severity": "info",
                "code": "no_profile",
                "detail": (
                    f"No seat profile at {self.path}. "
                    "All live instances stay TX-capable until you mark them."
                ),
            })
            return out

        if self.station_class and self.station_class not in SHARED_TRX_CLASSES:
            if self.station_class not in ("dual_radio", "single_radio", ""):
                out.append({
                    "severity": "warn",
                    "code": "unknown_class",
                    "detail": f"Unknown station_class {self.station_class!r}.",
                })

        if self.is_shared_trx():
            if len(tx_marks) == 0:
                out.append({
                    "severity": "error",
                    "code": "no_tx_capable",
                    "detail": (
                        f"{self.station_class}: need exactly one "
                        "tx_capable instance."
                    ),
                })
            elif len(tx_marks) > 1:
                ids = ", ".join(m.id for m in tx_marks)
                out.append({
                    "severity": "error",
                    "code": "many_tx_capable",
                    "detail": (
                        f"{self.station_class}: need exactly one "
                        f"tx_capable instance; marked TX: {ids}."
                    ),
                })
            else:
                out.append({
                    "severity": "info",
                    "code": "one_tx_capable",
                    "detail": f"TX-capable instance: {tx_marks[0].id}.",
                })
            for m in tx_marks:
                if m.rf_path and m.rf_path != "trx":
                    out.append({
                        "severity": "warn",
                        "code": "tx_rf_path",
                        "detail": (
                            f"{m.id}: TX-capable usually uses rf_path=trx "
                            f"(now {m.rf_path!r})."
                        ),
                    })
            for m in decode_marks:
                if m.rf_path and m.rf_path != "sdr_rx":
                    out.append({
                        "severity": "warn",
                        "code": "decode_rf_path",
                        "detail": (
                            f"{m.id}: decode-only usually uses rf_path=sdr_rx "
                            f"(now {m.rf_path!r})."
                        ),
                    })
        elif marks:
            if len(tx_marks) == 0 and decode_marks:
                out.append({
                    "severity": "warn",
                    "code": "all_decode_only",
                    "detail": (
                        "Every marked instance is decode-only. "
                        "Work and Inhibit need one TX-capable id."
                    ),
                })
            elif len(tx_marks) > 1:
                ids = ", ".join(m.id for m in tx_marks)
                out.append({
                    "severity": "info",
                    "code": "multi_tx_ok",
                    "detail": (
                        f"Multiple TX-capable marks ({ids}). "
                        "OK for dual-radio; for one-TRX dual RX set "
                        "station_class and keep one TX."
                    ),
                })

        if live_ids is not None:
            live = [i for i in live_ids if i]
            marked = set(self.instances)
            for iid in live:
                if iid not in marked and len(live) > 1:
                    out.append({
                        "severity": "warn",
                        "code": "unmarked_live",
                        "detail": (
                            f"Live instance {iid!r} has no mark "
                            "(treated as TX-capable)."
                        ),
                    })
            for iid in sorted(marked - set(live)):
                out.append({
                    "severity": "info",
                    "code": "marked_offline",
                    "detail": f"Marked instance {iid!r} is not live yet.",
                })

        return out

    def to_public_dict(self, *, live_ids: list[str] | None = None) -> dict[str, Any]:
        inst = [
            {
                "id": m.id,
                "tx_capable": m.tx_capable,
                "rf_path": m.rf_path,
                "modes": list(m.modes),
            }
            for m in sorted(self.instances.values(), key=lambda x: x.id)
        ]
        return {
            "path": str(self.path),
            "exists": self.exists,
            "station_class": self.station_class,
            "instances": inst,
            "checks": self.checks(live_ids=live_ids),
        }


def default_seat_profile_path() -> Path:
    """Platform path for the live seat-profile.json."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "WIMS" / "seat-profile.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "wims" / "seat-profile.json"
    return Path.home() / ".local" / "share" / "wims" / "seat-profile.json"


def _parse_instance(entry: Any) -> WsjtInstanceMark | None:
    if not isinstance(entry, dict):
        return None
    iid = str(entry.get("id") or "").strip()
    if not iid:
        return None
    tx = entry.get("tx_capable", True)
    if isinstance(tx, str):
        tx = tx.strip().lower() not in ("0", "false", "no", "off")
    else:
        tx = bool(tx)
    rf = entry.get("rf_path")
    rf_s = str(rf).strip() if rf else None
    if rf_s == "":
        rf_s = None
    if rf_s and rf_s not in VALID_RF_PATHS:
        # Keep value for checks; do not invent a substitute.
        pass
    modes_raw = entry.get("modes") or []
    modes: tuple[str, ...] = ()
    if isinstance(modes_raw, list):
        modes = tuple(str(m) for m in modes_raw if m)
    return WsjtInstanceMark(id=iid, tx_capable=tx, rf_path=rf_s, modes=modes)


def load_seat_profile(path: Path | None = None) -> SeatProfile:
    """Load profile from disk. Missing or invalid file → empty profile."""
    p = Path(path) if path is not None else default_seat_profile_path()
    profile = SeatProfile(path=p)
    if not p.is_file():
        return profile
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        profile.exists = True
        profile.raw = {}
        return profile
    if not isinstance(raw, dict):
        profile.exists = True
        return profile
    profile.exists = True
    profile.raw = dict(raw)
    sc = raw.get("station_class")
    profile.station_class = str(sc).strip() if sc else None
    if profile.station_class == "":
        profile.station_class = None
    by_id: dict[str, WsjtInstanceMark] = {}
    for entry in raw.get("wsjt_instances") or []:
        mark = _parse_instance(entry)
        if mark is not None:
            by_id[mark.id] = mark
    profile.instances = by_id
    return profile


def save_seat_profile_marks(
    *,
    path: Path | None = None,
    station_class: str | None = None,
    instances: list[dict[str, Any]] | None = None,
    clear_missing: bool = False,
) -> SeatProfile:
    """Merge H2 marks into seat-profile.json. Preserve unknown keys.

    ``instances`` is a list of ``{id, tx_capable, rf_path?}``.
    When ``clear_missing`` is False (default), ids not listed stay as-is.
    When True, ``wsjt_instances`` becomes exactly the listed set.
    """
    p = Path(path) if path is not None else default_seat_profile_path()
    current = load_seat_profile(p)
    raw = dict(current.raw) if current.raw else {}

    if station_class is not None:
        sc = str(station_class).strip()
        if sc:
            raw["station_class"] = sc
        else:
            raw.pop("station_class", None)

    existing_list = list(raw.get("wsjt_instances") or [])
    by_id: dict[str, dict[str, Any]] = {}
    for entry in existing_list:
        if isinstance(entry, dict) and entry.get("id"):
            by_id[str(entry["id"]).strip()] = dict(entry)

    if instances is not None:
        if clear_missing:
            by_id = {}
        for entry in instances:
            if not isinstance(entry, dict):
                continue
            iid = str(entry.get("id") or "").strip()
            if not iid:
                continue
            row = dict(by_id.get(iid) or {"id": iid})
            row["id"] = iid
            if "tx_capable" in entry:
                row["tx_capable"] = bool(entry["tx_capable"])
            elif "tx_capable" not in row:
                row["tx_capable"] = True
            if "rf_path" in entry:
                rf = entry.get("rf_path")
                if rf is None or str(rf).strip() == "":
                    row.pop("rf_path", None)
                else:
                    row["rf_path"] = str(rf).strip()
            elif "rf_path" not in row:
                # Default path from capability when newly created.
                row["rf_path"] = "trx" if row.get("tx_capable", True) else "sdr_rx"
            by_id[iid] = row

    raw["wsjt_instances"] = sorted(by_id.values(), key=lambda r: str(r.get("id") or ""))

    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(raw, indent=2, sort_keys=False) + "\n"
    p.write_text(text, encoding="utf-8")
    return load_seat_profile(p)


def format_checks(checks: list[dict[str, str]]) -> str:
    """Plain-text lines for solo / CLI."""
    if not checks:
        return "seat profile: ok"
    lines = []
    for c in checks:
        sev = (c.get("severity") or "info").upper()
        lines.append(f"seat profile [{sev}] {c.get('detail') or c.get('code')}")
    return "\n".join(lines)
