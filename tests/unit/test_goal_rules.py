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

"""Goal selector: migration, awards, checklist, and the Setup wording."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.engine.contest_rules import resolve  # noqa: E402
from wims.engine.goal_rules import (  # noqa: E402
    AwardRules,
    ChecklistRules,
    award_available,
    goal_menu,
    kind_available,
    shape_choice,
)
from wims.engine.scoring import build_candidate  # noqa: E402
from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.rules.choice import load_choice, needs_migration, save_choice  # noqa: E402
from wims.rules.places import US_STATES, canonical_place, is_us_state  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _qso(call, band, grid, mode, *, dxcc=None, state=None, qid=None):
    return LoggedQso(
        id=qid or f"{call}-{band}-{mode}-{state or ''}-{dxcc or ''}",
        call=call, band=band, grid=grid, mode=mode,
        points=1, is_mult=False, contest="T", timestamp="",
        operator="", rover_location=None, source="test",
        state=state, dxcc=dxcc,
    )


def _lookup(call):
    return {
        "K1ABC": "United States",
        "I1ABC": "Italy",
        "W1AW": "United States",
    }.get((call or "").upper())


class _Decode:
    def __init__(self, call, grid, mode="FT8"):
        self.dx_call = call
        self.grid = grid
        self.mode = mode
        self.id = "6m"
        self.snr = -10
        self.is_cq = True


def test_schema3_contest_migrates_and_keeps_the_selection():
    old = {
        "schema": 3,
        "contest": "nyqp",
        "explicit": True,
        "suggested": False,
        "fallback": "wsjtx-colors",
        "station_state": "NY",
        "station_county": "ALBA",
        "wsjtx_override": {"categories": {"new_call": True}},
    }
    got = shape_choice(old)
    assert got["schema"] == 4
    assert got["goal"] == "contest"
    assert got["goal_id"] == "nyqp"
    assert got["contest"] == "nyqp"
    assert got["explicit"] is True
    assert got["station_state"] == "NY"
    assert got["station_county"] == "ALBA"
    assert got["wsjtx_override"]["categories"]["new_call"] is True
    kept = resolve(old, n1mm=False)
    assert kept.rules.id == "nyqp"
    assert "once per band per mode group" in kept.public["summary"]


def test_schema3_empty_menu_becomes_just_operating():
    got = shape_choice({"schema": 3, "contest": None, "explicit": True})
    assert got["goal"] == "operating"
    assert got["goal_id"] == "wsjtx-colors"
    assert got["contest"] is None
    solo = resolve(got, n1mm=False, cty_ok=False)
    assert solo.rules.id == "wsjtx-colors"
    n1mm = resolve(got, n1mm=True)
    assert n1mm.rules.id == "arrl-vhf"
    assert n1mm.public["source_label"] == "N1MM · ARRL VHF"
    assert "ARRL VHF" in n1mm.public["n1mm_line"]


def test_schema3_custom_file_stays_custom():
    got = shape_choice({"schema": 3, "contest": "custom", "explicit": True})
    assert got["goal"] == "custom" and got["goal_id"] == "custom-file"
    rules = {"id": "custom", "title": "Custom rules", "summary": "Mine.", "dupe_scope": "band"}
    resolved = resolve(got, n1mm=False, custom_data=rules)
    assert resolved.rules.id == "custom"
    assert resolved.public["source_label"] == "Custom rules"


def test_saved_file_is_rewritten_as_schema4(tmp_path=None):
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(json.dumps({
            "schema": 3, "contest": "arrl-vhf", "explicit": True,
        }), encoding="utf-8")
        assert needs_migration(path) is True
        loaded = load_choice(path)
        assert loaded["goal"] == "contest" and loaded["goal_id"] == "arrl-vhf"
        save_choice(loaded, path)
        assert needs_migration(path) is False
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert disk["schema"] == 4
        assert disk["goal"] == "contest"
        assert disk["goal_id"] == "arrl-vhf"
        assert disk["contest"] == "arrl-vhf"
    finally:
        path.unlink(missing_ok=True)


def test_explicit_just_operating_is_not_replaced_by_a_suggestion():
    choice = {"goal": "operating", "goal_id": "wsjtx-colors", "explicit": True, "schema": 4}
    kept = resolve(choice, n1mm=False, contest_names=["NYQP"])
    assert kept.rules.id == "wsjtx-colors"
    assert kept.suggested is False


def test_suggestion_still_moves_an_unset_menu():
    moved = resolve(
        {"contest": None, "explicit": False},
        n1mm=False,
        contest_names=["NYQP"],
    )
    assert moved.rules.id == "nyqp"
    assert moved.suggested is True
    assert "Just operating (not a contest)" in moved.public["suggested_note"]
    assert moved.public["goal"]["type"] == "contest"
    assert moved.public["goal"]["id"] == "nyqp"


def test_dxcc_award_uses_the_log_as_the_already_have_list():
    store = LogStore(":memory:")
    rules = AwardRules("dxcc", dxcc_lookup=_lookup, log_label="the log")
    store.rules = rules
    store.upsert(_qso("K1ABC", "6m", "FN42", "FT8", dxcc="291"))
    new = store.classify("I1ABC", "6m", "JN45", "FT8")
    assert new.is_dupe is False and new.is_new_mult is True
    assert "Italy" in new.need_reason
    again = store.classify("W1AW", "2m", "FN31", "FT8")
    assert again.is_dupe is True
    assert "United States" in again.need_reason
    unknown = AwardRules("dxcc", dxcc_lookup=None).classify(
        store, "VK1ABC", "6m", "FT8", "QF22",
    )
    assert unknown.is_dupe is True
    assert "does not know" in unknown.need_reason


def test_was_counts_states_and_not_provinces():
    assert len(US_STATES) == 50
    assert is_us_state("MA") and not is_us_state("ON") and not is_us_state("DC")
    assert canonical_place("Massachusetts") == "MA"
    assert canonical_place("Québec") == "QC"
    store = LogStore(":memory:")
    store.rules = AwardRules("was", log_label="the log")
    store.upsert(_qso("K1ABC", "6m", "FN42", "FT8", state="MA"))
    fresh = store.classify("N2NEW", "6m", "FN20", "FT8", state="NH")
    assert fresh.is_dupe is False and "New Hampshire" in fresh.need_reason
    dupe = store.classify("K1ZZ", "2m", "FN42", "FT8", state="Massachusetts")
    assert dupe.is_dupe is True and "Massachusetts" in dupe.need_reason
    province = store.classify("VE3ABC", "6m", "FN03", "FT8", state="ON")
    assert province.is_dupe is True and "does not count" in province.need_reason
    missing = store.classify("N0NE", "6m", "FN42", "FT8")
    assert missing.is_dupe is True and "does not know this station's state" in missing.need_reason


def test_vucc_is_the_four_character_square():
    store = LogStore(":memory:")
    store.rules = AwardRules("vucc")
    store.upsert(_qso("K1ABC", "6m", "FN42xx", "FT8"))
    assert store.classify("N1NEW", "2m", "FN42", "FT8").is_dupe is True
    fresh = store.classify("N1NEW", "2m", "FN31", "FT8")
    assert fresh.is_dupe is False and fresh.is_new_mult is True
    assert "FN31" in fresh.need_reason
    field_only = store.classify("N1NEW", "2m", "FN", "FT8")
    assert field_only.is_dupe is True and "four-character" in field_only.need_reason
    cand = build_candidate(_Decode("N0NEW", "EM73"), "6m", store)
    assert cand.is_dupe is False and cand.is_new_mult is True


def test_county_award_and_prefix_stay_off():
    assert award_available("county") is False
    assert kind_available("county") is False
    assert kind_available("prefix") is False
    assert kind_available("dxcc") and kind_available("call")
    rules_dir = ROOT / "src" / "wims" / "rules"
    names = [p.name.lower() for p in rules_dir.iterdir()]
    assert not any("count" in name or "prefix" in name for name in names)
    store = LogStore(":memory:")
    verdict = AwardRules("county").classify(store, "K1ABC", "6m", "FT8", "FN42")
    assert verdict.is_dupe is True and verdict.is_new_mult is False
    assert "county list" in verdict.need_reason
    menu = goal_menu(
        {"goal": "award", "goal_id": "dxcc", "checklist": None},
        custom_available=False,
    )
    county = next(row for row in menu["menus"]["award"]["options"] if row["id"] == "county")
    assert county["enabled"] is False
    assert "coming soon" in county["title"].lower() or "coming soon" in county["tip"].lower()
    forced = ChecklistRules(
        {"prefix": {"enabled": True, "scope": "overall"}, "call": {"enabled": True, "scope": "overall"}},
        title="Checklist",
    )
    assert forced.items["prefix"]["enabled"] is False
    store.rules = forced
    store.upsert(_qso("K1ABC", "6m", "FN42", "FT8"))
    assert store.classify("G4ABC", "6m", "IO91", "FT8").is_dupe is False
    assert "new call G4ABC" in store.classify("G4ABC", "6m", "IO91", "FT8").need_reason
    assert store.classify("K1ABC", "20m", "FN42", "FT8").is_dupe is True


def test_checklist_scopes_and_state():
    store = LogStore(":memory:")
    rules = ChecklistRules(
        {
            "dxcc": {"enabled": False, "scope": "overall"},
            "grid": {"enabled": True, "scope": "band"},
            "state": {"enabled": True, "scope": "overall"},
            "call": {"enabled": True, "scope": "mode"},
        },
        title="Checklist",
        log_label="the log",
    )
    store.rules = rules
    store.upsert(_qso("K1ABC", "6m", "FN42", "FT8", state="MA"))
    same = store.classify("K1ABC", "6m", "FN42", "FT8", state="MA")
    assert same.is_dupe is True
    other_band = store.classify("N1NEW", "2m", "FN42", "FT8", state="MA")
    assert other_band.is_dupe is False and "on 2m" in other_band.need_reason
    other_state = store.classify("N1NEW", "6m", "FN42", "FT8", state="VT")
    assert other_state.is_dupe is False and "Vermont" in other_state.need_reason
    other_mode = store.classify("K1ABC", "6m", "FN42", "FT4", state="MA")
    assert other_mode.is_dupe is False and "FT4" in other_mode.need_reason


def test_set_rules_migrates_then_selects_an_award():
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    os.environ["WIMS_CONTEST_RULES"] = str(path)
    try:
        path.write_text(json.dumps({
            "schema": 3, "contest": "nyqp", "explicit": True,
        }), encoding="utf-8")
        from wims.server.app import LiveFleet
        live = LiveFleet()
        live.attach_rules(n1mm_authoritative=False)
        assert live._log.rules.id == "nyqp"
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert disk["schema"] == 4 and disk["goal_id"] == "nyqp"
        res = live.set_rules({"action": "select", "goal": "award", "goal_id": "vucc"})
        assert res["ok"] is True
        assert live._log.rules.id == "award-vucc"
        live.set_rules({"action": "select", "goal": "operating", "goal_id": "checklist"})
        assert live._log.rules.id == "checklist"
        live.set_rules({
            "action": "checklist",
            "items": [
                {"kind": "call", "enabled": True, "scope": "band"},
                {"kind": "prefix", "enabled": True, "scope": "overall"},
                {"kind": "dxcc", "enabled": False, "scope": "overall"},
            ],
        })
        assert live._log.rules.items["prefix"]["enabled"] is False
        assert live._log.rules.items["call"]["enabled"] is True
        assert live._log.rules.items["call"]["scope"] == "band"
        assert live._log.rules.items["dxcc"]["enabled"] is False
    finally:
        os.environ.pop("WIMS_CONTEST_RULES", None)
        path.unlink(missing_ok=True)


def test_setup_page_uses_positive_goal_wording():
    page = (ROOT / "src" / "wims" / "server" / "static" / "setup.html").read_text(encoding="utf-8")
    assert 'id="goal-pick"' in page
    assert "Just operating (not a contest)" in page
    assert ">None</option>" not in page
    assert "Set Contest to None" not in page
    js = (ROOT / "src" / "wims" / "server" / "static" / "wims.js").read_text(encoding="utf-8")
    assert "goal_id" in js
    assert "coming soon" in js
    menu = goal_menu(
        shape_choice({"schema": 3, "contest": None, "explicit": True}),
        custom_available=False,
    )
    titles = [row["title"] for row in menu["types"]]
    assert titles[2] == "Just operating (not a contest)"
    assert all(row["tip"] for row in menu["types"])
    assert menu["type"] == "operating"
    assert menu["detail_label"] == "Worth working"
    checks = {row["kind"]: row for row in menu["checklist"]["rows"]}
    assert checks["county"]["coming_soon"] is True
    assert checks["prefix"]["coming_soon"] is True
    assert checks["county"]["enabled"] is False
    assert checks["dxcc"]["enabled"] is True


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
