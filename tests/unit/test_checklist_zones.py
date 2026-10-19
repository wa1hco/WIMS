# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Colors → checklist migration, and continent / CQ / ITU checklist lines."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.contest_rules import resolve  # noqa: E402
from wims.engine.goal_rules import (  # noqa: E402
    ChecklistRules,
    colors_to_checklist,
    goal_menu,
    shape_choice,
)
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.rules.choice import load_choice, needs_migration, save_choice  # noqa: E402
from wims.rules.cty import CtyIndex, find_cty_dat  # noqa: E402
from wims.rules.zones import cq_zone_from_grid, itu_zone_from_grid  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

# A small country file in the AD1C layout. Not a copy of cty.dat.
_CTY = """\
United States:5:8:NA:43.00:-87.90:0.0:K:
    K,W,N,AA;
Canada:4:4:NA:45.00:-75.00:0.0:VE:
    VE,VE7(3)[2];
Federal Republic of Germany:14:28:EU:51.00:10.00:0.0:DL:
    DL,DA;
France:14:27:EU:46.00:2.00:0.0:F:
    F;
Hawaii:31:61:OC:21.00:-157.00:0.0:KH6:
    KH6;
Alaska:1:1:NA:61.00:-150.00:0.0:KL:
    KL;
Brazil:11:15:SA:-15.00:-48.00:0.0:PY:
    PY;
Australia:30:59:OC:-35.00:149.00:0.0:VK:
    VK;
Russia:16:29:EU:55.00:37.00:0.0:UA:
    UA;
China:24:44:AS:40.00:116.00:0.0:BY:
    BY;
Zone Thirteen:13:37:EU:40.00:0.00:0.0:Z1:
    Z1;
"""


def _cty():
    return CtyIndex.parse(_CTY)


def _qso(call, band, grid, mode, *, cqz=None, ituz=None, cont=None, qid=None):
    return LoggedQso(
        id=qid or f"{call}-{band}-{mode}-{grid or ''}-{cqz or ''}-{cont or ''}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp="",
        operator="", rover_location=None, source="test",
        cqz=cqz, ituz=ituz, cont=cont,
    )


def _rules(kind, scope, *, cty=None, label="the log"):
    items = {kind: {"enabled": True, "scope": scope}}
    return ChecklistRules(items, title="Checklist", cty=cty or _cty(), log_label=label)


def _store(kind, scope, rows, *, cty=None, label="the log"):
    store = LogStore(":memory:")
    store.rules = _rules(kind, scope, cty=cty, label=label)
    for row in rows:
        store.upsert(row)
    return store


def test_colors_map_onto_one_scope_per_kind():
    both = colors_to_checklist({
        "new_dxcc": True, "new_dxcc_band": True,
        "new_grid": True, "new_grid_band": False,
        "new_call": False, "new_call_band": True,
    })
    assert both["dxcc"] == {"enabled": True, "scope": "band"}
    assert both["grid"] == {"enabled": True, "scope": "overall"}
    assert both["call"] == {"enabled": True, "scope": "band"}
    highlighted = colors_to_checklist(
        {"new_call": True, "new_dxcc_band": True, "new_grid_band": True},
        highlight_by_mode=True,
    )
    assert highlighted["call"] == {"enabled": True, "scope": "mode"}
    assert highlighted["dxcc"] == {"enabled": True, "scope": "band"}
    assert highlighted["grid"] == {"enabled": True, "scope": "band"}
    band_and_mode = colors_to_checklist(
        {"new_call_band": True}, highlight_by_mode=True,
    )
    assert band_and_mode["call"] == {"enabled": True, "scope": "mode"}


def test_saved_colors_choice_is_rewritten_once():
    override = {
        "categories": {
            "new_dxcc": False, "new_dxcc_band": False,
            "new_grid": True, "new_grid_band": True,
            "new_call": True, "new_call_band": False,
        },
        "highlight_by_mode": True,
        "only_fields_sought": True,
    }
    raw = {
        "schema": 4,
        "goal": "operating",
        "goal_id": "wsjtx-colors",
        "explicit": True,
        "fallback": "gridtracker",
        "wsjtx_override": override,
        "gridtracker_path": "/tmp/gt.json",
        "checklist": {"dxcc": {"enabled": True, "scope": "overall"}},
    }
    got = shape_choice(raw)
    assert got["goal"] == "operating" and got["goal_id"] == "checklist"
    assert got["schema"] == 5
    assert got["explicit"] is True
    assert got["fallback"] == ""
    assert got["wsjtx_override"] is None
    assert got["gridtracker_path"] == "/tmp/gt.json"
    assert got["checklist"]["grid"] == {"enabled": True, "scope": "band"}
    assert got["checklist"]["call"] == {"enabled": True, "scope": "mode"}
    assert got["checklist"]["dxcc"]["enabled"] is False
    again = shape_choice(got)
    assert again["checklist"] == got["checklist"]
    assert again["goal_id"] == "checklist"
    kept = resolve(raw, n1mm=False, contest_names=["NYQP"])
    assert kept.rules.id == "checklist"
    assert kept.suggested is False

    fd, name = tempfile.mkstemp(suffix=".json")
    import os
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert needs_migration(path) is True
        save_choice(load_choice(path), path)
        assert needs_migration(path) is False
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert disk["goal_id"] == "checklist"
        assert disk["checklist"]["call"]["scope"] == "mode"
        second = load_choice(path)
        assert second["checklist"] == disk["checklist"]
    finally:
        path.unlink(missing_ok=True)


def test_contest_keeps_its_goal_when_a_colors_edit_is_left_over():
    raw = {
        "schema": 4,
        "goal": "contest",
        "goal_id": "nyqp",
        "explicit": True,
        "wsjtx_override": {"categories": {"new_call": True}, "highlight_by_mode": True},
        "checklist": {
            "dxcc": {"enabled": False, "scope": "overall"},
            "call": {"enabled": False, "scope": "overall"},
        },
    }
    got = shape_choice(raw)
    assert got["goal"] == "contest" and got["goal_id"] == "nyqp"
    assert got["checklist"]["call"]["enabled"] is False
    assert got["checklist"]["dxcc"]["enabled"] is False
    assert got["wsjtx_override"] is None


def test_zone_table_matches_the_sample_squares():
    # Interior boxes, not legal boundaries. See rules/zones.py for the sources.
    assert cq_zone_from_grid("FN42") == 5 and itu_zone_from_grid("FN42") == 8
    assert cq_zone_from_grid("FN42xx") == 5
    assert cq_zone_from_grid("FN03") == 4 and itu_zone_from_grid("FN03") == 4
    assert cq_zone_from_grid("CM87") == 3 and itu_zone_from_grid("CM87") == 6
    assert cq_zone_from_grid("CN89") == 3 and itu_zone_from_grid("CN89") == 2
    assert cq_zone_from_grid("GG66") == 11 and itu_zone_from_grid("GG66") == 15
    assert cq_zone_from_grid("OF78") == 29 and itu_zone_from_grid("OF78") == 58
    assert cq_zone_from_grid("QF22") == 30 and itu_zone_from_grid("QF22") == 59
    assert cq_zone_from_grid("OM89") == 24 and itu_zone_from_grid("OM89") == 44
    assert cq_zone_from_grid("KO85") == 16 and itu_zone_from_grid("KO85") == 29
    assert cq_zone_from_grid("NO15") == 18 and itu_zone_from_grid("NO15") == 31
    assert cq_zone_from_grid("EM75") is None
    assert itu_zone_from_grid("EM75") is None
    assert cq_zone_from_grid("FN") is None
    assert cq_zone_from_grid("") is None


def test_country_file_zones_and_portable_prefixes():
    cty = _cty()
    us = cty.describe("K1ABC", "FN42")
    assert us.continent == "NA" and us.cq == 5 and us.itu == 8
    assert us.cq_uncertain is False
    bare = cty.describe("K1ABC", None)
    assert bare.cq_uncertain and bare.itu_uncertain
    assert bare.cq is None and bare.continent == "NA"
    split = cty.describe("K1ABC", "EM75")
    assert split.cq_uncertain and split.itu_uncertain
    ve7 = cty.describe("VE7ABC", None)
    assert ve7.cq == 3 and ve7.itu == 2 and not ve7.cq_uncertain
    ve3 = cty.describe("VE3ABC", "FN03")
    assert ve3.cq == 4 and ve3.itu == 4
    dl = cty.describe("DL1ABC", None)
    assert dl.cq == 14 and dl.itu == 28 and dl.continent == "EU"
    assert not dl.cq_uncertain
    py = cty.describe("PY1ABC", None)
    assert py.cq == 11 and not py.cq_uncertain and py.itu_uncertain
    py_grid = cty.describe("PY1ABC", "GG66")
    assert py_grid.itu == 15 and not py_grid.itu_uncertain
    assert cty.describe("KL7ABC", None).cq == 1
    assert cty.describe("F/W1AW", None).continent == "EU"
    assert cty.entity_name("W1AW/KH6") == "Hawaii"
    assert cty.entity_name("W1AW/P") == "United States"
    adif = cty.describe("DL1ABC", "JO62", cqz="13", ituz="99", cont="OC")
    assert adif.cq == 13 and adif.itu == 28 and adif.continent == "OC"
    assert adif.cq_uncertain is False
    missing = cty.describe("ZZ9ZZZ", None)
    assert missing.known is False and not missing.cq_uncertain


def test_each_new_kind_and_scope():
    cty = _cty()
    logged = [_qso("DL1ABC", "20m", "JO62", "FT8")]
    asia = _store("continent", "overall", logged, cty=cty).classify(
        "BY1ABC", "20m", "OM89", "FT8",
    )
    assert asia.is_dupe is False and asia.is_new_mult is True
    assert asia.need_reason == "Need: continent Asia in the log."
    assert " on " not in asia.need_reason
    same = _store("continent", "overall", logged, cty=cty).classify(
        "DA1ABC", "40m", "JO62", "FT8",
    )
    assert same.is_dupe is True and "Europe" in same.need_reason
    other_band = _store("continent", "band", logged, cty=cty).classify(
        "DA1ABC", "40m", "JO62", "FT8",
    )
    assert other_band.is_dupe is False
    assert other_band.need_reason == "Need: continent Europe on 40m in the log."
    other_mode = _store("continent", "mode", logged, cty=cty).classify(
        "DA1ABC", "20m", "JO62", "FT4",
    )
    assert other_mode.need_reason == "Need: continent Europe on FT4 in the log."

    cq_new = _store("cq", "band", logged, cty=cty).classify(
        "Z1ABC", "20m", None, "FT8",
    )
    assert cq_new.need_reason == "Need: CQ zone 13 on 20m in the log."
    assert cq_new.is_new_mult is True
    cq_have = _store("cq", "overall", logged, cty=cty).classify(
        "DA1ABC", "40m", None, "FT8",
    )
    assert cq_have.is_dupe is True and "CQ zone 14" in cq_have.need_reason
    itu_mode = _store("itu", "mode", logged, cty=cty).classify(
        "DA1ABC", "20m", None, "FT4",
    )
    assert itu_mode.need_reason == "Need: ITU zone 28 on FT4 in the log."


def test_uncertain_zone_is_not_called_needed():
    cty = _cty()
    store = _store("cq", "overall", [], cty=cty)
    unsure = store.classify("K1ABC", "20m", None, "FT8")
    assert unsure.is_dupe is True and unsure.is_new_mult is False
    assert "zone uncertain" in unsure.need_reason
    assert not unsure.need_reason.startswith("Need")
    assert "Not needed" not in unsure.need_reason
    split = store.classify("K1ABC", "20m", "EM75", "FT8")
    assert "zone uncertain" in split.need_reason and split.is_new_mult is False
    sure = store.classify("K1ABC", "20m", "FN42", "FT8")
    assert sure.is_dupe is False and sure.is_new_mult is True
    assert sure.need_reason.startswith("Need: CQ zone 5")
    # An uncertain log row does not prove the zone was worked.
    logged = _store("cq", "overall", [_qso("K1OLD", "20m", None, "FT8")], cty=cty)
    still = logged.classify("K2NEW", "20m", "FN42", "FT8")
    assert still.is_dupe is False and "CQ zone 5" in still.need_reason
    # A needed line keeps its reason, and the uncertain zone is added.
    both = ChecklistRules(
        {
            "call": {"enabled": True, "scope": "overall"},
            "cq": {"enabled": True, "scope": "overall"},
        },
        title="Checklist", cty=cty, log_label="the log",
    )
    store.rules = both
    mixed = store.classify("N1NEW", "20m", None, "FT8")
    assert mixed.is_dupe is False
    assert mixed.need_reason.startswith("Needed: new call N1NEW")
    assert "zone uncertain" in mixed.need_reason
    # A call with no country is "cannot tell" when only the zone line is on.
    zone_only = _store("cq", "overall", [], cty=cty)
    missing = zone_only.classify("ZZ9ZZZ", "20m", "FN42", "FT8")
    assert missing.is_dupe is True and missing.is_new_mult is False
    assert missing.need_reason.startswith("WIMS cannot tell yet")
    assert "zone uncertain" not in missing.need_reason


def test_adif_zone_fields_win_over_the_country_file():
    cty = _cty()
    logged = [_qso("DL1ABC", "20m", "JO62", "FT8", cqz="13", cont="OC")]
    cq = _store("cq", "overall", logged, cty=cty)
    assert cq.classify("Z1ABC", "20m", None, "FT8").is_dupe is True
    still = cq.classify("DL2XYZ", "20m", None, "FT8")
    assert still.is_dupe is False
    assert still.need_reason == "Need: CQ zone 14 in the log."
    cont = _store("continent", "overall", logged, cty=cty)
    assert cont.classify("VK1ABC", "20m", "QF22", "FT8").is_dupe is True
    europe = cont.classify("DL2XYZ", "20m", None, "FT8")
    assert europe.is_dupe is False and "Europe" in europe.need_reason


def test_missing_country_file_disables_the_new_kinds():
    store = LogStore(":memory:")
    store.rules = ChecklistRules(
        {"continent": {"enabled": True, "scope": "overall"},
         "cq": {"enabled": True, "scope": "band"},
         "itu": {"enabled": True, "scope": "mode"}},
        title="Checklist", cty=None, log_label="the log",
    )
    verdict = store.classify("K1ABC", "20m", "FN42", "FT8")
    assert verdict.is_dupe is True and verdict.is_new_mult is False
    assert not verdict.need_reason.startswith("Need")
    summary = store.rules.plain_summary()
    assert "country list" in summary
    assert "are off because" in summary
    menu = goal_menu(
        {"goal": "operating", "goal_id": "checklist", "checklist": store.rules.items},
        custom_available=False, cty_ok=False,
    )
    rows = {row["kind"]: row for row in menu["checklist"]["rows"]}
    for kind in ("continent", "cq", "itu"):
        assert rows[kind]["available"] is False
        assert rows[kind]["enabled"] is False
        assert rows[kind]["stored"] is True
        assert rows[kind]["coming_soon"] is False
        assert "cty.dat" in rows[kind]["tip"]
    kept = shape_choice({
        "schema": 5, "goal": "operating", "goal_id": "checklist", "explicit": True,
        "checklist": store.rules.items,
    })
    assert kept["checklist"]["continent"]["enabled"] is True
    assert kept["checklist"]["cq"]["scope"] == "band"
    empty = Path(tempfile.mkdtemp())
    assert find_cty_dat(roots=[empty]) is None
    found = empty / "cty.dat"
    found.write_text(_CTY, encoding="latin-1")
    assert find_cty_dat(roots=[empty]) == found
    assert find_cty_dat(roots=[found]) == found


def test_py_itu_uncertain_does_not_hide_a_known_cq_zone():
    cty = _cty()
    rules = ChecklistRules(
        {
            "cq": {"enabled": True, "scope": "overall"},
            "itu": {"enabled": True, "scope": "overall"},
        },
        title="Checklist", cty=cty, log_label="the log",
    )
    store = LogStore(":memory:")
    store.rules = rules
    hit = store.classify("PY1ABC", "20m", None, "FT8")
    assert hit.is_dupe is False and hit.is_new_mult is True
    assert hit.need_reason.startswith("Need: CQ zone 11")
    assert "zone uncertain" in hit.need_reason


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
