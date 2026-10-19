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

"""Operate status-line wording. Display only — Work and Halt are not sent.

The page script formats the line. These checks load it in node the way the
browser would and read the text and the hover back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "wims" / "server" / "static" / "wims.js"
APP = ROOT / "src" / "wims" / "server" / "app.py"

WORK_DETAIL = (
    "Work PY3FSN on id='WSJT-X - flex' via reply+configure "
    "→ [127.0.0.1:34669]. Non-CQ line: Configure filled DX Call/Grid."
)
WORK_FULL = (
    "→ Work PY3FSN on WSJT-X - flex (reply+configure) → 127.0.0.1:34669 · "
    + WORK_DETAIL
)
ROUTE_DETAIL = (
    "Cannot reach 127.0.0.1:34669. This computer has no path to that "
    "WSJT-X address. Check that both computers are on the same network, "
    "then try Work again."
)
SEND_DETAIL = "UDP Work PY3FSN → [('127.0.0.1', 34669)] could not send (err 22): bad dest"

_VIEW = None


def _views() -> dict:
    global _VIEW
    if _VIEW is not None:
        return _VIEW
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required to format the Operate status line")
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
    this.style = {};
    this.children = [];
    this.id = "";
    this.dataset = {};
  }
}

const ids = {};
function make(id, tag) {
  const el = new El(tag || "div");
  el.id = id;
  ids[id] = el;
  return el;
}
make("tx-meta", "span");
make("conn", "span");

const scheduled = [];
let seq = 0;
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
  EventSource: function EventSource() { this.close = function () {}; },
  fetch() { return Promise.resolve({ok: true, status: 200, json: async () => ({})}); },
  setTimeout(fn, ms) {
    seq += 1;
    scheduled.push({id: seq, fn, ms, on: true});
    return seq;
  },
  clearTimeout(id) {
    for (const rec of scheduled) if (rec.id === id) rec.on = false;
  },
};
context.window = context;
vm.createContext(context);

function fire(ms) {
  const due = scheduled.filter(rec => rec.on && rec.ms === ms);
  for (const rec of due) {
    rec.on = false;
    rec.fn();
  }
}
context.fire = fire;
context.scheduled = scheduled;

const harness = `
function snap() {
  const m = $("tx-meta");
  return {
    text: m.textContent,
    title: m.title,
    className: m.className,
    opacity: m.style.opacity || "",
    pending: scheduled.filter(rec => rec.on).map(rec => rec.ms),
  };
}
const work = {
  ok: true,
  sent: "reply+configure",
  instance: "WSJT-X - flex",
  call: "PY3FSN",
  message: "CQ PY3FSN GF15",
  dest: ["127.0.0.1", 34669],
  dests: [["127.0.0.1", 34669]],
  detail: ${JSON.stringify(WORK_DETAIL)},
};
const out = {};
out.success = txStatusLine(work, "/api/tx/work");
out.successLoose = txStatusLine(Object.assign({}, work, {instance: "WSJT-X flex"}), "/api/tx/work");
out.successBare = txStatusLine(Object.assign({}, work, {instance: "flex"}), "/api/tx/work");
out.successReply = txStatusLine(Object.assign({}, work, {sent: "reply"}), "/api/tx/work");
out.halt = txStatusLine({
  ok: true,
  halted: ["WSJT-X - flex"],
  bands: ["6m"],
  detail: "Halted 6m started from this console.",
}, "/api/tx/halt");
out.haltTwo = txStatusLine({
  ok: true,
  halted: ["WSJT-X - flex", "WSJT-X - 2m"],
  bands: ["2m", "6m"],
  detail: "Halted 2m, 6m started from this console.",
}, "/api/tx/halt");
out.haltNone = txStatusLine({
  ok: true, halted: [], bands: [],
  detail: "No TX started from this console to halt.",
}, "/api/tx/halt");

function refusal(error, detail, url, extra) {
  const body = Object.assign({ok: false, error: error, detail: detail}, extra || {});
  return txStatusLine(body, url || "/api/tx/work");
}
out.noRoute = refusal("no_control_port",
  "No UDP control address for 'WSJT-X - flex' yet. Wait until that WSJT-X shows Status (Accept UDP requests on).");
out.noRouteSend = refusal("send_failed", ${JSON.stringify(ROUTE_DETAIL)});
out.decodeOnly = refusal("decode_only",
  "'WSJT-X - flex' is marked decode-only in seat-profile.json. Work the TX-capable instance, or change the mark on Setup.");
out.interlock = refusal("group_busy",
  "Another instance holds TX in this group (WSJT-X - 2m). Halt first.",
  "/api/tx/work", {holder: "WSJT-X - 2m"});
out.claim = refusal("other_dashboard",
  "That instance was started from another console.", "/api/tx/halt");
out.sendOther = refusal("send_failed", ${JSON.stringify(SEND_DETAIL)});
out.readOnly = refusal("tx_disabled", "Server started with --no-tx (read-only). Restart without --no-tx.");
out.unknownRow = refusal("unknown_row", "Row aged out or unknown — wait for a fresh decode, then Work again.");
out.band = refusal("band_mismatch", "Row is 6m but 'WSJT-X - flex' is on 2m. Work only same-band lines (or QSY WSJT-X back first).");
out.dial = refusal("dial_mismatch", "Decode was at dial 50313000 Hz; instance is now 144174000 Hz. Work a line heard on the current dial.");

txFlash(work, "/api/tx/work");
out.shown = snap();
fire(TX_STATUS_FADE_MS);
out.fading = snap();
fire(TX_STATUS_FADE_OUT_MS);
out.faded = snap();

txFlash(work, "/api/tx/work");
fire(TX_STATUS_FADE_MS);
txFlash({
  ok: true,
  halted: ["WSJT-X - flex"],
  bands: ["6m"],
  detail: "Halted 6m started from this console.",
}, "/api/tx/halt");
out.replaced = snap();

txFlash(work, "/api/tx/work");
txFlash({
  ok: false,
  error: "group_busy",
  holder: "WSJT-X - 2m",
  detail: "Another instance holds TX in this group (WSJT-X - 2m). Halt first.",
}, "/api/tx/work");
out.replacedByRefusal = snap();

console.log(JSON.stringify(out));
`;
vm.runInContext(src + "\n" + harness, context);
"""
    # The detail strings are substituted above as JSON literals.
    script = script.replace("${JSON.stringify(WORK_DETAIL)}", json.dumps(WORK_DETAIL))
    script = script.replace("${JSON.stringify(ROUTE_DETAIL)}", json.dumps(ROUTE_DETAIL))
    script = script.replace("${JSON.stringify(SEND_DETAIL)}", json.dumps(SEND_DETAIL))
    proc = subprocess.run(
        [node, "-e", script, str(JS)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout or "status-line script failed")
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not line:
        raise AssertionError(proc.stdout or proc.stderr or "no status-line snapshot")
    _VIEW = json.loads(line[-1])
    return _VIEW


def _plain(name: str) -> dict:
    view = _views()[name]
    assert view["prominent"] is True, name
    assert view["fade"] is False, name
    assert view["text"].count(".") == 1, name
    assert "127.0.0.1" not in view["text"], name
    assert "UDP" not in view["text"], name
    assert "seat-profile" not in view["text"], name
    return view


def test_success_is_the_short_rig_name():
    view = _views()["success"]
    assert view["text"] == "Working PY3FSN on flex"
    assert view["title"] == WORK_FULL
    assert "reply+configure" in view["title"]
    assert "127.0.0.1:34669" in view["title"]
    assert WORK_DETAIL in view["title"]
    assert view["prominent"] is False
    assert view["fade"] is True
    assert "127.0.0.1" not in view["text"]
    assert "reply+configure" not in view["text"]
    assert _views()["successLoose"]["text"] == "Working PY3FSN on flex"
    assert _views()["successBare"]["text"] == "Working PY3FSN on flex"
    reply = _views()["successReply"]
    assert reply["text"] == "Working PY3FSN on flex"
    assert "(reply)" not in reply["title"]
    assert "→ 127.0.0.1:34669" in reply["title"]


def test_halt_uses_the_short_rig_name():
    view = _views()["halt"]
    assert view["text"] == "Halted flex"
    assert view["title"] == "halted 6M · Halted 6m started from this console."
    assert view["prominent"] is False
    assert view["fade"] is True
    assert _views()["haltTwo"]["text"] == "Halted flex + 2m"
    none = _views()["haltNone"]
    assert none["text"] == "No TX started from this console to halt."
    assert none["fade"] is False
    assert none["prominent"] is False


def test_no_route_is_one_sentence():
    waiting = _plain("noRoute")
    assert waiting["text"] == (
        "No path to that radio yet, so wait until it shows up and try Work again."
    )
    assert "No UDP control address" in waiting["title"]
    assert waiting["title"].startswith("Work failed:")
    unreachable = _plain("noRouteSend")
    assert unreachable["text"] == (
        "No path to that radio, so check that both computers are on the same "
        "network and try Work again."
    )
    assert "127.0.0.1:34669" in unreachable["title"]
    other = _plain("sendOther")
    assert other["text"] == "That Work did not reach the radio, so try again."
    assert "127.0.0.1" in other["title"]


def test_decode_only_is_one_sentence():
    view = _plain("decodeOnly")
    assert view["text"] == (
        "That seat only listens, so work the radio that transmits or change the mark on Setup."
    )
    assert "seat-profile.json" in view["title"]
    assert "WSJT-X - flex" in view["title"]


def test_interlock_or_overlap_is_one_sentence():
    view = _plain("interlock")
    assert view["text"] == "Another radio is transmitting, so halt it first."
    assert "Halt first" in view["title"]
    assert "WSJT-X - 2m" in view["title"]
    assert view["title"].startswith("Work failed:")


def test_claim_held_elsewhere_is_one_sentence():
    view = _plain("claim")
    assert view["text"] == "Another console is working that radio."
    assert view["title"].startswith("Halt failed:")
    assert "another console" in view["title"]


def test_other_refusals_stay_one_sentence():
    assert _plain("readOnly")["text"] == "This console is read-only, so Work cannot transmit."
    assert _plain("unknownRow")["text"] == (
        "That line is gone, so wait for a new decode and try Work again."
    )
    assert _plain("band")["text"] == (
        "That line is on a different band, so work a line on the radio's current band."
    )
    assert _plain("dial")["text"] == (
        "That line is from a different frequency, so work a line on the current dial."
    )


def test_short_line_fades_or_is_replaced():
    shown = _views()["shown"]
    assert shown["text"] == "Working PY3FSN on flex"
    assert shown["title"] == WORK_FULL
    assert shown["opacity"] == "1"
    assert shown["className"] == "meta"
    assert shown["pending"] == [4000]
    fading = _views()["fading"]
    assert fading["text"] == "Working PY3FSN on flex"
    assert fading["opacity"] == "0"
    assert fading["pending"] == [600]
    faded = _views()["faded"]
    assert faded["text"] == ""
    assert faded["title"] == ""
    replaced = _views()["replaced"]
    assert replaced["text"] == "Halted flex"
    assert replaced["opacity"] == "1"
    assert replaced["pending"] == [4000]
    refusal = _views()["replacedByRefusal"]
    assert refusal["text"] == "Another radio is transmitting, so halt it first."
    assert refusal["opacity"] == "1"
    assert refusal["className"] == "meta warn"
    assert refusal["pending"] == []
    assert "Halt first" in refusal["title"]


def test_server_log_lines_unchanged():
    src = APP.read_text(encoding="utf-8")
    assert 'print(f"TX Work ok {inst!r} {call!r} msg={msg_text!r} "' in src
    assert 'print(f"TX Halt ok {t!r} → [{dest_s}]", flush=True)' in src
    assert "TX Work could not send" in src


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
