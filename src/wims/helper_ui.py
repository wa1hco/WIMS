# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compatibility shim — use ``wims.agent_ui`` (AgentStatus*)."""

from __future__ import annotations

from wims.agent_ui import (  # noqa: F401
    AgentStatusModel as HelperStatusModel,
    AgentStatusWindow as HelperStatusWindow,
)
