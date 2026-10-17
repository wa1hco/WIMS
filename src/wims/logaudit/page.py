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

"""Check logs in a browser window. Reads logs. Does not change them."""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import urlopen

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Check logs</title>
<style>
  body { font: 12pt sans-serif; background: #fff; color: #1f2328; margin: 28px auto;
         max-width: 46em; line-height: 1.45; }
  h1 { font-size: 16pt; font-weight: 600; margin: 0 0 8px 0; }
  button { font: 12pt sans-serif; }
  .progress { color: #656d76; }
  .summary { font-weight: 600; }
  .src { margin: 2px 0; }
  details { margin-top: 14px; }
  .group { margin: 12px 0; }
  .row { font-family: ui-monospace, monospace; font-size: 11pt; }
  .pager { margin: 6px 0 12px 0; }
  input { font: 12pt sans-serif; }
</style>
</head>
<body>
<h1>Check logs</h1>
<p>This check only reads logs. It does not change them.</p>
<p id="progress" class="progress">Looking for logs…</p>
<div id="report"></div>
<script>
const PAGE = 40;
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}
function hit(row, q) {
  if (!q) return true;
  const blob = [row.call, row.band, row.mode, row.time, row.grid, row.found_in, row.detail]
    .join(" ").toLowerCase();
  return blob.includes(q);
}
function pageOf(rows, page) {
  const start = page * PAGE;
  return rows.slice(start, start + PAGE);
}
function pager(name, page, total) {
  if (total <= PAGE) return "";
  const from = page * PAGE + 1;
  const to = Math.min(total, (page + 1) * PAGE);
  const prev = page > 0 ? `<button type="button" data-group="${esc(name)}" data-page="${page - 1}">Previous</button>` : "";
  const next = to < total ? `<button type="button" data-group="${esc(name)}" data-page="${page + 1}">Next</button>` : "";
  return `<p class="pager">${prev} ${from}–${to} of ${total} ${next}</p>`;
}
function line(row) {
  const grid = row.grid ? "  " + esc(row.grid) : "";
  const found = row.found_in ? "  (in " + esc(row.found_in) + ")" : "";
  return `<div class="row">${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}${grid}${found}</div>`;
}
function detailHtml(report, state) {
  const q = (state.filter || "").trim().toLowerCase();
  const missing = report.missing || {};
  let details = "";
  const names = Object.keys(missing).filter(name => (missing[name] || []).length);
  names.forEach(name => {
    const all = (missing[name] || []).filter(row => hit(row, q));
    const page = state.page[name] || 0;
    details += `<div class="group"><b>Missing from ${esc(name)}</b> (${all.length})` +
      pageOf(all, page).map(line).join("") + pager(name, page, all.length) + `</div>`;
  });
  const disag = (report.disagreements || []).filter(row => hit(row, q));
  if (disag.length) {
    const page = state.page.disagreements || 0;
    details += `<div class="group"><b>Different grid or mode</b> (${disag.length})` +
      pageOf(disag, page).map(row => {
        const why = row.detail && row.detail !== "grid" ? "  " + esc(row.detail) : (row.grid ? "  " + esc(row.grid) : "");
        return `<div class="row">${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}${why}</div>`;
      }).join("") + pager("disagreements", page, disag.length) + `</div>`;
  }
  const dupes = report.duplicates || [];
  if (dupes.length) {
    const extra = dupes.reduce((n, row) => n + Math.max(0, (row.count || 0) - 1), 0);
    details += `<div class="group"><b>${extra} extra cop${extra === 1 ? "y" : "ies"} collapsed</b>` +
      dupes.slice(0, PAGE).map(row =>
        `<div class="row">${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}  ×${esc(row.count)} in ${esc(row.source)}</div>`
      ).join("") + `</div>`;
  }
  if (!details) details = "<p>Nothing else to list.</p>";
  return details;
}
function bindPager(report, state) {
  document.querySelectorAll("#detail button[data-page]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.page[btn.getAttribute("data-group")] = Number(btn.getAttribute("data-page"));
      document.getElementById("detail").innerHTML = detailHtml(report, state);
      bindPager(report, state);
    });
  });
}
function paint(report, state) {
  const box = document.getElementById("report");
  const sources = (report.sources || []).map(src => {
    let extra = "";
    if (src.shared_by && src.shared_by.length > 1) {
      extra += " Same file for " + src.shared_by.map(esc).join(", ") + ".";
    }
    if (src.cached) extra += " Unchanged, so it was not read again.";
    const detail = src.detail || src.status || "";
    return `<div class="src"><b>${esc(src.name)}</b> — ${esc(detail)}.${extra}</div>`;
  }).join("");
  const notes = (report.notes || []).map(note => `<div class="src">${esc(note)}</div>`).join("");
  box.innerHTML =
    `<p class="summary">${esc(report.summary || "")}</p>` +
    sources + notes +
    `<details><summary>Show details</summary>` +
    `<p><label>Filter <input id="filt"></label></p>` +
    `<div id="detail">${detailHtml(report, state)}</div></details>`;
  const filt = document.getElementById("filt");
  if (filt) {
    filt.addEventListener("input", () => {
      state.filter = filt.value;
      state.page = {};
      document.getElementById("detail").innerHTML = detailHtml(report, state);
      bindPager(report, state);
    });
  }
  bindPager(report, state);
}
const state = {page: {}, filter: ""};
function show(report) {
  document.getElementById("progress").textContent = "";
  paint(report, state);
}
async function tick() {
  try {
    const resp = await fetch("/api/status");
    const body = await resp.json();
    if (body.state === "running" || body.state === "idle") {
      document.getElementById("progress").textContent = body.progress || "Looking for logs…";
      setTimeout(tick, 400);
      return;
    }
    show(body);
  } catch (err) {
    document.getElementById("progress").textContent = "Check logs could not be read. Leave this window open and reload the page.";
  }
}
tick();
</script>
</body>
</html>
"""


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase = "running"
        self.progress = "Looking for logs…"
        self.result: dict | None = None

    def snapshot(self) -> dict:
        with self.lock:
            if self.phase == "done" and self.result is not None:
                out = dict(self.result)
                out["state"] = "done"
                out["progress"] = ""
                return out
            return {"ok": False, "state": self.phase, "progress": self.progress, "summary": ""}


def _port_file():
    from wims.rules.choice import config_dir
    return config_dir() / "logcheck.port"


def _existing_port() -> int | None:
    path = _port_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        port = int(data.get("port") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if port <= 0:
        return None
    try:
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.4) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, URLError, json.JSONDecodeError, TimeoutError):
        return None
    if body.get("ok") and body.get("role") == "wims-log-check":
        return port
    return None


def _remember_port(port: int) -> None:
    path = _port_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": port}) + "\n", encoding="utf-8")
    except OSError:
        return


def _serve(state: _State) -> ThreadingHTTPServer:
    page = PAGE.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html"}:
                self._send(200, "text/html; charset=utf-8", page)
                return
            if path == "/healthz":
                self._send(200, "application/json",
                           json.dumps({"ok": True, "role": "wims-log-check"}).encode("utf-8"))
                return
            if path == "/api/status":
                self._send(200, "application/json",
                           json.dumps(state.snapshot()).encode("utf-8"))
                return
            self._send(404, "text/plain", b"not found")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return httpd


def _run_check(state: _State) -> None:
    from wims.logaudit.check import ui_payload
    from wims.logaudit.cli import build_report

    def progress(message: str) -> None:
        print(message, flush=True)
        with state.lock:
            if state.phase == "running":
                state.progress = message

    try:
        report = build_report([], progress=progress)
        result = ui_payload(report)
    except Exception:
        result = {
            "ok": False,
            "state": "done",
            "summary": "Check logs failed. Close any program that has a log open and try again.",
            "sources": [],
            "missing": {},
            "disagreements": [],
            "duplicates": [],
            "notes": [],
            "matched_count": 0,
        }
    with state.lock:
        state.phase = "done"
        state.progress = ""
        state.result = result


def main(argv: list[str] | None = None) -> int:
    del argv
    existing = _existing_port()
    if existing:
        url = f"http://127.0.0.1:{existing}/"
        print("Check logs is already open.", flush=True)
        webbrowser.open(url)
        return 0
    state = _State()
    httpd = _serve(state)
    port = int(httpd.server_address[1])
    _remember_port(port)
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=_run_check, args=(state,), name="wims-log-check", daemon=True).start()
    print("Opening Check logs.", flush=True)
    print("Leave this window open while you read the report.", flush=True)
    print(url, flush=True)
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
