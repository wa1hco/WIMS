# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One call-to-entity resolver for the checklist and the Country column.

The fixture is a small country file in the AD1C layout. It is not a copy
of cty.dat. The checklist name and the Country column have to agree on it,
and the structural rules have to hold.
"""

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.dxcc import country_fields, describe, lookup  # noqa: E402
from wims.rules.cty import CtyIndex  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "cty_rules.dat"

# Calls the two former paths both have to answer. Expected name is the
# DXCC entity, which is what both the checklist and the Country column show.
_SAMPLE = {
    "CX4BAN": "Uruguay",
    "CX4BAN/P": "Uruguay",
    "W1AW": "United States",
    "W1AW/P": "United States",
    "W1AW/M": "United States",
    "W1AW/MM": "United States",
    "W1AW/AM": "United States",
    "W1AW/QRP": "United States",
    "W1AW/R": "United States",
    "W1AW/7": "United States",
    "W1AW/KH6": "Hawaii",
    "KH6/W1AW": "Hawaii",
    "KH6ABC": "Hawaii",
    "W1/VE3XX": "United States",
    "VE3XX/W1": "United States",
    "VE3ABC": "Canada",
    "F/W1AW": "France",
    "DL1ABC": "Fed. Rep. of Germany",
    "KG4LDK": "United States",
    "KG4LDK/P": "United States",
    "KG4AA": "Guantanamo Bay",
    "KG4NE": "Guantanamo Bay",
    "W1AW/KG4": "Guantanamo Bay",
    "KG4V": "United States",
    "KG4HZF": "Alaska",
    "KL7AA": "Alaska",
    "KL7NW": "United States",
    "KH6EE/7": "United States",
    "NP2Q": "US Virgin Islands",
    "MM0ABC": "Scotland",
    "G4ABC": "England",
    "IT9NVA": "Italy",
    "IG9CGH": "Italy",
    "IH9YMC": "Italy",
    "KC4AAA": "Antarctica",
    "KC4AAB": "Antarctica",
    "KC4USV": "Antarctica",
    "KC4BB": "United States",
    "KC4ZZZ": "United States",
    "3Y/B": "Bouvet",
    "3Y/LB5SH": "Bouvet",
    "3Y0J": "Peter 1 Island",
    "3Y0X": "Peter 1 Island",
    "CE0/X": "San Felix & San Ambrosio",
    "CE0XAA": "San Felix & San Ambrosio",
    "CE0YAA": "Easter Island",
    "CE0ZAA": "Juan Fernandez Islands",
    "CE0/I": "Juan Fernandez Islands",
    "VP8ADR": "Falkland Islands",
    "VP8/G": "South Georgia Island",
    "VP8LP/G": "South Georgia Island",
    "VP8/S": "South Sandwich Islands",
    "SV2RSG/A": "Mount Athos",
    "SV2ASP/A": "Mount Athos",
    "K9CS/KH8S": "Swains Island",
    "JG8NQJ/JD1": "Minami Torishima",
    "JD1ABC": "Ogasawara",
    "4U1ITU": "ITU HQ",
    "4U1UN": "United Nations HQ",
    "4U1VIC": "Austria",
    "F1FIRST": "France",
    "WD9EXD/R": "United States",
}


def _cty():
    return CtyIndex.parse(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_parses_and_structural_rules_hold():
    cty = _cty()
    assert cty.entities > 20
    assert "K9CS/KH8S" in cty.exact
    assert "KH6EE/7" in cty.exact
    assert "3Y/LB5SH" in cty.exact
    assert "SV2RSG/A" in cty.exact
    assert "3Y/B" in cty.by_prefix
    assert "IT9" not in cty.dxcc_prefix
    assert "IT9" in cty.by_prefix
    for call, name in _SAMPLE.items():
        assert cty.entity_name(call) == name, call
    us = cty.describe("KG4LDK", "FN42")
    assert us.continent == "NA" and us.cq == 5 and us.itu == 8
    moved = cty.describe("KH6EE/7", None)
    assert moved.cq == 3 and moved.itu == 6
    assert cty.describe("KG4AA", None).cq == 8
    africa = cty.describe("IG9CGH", None)
    assert africa.continent == "AF" and africa.cq == 33
    assert cty.describe("IZ1ABC", None).continent == "AF"
    assert cty.lookup("4U1VIC").name == "Vienna Intl Ctr"
    assert cty.lookup("W1ZZ").cq == 4


def test_checklist_and_country_column_agree():
    cty = _cty()
    for call, name in _SAMPLE.items():
        column = country_fields(call, cty=cty)
        assert column["country"] == name, call
        assert lookup(call, cty=cty) == name, call
        assert cty.entity_name(call) == column["country"]
    # A grid fills the US CQ zone the same way the checklist does.
    placed = country_fields("K1ABC", cty=cty, grid="FN42")
    assert placed["country"] == "United States"
    assert placed["cq_zone"] == 5
    assert placed["continent"] == "NA"


def test_builtin_fallback_matches_the_structural_rules():
    assert lookup("VK7DZ") == "Australia"
    assert describe("VK7DZ")["number"] == 150
    assert lookup("VK0M") == "Macquarie I."
    assert lookup("WD9EXD/R") == "United States"
    assert lookup("AC1JR/R") == "United States"
    assert lookup("W1AW/MM") == "United States"
    assert lookup("W1AW/QRP") == "United States"
    assert lookup("R/W1AW") == "European Russia"
    assert lookup("KG4LDK") == "United States"
    assert lookup("KG4AA") == "Guantanamo Bay"
    assert lookup("KC4AAA") == "Antarctica"
    assert lookup("KC4AAB") == "Antarctica"
    assert lookup("KC4USV") == "Antarctica"
    assert lookup("KC4BB") == "United States"
    assert lookup("3Y/B") == "Bouvet"
    assert lookup("3Y0J") == "Peter 1 I."
    assert lookup("VP8LP/G") == "South Georgia I."
    assert lookup("SV2ASP/A") == "Mount Athos"
    assert lookup("CE0/X") == "San Felix & San Ambrosio"
    assert lookup("W1AW/KH6") == "Hawaii"
    assert lookup("W1/VE3XX") == "United States"
    assert lookup("VE3XX/W1") == "United States"
    assert lookup("CQ") is None


def _audit():
    path = ROOT / "tools" / "dev" / "audit_entities.py"
    spec = importlib.util.spec_from_file_location("audit_entities", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_reports_log_and_n1mm_disagreements():
    mod = _audit()
    adif = (
        "<EOH>\n"
        "<CALL:6>KG4LDK <DXCC:3>105 <COUNTRY:14>Guantanamo Bay <EOR>\n"
        "<CALL:5>KG4AA <DXCC:3>105 <COUNTRY:14>Guantanamo Bay <EOR>\n"
        "<CALL:4>W1AW <DXCC:3>291 <COUNTRY:13>United States <EOR>\n"
        "<CALL:5>DL1ABC <EOR>\n"
    )
    with tempfile.TemporaryDirectory() as folder:
        adi = Path(folder) / "log.adi"
        adi.write_text(adif, encoding="utf-8")
        db = Path(folder) / "n1mm.s3db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE DXLOG (Call TEXT, Country TEXT, DXCC TEXT)")
        con.execute(
            "INSERT INTO DXLOG VALUES (?, ?, ?)",
            ("KG4LDK", "Guantanamo Bay", "105"),
        )
        con.execute(
            "INSERT INTO DXLOG VALUES (?, ?, ?)",
            ("W1AW", "United States", "291"),
        )
        con.commit()
        con.close()
        report = mod.audit(adi, cty_path=FIXTURE, s3db_path=db)
    assert report["qsos"] == 4
    assert report["with_dxcc"] == 3
    assert report["with_country"] == 3
    calls = {row["call"]: row for row in report["field_disagreements"]}
    assert "KG4LDK" in calls
    assert calls["KG4LDK"]["resolver"] == "United States"
    assert "KG4AA" not in calls
    assert "W1AW" not in calls
    n1mm = {row["call"]: row for row in report["n1mm_disagreements"]}
    assert "KG4LDK" in n1mm
    assert "W1AW" not in n1mm
    text = mod.format_report(report)
    assert "KG4LDK" in text
    assert "Disagreements with stored fields: 1" in text


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
