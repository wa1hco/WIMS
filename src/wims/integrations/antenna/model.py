# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Device kinds on an antenna.

An antenna has a name and a list of devices. This step reads only
``rotator`` (hamlib rotctld, heading only). The other kinds are named so
the same list can grow. Nothing here opens a port or sends a command.

* ``rotator`` — azimuth and elevation. rotctld ``p`` only.
* ``tuner`` — a frequency-tuned antenna. The station's SteppIR controller
  is USB serial on the antenna PC. A later step has the antenna agent on
  that PC own that serial port: read frequency and state, then follow the
  radio. Not built.
* ``switch`` — antenna selection. Not built.
"""

from __future__ import annotations

KIND_ROTATOR = "rotator"
KIND_TUNER = "tuner"
KIND_SWITCH = "switch"

DEVICE_KINDS = (KIND_ROTATOR, KIND_TUNER, KIND_SWITCH)

# Kinds this step actually reads. Tuner and switch stay in DEVICE_KINDS
# so a later reader can register without changing the antenna list.
IMPLEMENTED_KINDS = frozenset({KIND_ROTATOR})


def unread_device(dev: dict) -> dict:
    """A device this step does not read. No session is opened."""
    kind = str(dev.get("kind") or "").strip().lower()
    return {
        "id": str(dev.get("id") or ""),
        "kind": kind,
        "az": None,
        "el": None,
        "link": "down",
        "link_ok": False,
        "connection": "stale",
        "health": "STALE",
        "moving": False,
        "detail": "Not read yet.",
    }


def public_device(dev: dict) -> dict | None:
    """Console view of one device. Host, port, and serial path are omitted."""
    if not isinstance(dev, dict):
        return None
    kind = str(dev.get("kind") or KIND_ROTATOR).strip().lower()
    if kind not in DEVICE_KINDS:
        kind = str(dev.get("kind") or "")
    connected = (
        kind == KIND_ROTATOR
        and dev.get("connection") == "connected"
        and dev.get("az") is not None
    )
    el = dev.get("el") if connected else None
    try:
        el_out = None if el is None else float(el)
    except (TypeError, ValueError):
        el_out = None
    try:
        az_out = float(dev["az"]) if connected else None
    except (TypeError, ValueError):
        az_out = None
        connected = False
    return {
        "id": str(dev.get("id") or ""),
        "kind": kind,
        "az": az_out,
        "el": el_out,
        "link": "up" if connected else "down",
        "link_ok": connected,
        "connection": "connected" if connected else "stale",
        "health": "OK" if connected else str(dev.get("health") or "STALE"),
        "moving": False,
        "detail": "" if connected else str(dev.get("detail") or (
            "Heading unknown." if kind == KIND_ROTATOR else "Not read yet."
        )),
    }


def public_antennas(items: list | None) -> list[dict]:
    """Antennas safe to put on the live state. No address and no serial path."""
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        devices = []
        for dev in raw.get("devices") or []:
            pub = public_device(dev)
            if pub:
                devices.append(pub)
        name = " ".join(str(raw.get("name") or "").split()) or "Antenna"
        out.append({
            "id": str(raw.get("id") or name),
            "name": name,
            "devices": devices,
        })
    return out
