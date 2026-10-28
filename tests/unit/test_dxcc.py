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

"""DXCC entity name that feeds the Operate Country column."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.dxcc import (  # noqa: E402
    country_fields, describe, entity_name, lookup,
)
from wims.server.app import LiveFleet  # noqa: E402
from wims.server.state import decodes_to_dict  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"


def test_cx4ban_is_uruguay():
    assert lookup("CX4BAN") == "Uruguay"
    info = describe("CX4BAN")
    assert info["number"] == 144
    assert info["continent"] == "SA"
    assert info["cq"] == 13
    assert entity_name(144) == "Uruguay"
    assert entity_name("144") == "Uruguay"


def test_us_call_is_united_states():
    assert lookup("W1XX") == "United States"
    assert lookup("W1AW") == "United States"
    assert lookup("K1ABC") == "United States"
    info = describe("W1XX")
    assert info["number"] == 291
    assert info["continent"] == "NA"
    assert info["cq"] == 5
    assert describe("W6ABC")["cq"] == 3
    assert entity_name(291) == "United States"


def test_portable_and_prefix_override():
    # Portable suffix stays with the home entity.
    assert lookup("CX4BAN/P") == "Uruguay"
    assert lookup("W1AW/M") == "United States"
    assert lookup("W1AW/7") == "United States"
    # Trailing /R is a rover, still the home entity. A leading R/ is Russia.
    assert lookup("W1XX/R") == "United States"
    assert lookup("K1ABC/R") == "United States"
    assert lookup("R/W1XX") == "European Russia"
    assert lookup("3D2/R") == "Rotuma I."
    # Prefix before or after the slash is the place they are operating from.
    assert lookup("W1AW/CX") == "Uruguay"
    assert lookup("CX/W1AW") == "Uruguay"
    assert lookup("CX/W1AW/P") == "Uruguay"
    assert describe("W1AW/CX")["cq"] == 13
    assert lookup("W1AW/KH6") == "Hawaii"


def test_unknown_call_is_blank():
    assert lookup("QQ1ZZZ") is None
    assert lookup("") is None
    assert lookup("CQ") is None
    assert lookup(None) is None
    assert country_fields("QQ1ZZZ") == {
        "country": "", "continent": "", "cq_zone": None,
    }
    assert country_fields("")["country"] == ""
    assert entity_name(0) == ""
    assert entity_name("nope") == ""
    assert entity_name(None) == ""


def test_roster_and_decode_column_use_the_lookup():
    live = LiveFleet()
    live.observe_wsjtx(M.parse(E.build_status(
        "SIM-6M", 50_313_000, mode="FT8", de_call="WA1HCO", de_grid="FN31")),
        now=1.0, src_ip="192.168.10.21")
    for msg in (
        "CQ CX4BAN GF15",
        "CQ W1XX FN42",
        "CQ W1AW/CX GF15",
        "CQ QQ1ZZZ FN20",
    ):
        live.observe_wsjtx(M.parse(E.build_decode(
            "SIM-6M", time_ms=0, snr=-8, delta_time=0.2,
            delta_frequency=1400, message=msg)),
            now=1.2, src_ip="192.168.10.21")
    snap = live.snapshot(2.0)
    by = {c["call"]: c for c in snap["roster"]["candidates"]}
    assert by["CX4BAN"]["country"] == "Uruguay"
    assert by["CX4BAN"]["continent"] == "SA"
    assert by["CX4BAN"]["cq_zone"] == 13
    assert by["W1XX"]["country"] == "United States"
    assert by["W1XX"]["continent"] == "NA"
    assert by["W1XX"]["cq_zone"] == 5
    assert by["W1AW/CX"]["country"] == "Uruguay"
    assert by["QQ1ZZZ"]["country"] == ""
    assert by["QQ1ZZZ"]["continent"] == ""
    assert by["QQ1ZZZ"]["cq_zone"] is None

    decoded = {row["message"]: row for row in snap["decodes"]}
    assert decoded["CQ CX4BAN GF15"]["country"] == "Uruguay"
    assert decoded["CQ CX4BAN GF15"]["dx_call"] == "CX4BAN"
    assert decoded["CQ QQ1ZZZ FN20"]["country"] == ""

    plain = decodes_to_dict([
        {"ts": 1.0, "instance": "SIM-6M", "band": "6m", "snr": -5, "df": 200,
         "message": "CQ K1ABC FN42", "is_cq": True},
    ], now=2.0)
    assert plain[0]["country"] == "United States"
    assert plain[0]["dx_call"] == "K1ABC"


def test_country_column_is_text_and_default_after_dx():
    js = JS.read_text(encoding="utf-8")
    body = re.search(r"\{key:\"country\"[\s\S]*?cell:rosCountry\}", js)
    assert body, "ROS_COLS is missing the Country column"
    col = body.group(0)
    assert 'label:"Country"' in col
    assert "num:" not in col
    defaults = re.search(r"const ROS_COLS_DEFAULT = \[([^\]]+)\]", js)
    keys = re.findall(r'"([a-z0-9_]+)"', defaults.group(1))
    assert keys[keys.index("call") + 1] == "country"
    assert "function rosCountry" in js
    assert "rosCountryTip" in js
    assert "CQ " in js[js.find("function rosCountryTip"):js.find("function rosCountry(")]
    assert "dlogCountryCell" in js
    assert 'const ROS_COLS_VERSION = 3' in js


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
