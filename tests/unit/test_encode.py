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

"""Round-trip tests: encode.build_x -> messages.parse -> same values."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp import encode as E  # noqa: E402


def test_heartbeat_roundtrip():
    m = M.parse(E.build_heartbeat("SIM-6M-1", max_schema=3, version="2.7.0"))
    assert isinstance(m, M.Heartbeat)
    assert m.id == "SIM-6M-1" and m.version == "2.7.0" and m.max_schema == 3


def test_status_roundtrip():
    raw = E.build_status("SIM-6M-1", 50_313_000, mode="FT8", de_call="WA1HCO",
                         de_grid="FN42", dx_call="K1ABC", dx_grid="FN31",
                         transmitting=True, rx_df=1200, tx_df=1500, config_name="SIM")
    m = M.parse(raw)
    assert isinstance(m, M.Status)
    assert m.dial_frequency == 50_313_000
    assert m.mode == "FT8" and m.de_call == "WA1HCO" and m.dx_call == "K1ABC"
    assert m.transmitting is True and m.rx_df == 1200 and m.tx_df == 1500
    assert m.config_name == "SIM"
    assert m.frequency_tolerance is None and m.tr_period is None  # defaulted to N/A


def test_decode_roundtrip_with_grid():
    raw = E.build_decode("SIM-6M-1", time_ms=8_145_000, snr=-7, delta_time=0.2,
                         delta_frequency=1500, message="CQ NJ1H FN42")
    m = M.parse(raw)
    assert isinstance(m, M.Decode)
    assert m.snr == -7 and abs(m.delta_time - 0.2) < 1e-9 and m.delta_frequency == 1500
    assert m.message == "CQ NJ1H FN42"
    assert m.is_cq is True and m.dx_call == "NJ1H" and m.grid == "FN42"


def test_halt_and_reply_parse_as_known_types():
    halt = M.parse(E.build_halt_tx("SIM-6M-1", auto_only=False))
    assert halt.type == M.HALT_TX and halt.id == "SIM-6M-1"
    reply = M.parse(E.build_reply("SIM-6M-1", time_ms=8_145_000, snr=-7, delta_time=0.2,
                                  delta_frequency=1500, message="CQ NJ1H FN42"))
    assert reply.type == M.REPLY and reply.id == "SIM-6M-1"


def test_build_configure_has_configure_type():
    import struct
    raw = E.build_configure("SIM-6M-1", dx_call="K1ABC", dx_grid="FN31",
                            rx_df=1500, generate_messages=True)
    magic, schema, mtype = struct.unpack_from(">III", raw, 0)
    assert magic == 0xADBCCBDA and mtype == M.CONFIGURE and schema == 2


def test_reply_auto_tx_eligible():
    assert M.reply_auto_tx_eligible("CQ K1ABC FN31") is True
    assert M.reply_auto_tx_eligible("QRZ K1ABC FN31") is True
    assert M.reply_auto_tx_eligible("W9XYZ K1ABC 73") is True
    assert M.reply_auto_tx_eligible("W9XYZ K1ABC RR73") is True
    assert M.reply_auto_tx_eligible("W9XYZ K1ABC R-12") is False


def test_qso_logged_roundtrip():
    from datetime import datetime, timezone
    when = datetime(2026, 8, 24, 18, 30, 0, tzinfo=timezone.utc)
    raw = E.build_qso_logged(
        "PROBE-6M",
        dx_call="K1AA1",
        dx_grid="FN42",
        tx_frequency=50_313_000,
        mode="FT8",
        my_call="WA1HCO",
        my_grid="FN42",
        comments="WIMS2237-mcast",
        datetime_off=when,
        datetime_on=when,
    )
    m = M.parse(raw)
    assert isinstance(m, M.QSOLogged)
    assert m.id == "PROBE-6M"
    assert m.dx_call == "K1AA1" and m.dx_grid == "FN42"
    assert m.tx_frequency == 50_313_000 and m.mode == "FT8"
    assert m.my_call == "WA1HCO" and m.comments == "WIMS2237-mcast"
    assert m.datetime_off is not None and m.datetime_off["julian_day"] > 0
    assert m.datetime_off["timespec"] == 1


def test_logged_adif_roundtrip():
    adif = "<CALL:5>K1AA2<BAND:2>6m<FREQ:8>50.313000<MODE:3>FT8"
    raw = E.build_logged_adif("PROBE-6M", adif)
    m = M.parse(raw)
    assert isinstance(m, M.LoggedADIF)
    assert m.id == "PROBE-6M"
    assert m.adif is not None and "K1AA2" in m.adif and "<eor>" in m.adif.lower()
    assert M.reply_auto_tx_eligible("W9XYZ K1ABC FN42") is False


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
