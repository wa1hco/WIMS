"""Unified logged-QSO record from N1MM's two feeds (plan §3.6).

Both the live `<contactinfo>` UDP broadcast and the `DXLOG` rows of N1MM's `.s3db`
describe the same QSO with the same field names and the same unique `ID`, so they
collapse to one `LoggedQso`. The DB read seeds the log copy at cold start; the
broadcast keeps it live; both dedup on `id`.
"""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from wims.core.bands import band_label_mhz

_FALSEY = {"", "0", "false", "no", "n"}


def _truthy(v) -> bool:
    return str(v).strip().lower() not in _FALSEY


def _grid(v) -> str | None:
    s = (str(v) if v is not None else "").strip().upper()
    return s or None


def _band(v) -> str:
    try:
        return band_label_mhz(float(v))
    except (TypeError, ValueError):
        return "?"


@dataclass
class LoggedQso:
    id: str
    call: str
    band: str            # normalized label, e.g. "20m"
    grid: str | None
    mode: str | None
    points: int
    is_mult: bool        # any of N1MM's ismultiplier1/2/3
    contest: str | None
    timestamp: str | None
    operator: str | None
    rover_location: str | None
    source: str          # "seed" (DB) or "live" (broadcast)

    @classmethod
    def _from_dict(cls, d: dict, source: str) -> "LoggedQso":
        """d has lowercased keys from either feed."""
        return cls(
            id=str(d.get("id") or "").strip(),
            call=(d.get("call") or "").strip().upper(),
            band=_band(d.get("band")),
            grid=_grid(d.get("gridsquare")),
            mode=(d.get("mode") or None),
            points=int(float(d.get("points") or 0)),
            is_mult=any(_truthy(d.get(k)) for k in
                        ("ismultiplier1", "ismultiplier2", "ismultiplier3")),
            contest=(d.get("contestname") or None),
            timestamp=(d.get("timestamp") or d.get("ts") or None),
            operator=(d.get("operator") or None),
            rover_location=(d.get("roverlocation") or None),
            source=source,
        )

    @classmethod
    def from_contactinfo(cls, xml_text: str) -> "LoggedQso":
        root = ET.fromstring(xml_text)
        d = {c.tag.lower(): (c.text or "").strip() for c in root}
        return cls._from_dict(d, source="live")

    @classmethod
    def from_dxlog_row(cls, row: dict) -> "LoggedQso":
        d = {str(k).lower(): v for k, v in row.items()}
        return cls._from_dict(d, source="seed")
