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

"""Parser tests against real captured WSJT-X datagrams (captures/).

The hex fixtures below are taken verbatim from a live multicast capture
(captures/wsjtx-20260616-221551.jsonl) on a 6 m FT8 instance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as m  # noqa: E402

HEARTBEAT = bytes.fromhex(
    "adbccbda00000002000000000000000657534a542d58"
    "0000000300000005332e302e3000000006616239373662"
)
STATUS = bytes.fromhex(
    "adbccbda00000002000000010000000657534a542d580000000002ffb728"
    "00000003465438000000054b3447444a000000032d31350000000346543800"
    "0001000005dc000003600000000657413148434f00000006464e3432455600"
    "000004454c393800ffffffff0000ffffffffffffffff0000000744656661756c74ffffffff"
)
DECODE = bytes.fromhex(
    "adbccbda00000002000000020000000657534a542d5801007c4868000000143f"
    "c99999a00000000000031b000000017e0000000c4351204e4a314820464e34320000"
)


def test_heartbeat():
    msg = m.parse(HEARTBEAT)
    assert isinstance(msg, m.Heartbeat)
    assert msg.id == "WSJT-X"
    assert msg.version == "3.0.0"
    assert msg.max_schema == 3


def test_status():
    msg = m.parse(STATUS)
    assert isinstance(msg, m.Status)
    assert msg.dial_frequency == 50_313_000  # 50.313 MHz, 6 m
    assert msg.mode == "FT8"
    assert msg.dx_call == "K4GDJ"
    assert msg.report == "-15"
    assert msg.de_call == "WA1HCO"
    assert msg.de_grid == "FN42EV"
    assert msg.dx_grid == "EL98"
    assert msg.rx_df == 1500
    assert msg.tx_df == 864
    assert msg.config_name == "Default"
    assert msg.tx_enabled is False
    assert msg.frequency_tolerance is None  # 0xFFFFFFFF -> N/A


def test_decode_and_grid():
    msg = m.parse(DECODE)
    assert isinstance(msg, m.Decode)
    assert msg.new is True
    assert msg.snr == 20
    assert abs(msg.delta_time - 0.2) < 1e-6
    assert msg.delta_frequency == 795
    assert msg.mode == "~"  # FT8
    assert msg.message == "CQ NJ1H FN42"
    assert msg.is_cq is True
    assert msg.dx_call == "NJ1H"
    assert msg.to_call == "CQ"     # "calling" column: a CQ addresses CQ
    assert msg.grid == "FN42"  # the rover/mult-critical field


def test_interpret_exchange_to_and_from():
    is_cq, dx_call, to_call, grid = m._interpret_decode("WA1HCO K1ABC -05")
    assert is_cq is False
    assert dx_call == "K1ABC"      # station of interest (the one transmitting)
    assert to_call == "WA1HCO"     # who it is calling


def test_qsy_message_system_in_calling_column():
    """WSJT-X 2.7+ Message System QSY → target in DX, QSY label in Calling."""
    is_cq, dx, to, grid = m._interpret_decode("WA9BTV. EL 174")
    assert is_cq is False
    assert dx == "WA9BTV"
    assert to == "QSY 1296.174"
    assert grid is None

    is_cq, dx, to, _ = m._interpret_decode("W3SZ. D 550")
    assert dx == "W3SZ" and to == "QSY 432.550"

    is_cq, dx, to, _ = m._interpret_decode("VE3KI.NOQSY")
    assert dx == "VE3KI" and to == "NOQSY"

    is_cq, dx, to, _ = m._interpret_decode("QSY 432")
    assert dx is None and to == "QSY 432"


def test_cq_directed_west_is_not_dx_call():
    """'CQ WEST AA1ON' — WEST is a directed CQ tag; DX column must be AA1ON."""
    is_cq, dx_call, to_call, grid = m._interpret_decode("CQ WEST AA1ON")
    assert is_cq is True
    assert dx_call == "AA1ON"
    assert to_call == "CQ"
    assert grid is None


def test_cq_directed_variants():
    cases = [
        ("CQ DX K1ABC FN42", "K1ABC", "FN42"),
        ("CQ NA W1AW FN31", "W1AW", "FN31"),
        ("CQ POTA K1ABC", "K1ABC", None),
        ("CQ AA1ON FN42", "AA1ON", "FN42"),  # plain CQ still works
        ("CQ EAST N1MM", "N1MM", None),
    ]
    for msg, want_call, want_grid in cases:
        is_cq, dx_call, to_call, grid = m._interpret_decode(msg)
        assert is_cq is True, msg
        assert dx_call == want_call, msg
        assert to_call == "CQ", msg
        assert grid == want_grid, msg


def test_non_wsjtx_returns_none():
    assert m.parse(b"not a wsjtx datagram") is None


def test_grid_extractor_excludes_signoffs():
    assert m.extract_grid("CQ NJ1H FN42") == "FN42"
    assert m.extract_grid("K1ABC NJ1H FN42") == "FN42"
    assert m.extract_grid("K1ABC NJ1H R-12") is None
    assert m.extract_grid("K1ABC NJ1H RR73") is None
    assert m.extract_grid("K1ABC NJ1H 73") is None
    assert m.extract_grid("CQ DX K1ABC EM48bk") == "EM48BK"


def test_inhibit_status_roundtrip():
    from wims.udp import encode as E
    raw = E.build_inhibit_status(
        "ROY-144-A", 22372,
        inhibited=True, source_station="ROY-SSB",
        hold_rx=3, release_rx=1, expiries=0, invalid=2,
    )
    msg = m.parse(raw)
    assert isinstance(msg, m.InhibitStatus)
    assert msg.id == "ROY-144-A"
    assert msg.inhibit_port == 22372
    assert msg.inhibited is True
    assert msg.source_station == "ROY-SSB"
    assert msg.hold_rx == 3 and msg.release_rx == 1
    assert msg.expiries == 0 and msg.invalid == 2
    assert msg.type == m.INHIBIT_STATUS


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
