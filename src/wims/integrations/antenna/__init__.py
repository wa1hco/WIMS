# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Antenna agent model: one antenna, a list of typed devices (plan §2.10)."""

from wims.integrations.antenna.model import (
    DEVICE_KINDS,
    IMPLEMENTED_KINDS,
    KIND_ROTATOR,
    KIND_SWITCH,
    KIND_TUNER,
)

__all__ = [
    "DEVICE_KINDS",
    "IMPLEMENTED_KINDS",
    "KIND_ROTATOR",
    "KIND_SWITCH",
    "KIND_TUNER",
]
