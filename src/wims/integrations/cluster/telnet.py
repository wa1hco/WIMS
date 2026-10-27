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

"""Just enough telnet to read a cluster.

``telnetlib`` is not in Python 3.13. Nodes send option bytes before the
text. WIMS refuses every option (WONT / DONT) so the session stays plain
text. Those refusals are the telnet handshake, not cluster commands.
The only text WIMS sends is the callsign, and only as the login.
"""

from __future__ import annotations

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240


def strip_telnet(data: bytes, reply: bytearray, state: dict) -> bytes:
    """Drop telnet bytes. Append refusals to ``reply``. ``state`` is the carry."""
    out = bytearray()
    st = int(state.get("st") or 0)
    pending = int(state.get("cmd") or 0)
    for byte in data:
        if st == 0:
            if byte == IAC:
                st = 1
            else:
                out.append(byte)
        elif st == 1:
            if byte == IAC:
                out.append(IAC)
                st = 0
            elif byte in (WILL, WONT, DO, DONT):
                pending = byte
                st = 2
            elif byte == SB:
                st = 3
            else:
                st = 0
        elif st == 2:
            if pending == DO:
                reply.extend((IAC, WONT, byte))
            elif pending == WILL:
                reply.extend((IAC, DONT, byte))
            st = 0
        elif st == 3:
            st = 4 if byte == IAC else 3
        else:
            st = 0 if byte == SE else 3
    state["st"] = st
    state["cmd"] = pending
    return bytes(out)


def plaintext(data: bytes) -> str:
    """Telnet bytes removed, so a test can see the text we actually sent."""
    return strip_telnet(data, bytearray(), {}).decode("latin-1", "replace")
