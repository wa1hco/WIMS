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

"""Operate TX groups visibility. Display only — the arbiter is not involved.

The page script is the real renderer. These checks load it in node the way
the browser would, against the same element ids, and read the banner back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "src" / "wims" / "server" / "static" / "ops.html"
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"

TIP = (
    "A group is a set of WSJT-X instances that must not transmit at the same time "
    "(shared PA, antenna, or band policy). WIMS refuses Work when another instance "
    "in the same group already holds TX."
)

_VIEWS = None


def _ops() -> str:
    return OPS.read_text(encoding="utf-8")


def _js() -> str:
    return JS.read_text(encoding="utf-8")


def test_tx_groups_paragraph_is_a_hover_title():
    page = _ops()
    assert "<h2>TX groups</h2>" not in page
    assert "<b>group</b>" not in page
    assert "Rows appear here when something is transmitting" not in page
    start = page.find('id="il-section"')
    assert start > 0
    block = page[start:page.find("</section>", start)]
    assert 'class="hint"' not in block
    assert 'id="il-summary"' in block
    assert ">TX groups</summary>" in block
    assert f'title="{TIP}"' in block


def test_tx_groups_ids_and_starts_hidden():
    page = _ops()
    assert 'id="il-section" hidden' in page
    for eid in ("il-banner", "il-meta", "il-body", "il-empty", "il-details", "il-summary"):
        assert f'id="{eid}"' in page
    assert 'id="il"' in page
    assert 'id="il-banner"' in page and "hidden" in page[page.find('id="il-banner"'):page.find('id="il-banner"') + 80]
    js = _js()
    assert "A group is a set of WSJT-X instances that must not transmit at the same time" in js
    assert "WIMS refuses Work when another instance" in js
    assert "function interlockView(" in js
    assert "function renderInterlock(" in js
    # Quiet path must not put the old always-on line back.
    assert "✓ no overlap" not in js
    assert "TX OVERLAP" not in js


def _views() -> dict:
    global _VIEWS
    if _VIEWS is not None:
        return _VIEWS
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required to render the Operate TX groups banner")
    script = r"""
const fs = require("fs");
const vm = require("vm");
const jsPath = process.argv[1];
const src = fs.readFileSync(jsPath, "utf8");

class El {
  constructor(tag) {
    this.tagName = tag || "div";
    this.hidden = false;
    this.className = "";
    this.textContent = "";
    this.title = "";
    this.open = false;
    this.style = {};
    this.children = [];
    this.id = "";
    this.dataset = {};
    this._html = "";
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    this._html = String(v);
    if (this._html === "") this.children.length = 0;
  }
  appendChild(child) { this.children.push(child); return child; }
}

const ids = {};
function make(id, tag) {
  const el = new El(tag || "div");
  el.id = id;
  ids[id] = el;
  return el;
}
const section = make("il-section", "section");
section.hidden = true;
const banner = make("il-banner", "div");
banner.hidden = true;
const details = make("il-details", "details");
const summary = make("il-summary", "summary");
summary.textContent = "TX groups";
const meta = make("il-meta", "div");
const table = make("il", "table");
const body = make("il-body", "tbody");
const empty = make("il-empty", "div");
const txMeta = make("tx-meta", "span");
make("tx-status", "span");
make("tx-halt", "button");
make("conn", "span");

const document = {
  getElementById(id) { return ids[id] || null; },
  createElement(tag) { return new El(tag); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  activeElement: null,
};
const store = {};
const context = {
  console,
  document,
  location: {pathname: "/"},
  localStorage: {
    getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem(k, v) { store[k] = String(v); },
    removeItem(k) { delete store[k]; },
  },
  EventSource: function EventSource() {},
  fetch() { return Promise.resolve({ok: true, status: 200, json: async () => ({})}); },
  setTimeout, clearTimeout,
};
context.window = context;
vm.createContext(context);

const harness = `
function ilReset() {
  _ilRefused = null;
  _ilOverlapLatched = false;
  _ilLast = null;
  const section = $("il-section");
  const banner = $("il-banner");
  const details = $("il-details");
  section.hidden = true;
  banner.hidden = true;
  banner.textContent = "";
  banner.className = "";
  details.open = false;
  $("il-body").innerHTML = "";
  $("tx-meta").textContent = "";
  $("tx-meta").className = "";
}
function ilSnap() {
  const body = $("il-body");
  const row = body.children[0];
  return {
    sectionHidden: $("il-section").hidden,
    bannerHidden: $("il-banner").hidden,
    bannerText: $("il-banner").textContent,
    bannerClass: $("il-banner").className,
    detailsOpen: $("il-details").open,
    summaryTitle: $("il-summary").title,
    rows: body.children.length,
    rowHtml: row ? row.innerHTML : "",
    rowClass: row ? row.className : "",
    txMeta: $("tx-meta").textContent,
    meta: $("il-meta").textContent,
  };
}
const quietTx = {
  grouping: "instance",
  groups: [
    {group: "20m-ft8", instances: ["20m-ft8"], transmitting: ["20m-ft8"], overlap: false},
    {group: "2m", instances: ["2m"], transmitting: [], overlap: false},
  ],
  tx_now: ["20m-ft8"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
};
const multiQuiet = {
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: [], overlap: false}],
  tx_now: [],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
};
const out = {};

ilReset();
renderInterlock(quietTx, {holders: {"20m-ft8": "20m-ft8"}});
out.quietSingle = ilSnap();

ilReset();
renderInterlock({
  grouping: "instance",
  groups: [
    {group: "20m-ft8", instances: ["20m-ft8"], transmitting: ["20m-ft8"], overlap: false},
    {group: "2m", instances: ["2m"], transmitting: ["2m"], overlap: false},
  ],
  tx_now: ["20m-ft8", "2m"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {"20m-ft8": "20m-ft8", "2m": "2m"}});
out.twoRadios = ilSnap();

ilReset();
renderInterlock(multiQuiet, {holders: {}});
out.multiQuiet = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8", "FT4"], overlap: true}],
  tx_now: ["FT8", "FT4"],
  overlap_now: true,
  violation_count: 1,
  last_violation: {group: "20m", instances: ["FT4", "FT8"], age: 1},
}, {holders: {}});
out.overlap = ilSnap();
$("il-details").open = false;
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8", "FT4"], overlap: true}],
  tx_now: ["FT8", "FT4"],
  overlap_now: true,
  violation_count: 1,
  last_violation: {group: "20m", instances: ["FT4", "FT8"], age: 2},
}, {holders: {}});
out.overlapStaysClosed = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8"], overlap: false}],
  tx_now: ["FT8"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {"20m": "FT8"}});
out.sharedTx = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: [], overlap: false}],
  tx_now: [],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {"20m": "FT8"}});
out.holderOnly = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [
    {group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8"], overlap: false},
    {group: "6m", instances: ["A", "B"], transmitting: ["A"], overlap: false},
  ],
  tx_now: ["FT8", "A"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {}});
out.twoBlocked = ilSnap();

ilReset();
renderInterlock(multiQuiet, {holders: {}});
txFlash({
  ok: false,
  error: "group_busy",
  holder: "FT8",
  detail: "Another instance holds TX in this group (FT8). Halt first.",
}, "/api/tx/work");
out.refused = ilSnap();
renderInterlock(multiQuiet, {holders: {}});
out.refusedStale = ilSnap();
renderInterlock(multiQuiet, {holders: {}});
out.refusedCleared = ilSnap();

ilReset();
renderInterlock(multiQuiet, {holders: {}});
txFlash({
  ok: false,
  error: "group_busy",
  holder: "FT8",
  detail: "Another instance holds TX in this group (FT8). Halt first.",
}, "/api/tx/work");
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8"], overlap: false}],
  tx_now: ["FT8"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {"20m": "FT8"}});
out.refusedSeen = ilSnap();
renderInterlock(multiQuiet, {holders: {}});
out.refusedReleased = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8"], transmitting: [], overlap: false}],
  tx_now: [],
  overlap_now: false,
  violation_count: 1,
  last_violation: {group: "20m", instances: ["FT8", "FT4"], age: 40},
}, {holders: {}});
out.pastOverlap = ilSnap();

ilReset();
renderInterlock({
  grouping: "band",
  groups: [{group: "20m", instances: ["FT8", "FT4"], transmitting: ["FT8", "FT4"], overlap: false}],
  tx_now: ["FT8", "FT4"],
  overlap_now: false,
  violation_count: 0,
  last_violation: null,
}, {holders: {}});
out.twoTxFlagMissed = ilSnap();

console.log(JSON.stringify(out));
`;
vm.runInContext(src + "\n" + harness, context);
"""
    proc = subprocess.run(
        [node, "-e", script, str(JS)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout or "banner script failed")
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not line:
        raise AssertionError(proc.stdout or proc.stderr or "no banner snapshot")
    _VIEWS = json.loads(line[-1])
    return _VIEWS


def test_quiet_station_hides_tx_groups():
    v = _views()
    for name in ("quietSingle", "twoRadios"):
        snap = v[name]
        assert snap["sectionHidden"] is True, name
        assert snap["bannerHidden"] is True, name
        assert snap["bannerText"] == "", name
        assert snap["detailsOpen"] is False, name


def test_multi_op_closed_list_when_quiet():
    snap = _views()["multiQuiet"]
    assert snap["sectionHidden"] is False
    assert snap["bannerHidden"] is True
    assert snap["bannerText"] == ""
    assert snap["detailsOpen"] is False
    assert snap["summaryTitle"] == TIP


def test_interlock_banner_appears_on_conflict():
    v = _views()
    overlap = v["overlap"]
    assert overlap["sectionHidden"] is False
    assert overlap["bannerHidden"] is False
    assert overlap["bannerText"] == "Overlap: 20M"
    assert overlap["bannerClass"] == "banner alarm"
    assert overlap["detailsOpen"] is True
    assert overlap["rows"] == 1
    assert "OVERLAP" in overlap["rowHtml"]
    assert overlap["rowClass"] == "overlap"

    # Operator can close the list while the overlap line stays up.
    stayed = v["overlapStaysClosed"]
    assert stayed["bannerText"] == "Overlap: 20M"
    assert stayed["bannerHidden"] is False
    assert stayed["detailsOpen"] is False

    shared = v["sharedTx"]
    assert shared["bannerHidden"] is False
    assert shared["bannerText"] == "Work blocked: 20M is transmitting"
    assert shared["bannerClass"] == "banner alarm"
    assert shared["sectionHidden"] is False
    assert shared["detailsOpen"] is False
    assert shared["rows"] == 1

    holder = v["holderOnly"]
    assert holder["bannerText"] == "Work blocked: 20M is transmitting"
    assert holder["bannerHidden"] is False

    two = v["twoBlocked"]
    assert two["bannerText"] == "Work blocked: 20M, 6M are transmitting"
    assert two["bannerHidden"] is False

    # Two transmitters must show even if the overlap flag was not set.
    missed = v["twoTxFlagMissed"]
    assert missed["bannerText"] == "Overlap: 20M"
    assert missed["bannerHidden"] is False
    assert missed["bannerClass"] == "banner alarm"

    refused = v["refused"]
    assert refused["bannerHidden"] is False
    assert refused["bannerText"] == "Work blocked: 20M is transmitting"
    assert refused["sectionHidden"] is False
    assert "Work failed:" in refused["txMeta"]
    assert "Halt first" in refused["txMeta"]
    # One stale snapshot keeps the refusal on screen. The next one drops it
    # once the holder was never actually seen.
    assert v["refusedStale"]["bannerText"] == "Work blocked: 20M is transmitting"
    assert v["refusedStale"]["bannerHidden"] is False
    assert v["refusedCleared"]["bannerHidden"] is True
    assert v["refusedCleared"]["sectionHidden"] is False  # multi-op list remains

    assert v["refusedSeen"]["bannerText"] == "Work blocked: 20M is transmitting"
    assert v["refusedReleased"]["bannerHidden"] is True
    assert v["refusedReleased"]["bannerText"] == ""


def test_past_overlap_stays_on_the_banner():
    snap = _views()["pastOverlap"]
    assert snap["sectionHidden"] is False
    assert snap["bannerHidden"] is False
    assert snap["bannerText"] == "Overlap: 20M"
    assert snap["bannerClass"] == "banner tx"
    assert snap["detailsOpen"] is False
    assert "1 overlap" in snap["meta"]


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
