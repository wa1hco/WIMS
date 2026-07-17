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

"""WIMS host agent — local seat config/network checks + optional export to site server.

Local-first: the station operator can verify WSJT-X / N1MM settings on this PC
without a site server. Default CLI is **one-shot** (print and exit). Continuous
dashboard reporting uses ``--daemon`` / Start-WimsAgent-Continuous.cmd.

Not the site server. Not a TX controller. Fast mute / leases come later.
"""

from wims.agent.report import build_report

__all__ = ["build_report"]
