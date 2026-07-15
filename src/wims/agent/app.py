"""Local agent process: scan configs, show operator page, optional export to server.

Run:
  python -m wims.agent
  python -m wims.agent --once
  python -m wims.agent --server http://192.168.1.119:8787
  python -m wims.agent --lab --local-port 8790
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wims.agent.export import export_report  # noqa: E402
from wims.agent.report import build_report, format_report_text  # noqa: E402


class AgentState:
    """Thread-safe latest report + last export result."""

    def __init__(self):
        self._lock = threading.Lock()
        self.report: dict | None = None
        self.export_result: dict | None = None
        self.server_url: str | None = None
        self.fleet: bool = True
        self.agent_id: str | None = None
        self.seat_id: str | None = None

    def refresh(self) -> dict:
        r = build_report(
            agent_id=self.agent_id,
            seat_id=self.seat_id,
            fleet=self.fleet,
        )
        with self._lock:
            self.report = r
        return r

    def get_report(self) -> dict | None:
        with self._lock:
            return self.report

    def set_export(self, result: dict | None) -> None:
        with self._lock:
            self.export_result = result

    def get_export(self) -> dict | None:
        with self._lock:
            return self.export_result


def _page_html(state: AgentState) -> bytes:
    rep = state.get_report() or {}
    exp = state.get_export()
    text = format_report_text(rep) if rep else "(no report yet)"
    s = rep.get("summary") or {}
    sev = s.get("severity", "unknown")
    color = {"ok": "#1a7f37", "warn": "#9a6700", "error": "#cf222e"}.get(sev, "#656d76")
    exp_line = ""
    if state.server_url:
        if exp is None:
            exp_line = f"Export target: {html.escape(state.server_url)} (not yet sent)"
        elif exp.get("ok"):
            exp_line = f"Exported OK to {html.escape(str(exp.get('url') or state.server_url))}"
        else:
            err = exp.get("error") or exp.get("body") or exp
            exp_line = f"Export FAILED: {html.escape(str(err)[:300])}"
    else:
        exp_line = "No --server set; local check only (not on wrangler dashboard)."

    body = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WIMS Agent — {html.escape(str(rep.get('agent_id') or 'seat'))}</title>
<style>
  body {{ margin:0; font:14px/1.4 ui-monospace,Consolas,monospace; background:#f6f8fa; color:#1f2328; }}
  header {{ padding:10px 14px; background:#fff; border-bottom:1px solid #d0d7de; }}
  h1 {{ margin:0; font-size:16px; color:#0969da; }}
  .sum {{ margin-top:8px; padding:8px 12px; border-radius:6px; border:1px solid #d0d7de;
          background:#fff; color:{color}; font-weight:bold; }}
  main {{ padding:12px 14px; }}
  pre {{ background:#fff; border:1px solid #d0d7de; padding:12px; overflow:auto;
         white-space:pre-wrap; font-size:12px; }}
  .meta {{ color:#656d76; font-size:12px; margin:6px 0; }}
  a {{ color:#0969da; }}
  .bar {{ display:flex; gap:12px; flex-wrap:wrap; margin:8px 0; }}
  button, .btn {{ font:inherit; padding:4px 12px; cursor:pointer; }}
</style>
</head><body>
<header>
  <h1>WIMS Agent — station check</h1>
  <div class="meta">Local config / networking verification for this PC.
  Auto-refresh 15s · <a href="/">refresh</a> ·
  <a href="/api/report">JSON</a> ·
  <a href="/export">export now</a></div>
  <div class="sum">[{html.escape(sev.upper())}] {html.escape(str(s.get('message') or ''))}</div>
  <div class="meta">{html.escape(exp_line)}</div>
</header>
<main>
  <div class="bar">
    <form method="post" action="/refresh"><button type="submit">Re-scan now</button></form>
    <form method="post" action="/export"><button type="submit">Export to server</button></form>
  </div>
  <pre>{html.escape(text)}</pre>
  <p class="meta">This is the seat agent, not the site server. TX control / interlock come later.
  Site dashboard (if exported): server Status / Setup pages.</p>
</main>
</body></html>
"""
    return body.encode("utf-8")


def make_handler(state: AgentState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", _page_html(state))
            elif path == "/api/report":
                rep = state.get_report() or {}
                self._send(200, "application/json",
                           json.dumps(rep, indent=2).encode("utf-8"))
            elif path == "/healthz":
                self._send(200, "application/json", b'{"ok":true,"role":"agent"}')
            elif path == "/export":
                # GET convenience for browser link
                self._do_export()
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = urlparse(self.path).path
            # drain body
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            if path == "/refresh":
                state.refresh()
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            elif path == "/export":
                self._do_export()
            else:
                self._send(404, "text/plain", b"not found")

        def _do_export(self):
            if not state.server_url:
                self._send(400, "text/plain",
                           b"no --server configured; restart agent with --server URL")
                return
            rep = state.refresh()
            result = export_report(rep, state.server_url)
            state.set_export(result)
            # Prefer redirect back to UI
            accept = self.headers.get("Accept", "")
            if "text/html" in accept or self.command == "GET":
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self._send(200 if result.get("ok") else 502, "application/json",
                           json.dumps(result).encode("utf-8"))

    return Handler


def _bg_loop(state: AgentState, interval: float, export: bool):
    while True:
        try:
            rep = state.refresh()
            if export and state.server_url:
                state.set_export(export_report(rep, state.server_url))
        except Exception as e:
            state.set_export({"ok": False, "error": f"refresh/export: {e}"})
        time.sleep(max(5.0, interval))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="WIMS host agent — local seat config check + optional export to site server.",
    )
    ap.add_argument("--once", action="store_true",
                    help="scan once, print report, optional one-shot export, exit")
    ap.add_argument("--server", default=os_env_server(),
                    help="site server base URL (e.g. http://192.168.1.119:8787); "
                         "also WIMS_SERVER env")
    ap.add_argument("--export", action="store_true",
                    help="with --once, POST report to --server; in daemon mode, export each cycle")
    ap.add_argument("--no-export", action="store_true",
                    help="daemon: do not auto-export (local UI only; manual Export button still works)")
    ap.add_argument("--local-port", type=int, default=8790,
                    help="local operator UI port (default 8790)")
    ap.add_argument("--bind", default="127.0.0.1",
                    help="local UI bind address (default 127.0.0.1; use 0.0.0.0 for LAN view of agent)")
    ap.add_argument("--interval", type=float, default=30.0,
                    help="rescan / export interval seconds (default 30)")
    ap.add_argument("--agent-id", default=None, help="stable agent id (default: hostname)")
    ap.add_argument("--seat-id", default=None, help="contest seat label (e.g. ROY-222)")
    ap.add_argument("--lab", action="store_true",
                    help="lab mode: loopback WSJT-X UDP is warn, not error")
    args = ap.parse_args(argv)

    state = AgentState()
    state.server_url = (args.server or "").strip() or None
    state.fleet = not args.lab
    state.agent_id = args.agent_id
    state.seat_id = args.seat_id

    rep = state.refresh()
    print(format_report_text(rep))
    print()

    if args.once:
        # One-shot: push to server when --server is set (or --export with server).
        if state.server_url and (args.export or args.server):
            result = export_report(rep, state.server_url)
            state.set_export(result)
            if result.get("ok"):
                print(f"Exported OK -> {result.get('url')}")
            else:
                print(f"Export failed: {result}", file=sys.stderr)
                return 1
        errors = (rep.get("wsjtx") or {}).get("error_count", 0)
        return 1 if errors else 0

    # Daemon: local UI + background scan; export each cycle unless --no-export
    auto_export = bool(state.server_url) and not args.no_export
    if args.export:
        auto_export = bool(state.server_url)

    t = threading.Thread(
        target=_bg_loop, args=(state, args.interval, auto_export), daemon=True,
    )
    t.start()

    httpd = ThreadingHTTPServer((args.bind, args.local_port), make_handler(state))
    print(f"WIMS agent UI: http://{args.bind}:{args.local_port}/")
    if state.server_url:
        print(f"  export -> {state.server_url}/api/agents/report"
              f" ({'auto every ' + str(args.interval) + 's' if auto_export else 'manual only'})")
    else:
        print("  no --server: local verification only")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def os_env_server() -> str | None:
    import os
    return os.environ.get("WIMS_SERVER") or None


if __name__ == "__main__":
    raise SystemExit(main())
