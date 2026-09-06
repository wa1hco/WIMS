# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse N1MM RadioInfo UDP XML -> band label.

N1MM Broadcast Data -> Radio sends <RadioInfo> with <Freq>/<TXFreq> in
10 Hz units (e.g. 5012345 -> 50.12345 MHz). See N1MM External UDP Broadcasts.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from wims.core.bands import band_label


def n1mm_freq_units_to_hz(raw: str | int | float) -> int | None:
    """Convert N1MM RadioInfo frequency units (10 Hz) to Hz."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n * 10


def band_from_radioinfo_xml(text: str) -> tuple[str | None, dict]:
    """Return (band_label_or_None, meta) from one UDP datagram.

    meta may include freq_hz, mode, radio_nr, active_radio_nr, raw_freq.
    Non-RadioInfo packets return (None, {}).
    """
    text = (text or "").strip()
    if not text or "RadioInfo" not in text:
        return None, {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None, {}
    tag = (root.tag or "").split("}")[-1]
    if tag.lower() != "radioinfo":
        return None, {}

    def child(name: str) -> str | None:
        for c in root:
            if (c.tag or "").split("}")[-1].lower() == name.lower():
                if c.text and c.text.strip():
                    return c.text.strip()
        return None

    radio_nr = child("RadioNr")
    active = child("ActiveRadioNr")
    raw = child("TXFreq") or child("Freq")
    hz = n1mm_freq_units_to_hz(raw) if raw else None
    meta = {
        "freq_hz": hz,
        "raw_freq": raw,
        "mode": child("Mode"),
        "radio_nr": radio_nr,
        "active_radio_nr": active,
        "station": child("StationName"),
        "netbios": child("NetBiosName"),
    }
    if hz is None:
        return None, meta
    return band_label(hz), meta


def radioinfo_ignore_reason(
    meta: dict,
    *,
    hostname: str = "",
    filter_station: bool = False,
) -> str | None:
    """Why this RadioInfo must not drive live_band, or None to accept.

    Inactive SO2R/SO2V radios (RadioNr != ActiveRadioNr) still beacon their
    VFO — using them makes the log filter flip-flop. When listening on
    multicast, StationName / NetBiosName must match this PC or we hear
    every logger on the LAN.
    """
    radio_nr = str(meta.get("radio_nr") or "").strip()
    active = str(meta.get("active_radio_nr") or "").strip()
    if radio_nr and active and radio_nr != active:
        return "inactive_radio"
    if filter_station:
        station = (
            str(meta.get("station") or "").strip()
            or str(meta.get("netbios") or "").strip()
        )
        host = (hostname or "").strip()
        if station and host and station.lower() != host.lower():
            return "other_station"
    return None
