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

"""Pluggable log backends for Operate / LogStore (design §3.6).

Engine code depends on ``LoggedQso`` + ``LogSource``, not on N1MM or ADIF details.
See ``docs/plan/wims_log_source_survey.md``.
"""

from wims.integrations.logsource.base import (
    LogEvent,
    LogSource,
    LogSourceCandidate,
)
from wims.integrations.logsource.n1mm_source import N1mmLogSource

__all__ = [
    "LogEvent",
    "LogSource",
    "LogSourceCandidate",
    "N1mmLogSource",
]
