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

"""Local agent process: scan configs, optional local UI + export to server.

Default is **one-shot** (scan, print, optional export, exit) so operators can
double-click a check without leaving a process running. Continuous reporting
for fleet seats uses ``--daemon`` (see Start-WimsAgent-Continuous.cmd).

Discovers the site server via plane-E multicast presence (clickable console
links — zero-memory operator path) when ``--server`` / WIMS_SERVER is unset.

Run:
  python -m wims.agent
  python -m wims.agent --server http://192.168.1.119:8787
  python -m wims.agent --daemon --server http://192.168.1.119:8787
  python -m wims.agent --lab
"""

from __future__ import annotations

import argparse
import html
import json
import os
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

# Presence is optional at import time so a half-updated tree still runs the scan.
try:
    from wims.discovery import presence as P  # noqa: E402
except ImportError:  # pragma: no cover
    P = None  # type: ignore


class AgentState:
    """Thread-safe latest report + last export result + discovered site server."""

    def __init__(self):
        self._lock = threading.Lock()
        self.report: dict | None = None
        self.export_result: dict | None = None
        self.server_url: str | None = None
        self.configured_server: str | None = None  # CLI/env, may differ from discover
        self.presence: dict | None = None          # last plane-E beacon
        self.fleet: bool = True
        self.solo: bool = False
        self.agent_id: str | None = None
        self.seat_id: str | None = None
        self.presence_iface: str = "0.0.0.0"

    def refresh(self) -> dict:
        r = build_report(
            agent_id=self.agent_id,
            seat_id=self.seat_id,
            fleet=self.fleet,
            solo=self.solo,
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

    def set_presence(self, beacon: dict | None) -> None:
        with self._lock:
            self.presence = beacon
            if beacon:
                base = (beacon.get("console_base") or "").rstrip("/")
                # Prefer discovered URL when operator did not pin --server.
                if base and not self.configured_server:
                    self.server_url = base

    def get_presence(self) -> dict | None:
        with self._lock:
            return self.presence

    def discover_server(self, duration_s: float | None = None,
                        *, http_fallback: bool = True) -> dict | None:
        """UDP presence then HTTP /24 probe; update state. Returns beacon or None."""
        if P is None:
            self.set_presence(None)
            return None
        try:
            b = P.discover_site_server(
                iface=self.presence_iface,
                duration_s=duration_s if duration_s is not None else P.STARTUP_LISTEN_S,
                http_fallback=http_fallback,
            )
        except Exception as e:
            # Multicast join can fail on locked-down NICs; never crash the agent.
            print(f"  (discovery failed: {e})", file=sys.stderr)
            b = None
        self.set_presence(b)
        return b


def _presence_block_html(state: AgentState) -> str:
    """Clickable Operate / Status / Setup links from last presence beacon."""
    p = state.get_presence()
    if not p:
        return (
            '<div class="sum" style="color:#9a6700">'
            "No WIMS site server heard on the LAN (presence multicast). "
            "Start the site server on the designated PC, or set --server / WIMS_SERVER."
            "</div>"
        )
    urls = p.get("urls") or {}
    host = html.escape(str(p.get("hostname") or "?"))
    base = html.escape(str(p.get("console_base") or ""))
    op = html.escape(urls.get("operate") or (p.get("console_base") or "") + "/")
    st = html.escape(urls.get("status") or "")
    su = html.escape(urls.get("setup") or "")
    links = []
    if op:
        links.append(f'<a class="btn" href="{op}" target="_blank" rel="noopener">Operate</a>')
    if st:
        links.append(f'<a class="btn" href="{st}" target="_blank" rel="noopener">Status</a>')
    if su:
        links.append(f'<a class="btn" href="{su}" target="_blank" rel="noopener">Setup</a>')
    warn = ""
    cfg = state.configured_server
    disc = (p.get("console_base") or "").rstrip("/")
    if cfg and disc and cfg.rstrip("/") != disc:
        warn = (
            f'<div class="meta" style="color:#9a6700">Configured --server '
            f'{html.escape(cfg)} differs from discovered {html.escape(disc)} — '
            f"links use discovery; export uses configured URL.</div>"
        )
    return (
        f'<div class="panel">'
        f'<div><b>Site WIMS server</b> (heard on LAN)</div>'
        f'<div class="meta">{host} · {base}</div>'
        f'<div class="bar">{"".join(links)}</div>'
        f'{warn}'
        f"</div>"
    )


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
        exp_line = "No site server URL yet (waiting for presence or --server)."

    presence_html = _presence_block_html(state)

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
  .panel {{ margin-top:8px; padding:10px 12px; border-radius:6px; border:1px solid #d0d7de;
            background:#fff; }}
  main {{ padding:12px 14px; }}
  pre {{ background:#fff; border:1px solid #d0d7de; padding:12px; overflow:auto;
         white-space:pre-wrap; font-size:12px; }}
  .meta {{ color:#656d76; font-size:12px; margin:6px 0; }}
  a {{ color:#0969da; }}
  .bar {{ display:flex; gap:12px; flex-wrap:wrap; margin:8px 0; align-items:center; }}
  button, .btn {{ font:inherit; padding:6px 14px; cursor:pointer;
                  background:#0969da; color:#fff; border-radius:6px; text-decoration:none;
                  border:none; display:inline-block; }}
  a.btn:hover {{ filter:brightness(1.05); }}
</style>
</head><body>
<header>
  <h1>WIMS Agent — station check</h1>
  <div class="meta">Local config / networking verification for this PC.
  Auto-refresh 15s · <a href="/">refresh</a> ·
  <a href="/api/report">JSON</a> ·
  <a href="/export">export now</a></div>
  <div class="sum">[{html.escape(sev.upper())}] {html.escape(str(s.get('message') or ''))}</div>
  {presence_html}
  <div class="meta">{html.escape(exp_line)}</div>
</header>
<main>
  <div class="bar">
    <form method="post" action="/refresh"><button type="submit">Re-scan now</button></form>
    <form method="post" action="/export"><button type="submit">Export to server</button></form>
    <form method="post" action="/discover"><button type="submit">Find site server</button></form>
  </div>
  <pre>{html.escape(text)}</pre>
  <p class="meta">This is the seat agent, not the site server. Open the site console via the
  links above (discovered on the LAN) — no IP to remember. TX control / interlock come later.</p>
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
            elif path == "/api/presence":
                p = state.get_presence()
                self._send(200, "application/json",
                           json.dumps(p or {}, indent=2).encode("utf-8"))
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
            elif path == "/discover":
                state.discover_server()
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            elif path == "/export":
                self._do_export()
            else:
                self._send(404, "text/plain", b"not found")

        def _do_export(self):
            if not state.server_url:
                # One more listen before giving up.
                state.discover_server(duration_s=1.5)
            if not state.server_url:
                self._send(400, "text/plain",
                           b"no site server URL (presence not heard; set --server or WIMS_SERVER)")
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
            # Refresh discovery so clickable links stay current.
            # UDP first; HTTP fallback only if we have no server yet (scan is heavier).
            if P is not None:
                need_http = not state.server_url and not state.get_presence()
                state.discover_server(duration_s=1.2, http_fallback=need_http)
            rep = state.refresh()
            if export and state.server_url:
                state.set_export(export_report(rep, state.server_url))
        except Exception as e:
            state.set_export({"ok": False, "error": f"refresh/export: {e}"})
        time.sleep(max(5.0, interval))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="WIMS host agent — local seat config check + optional export to site server. "
                    "Default: one-shot (exit). Use --daemon for continuous report to the server.",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true", default=True,
        help="scan once, print report, optional export, exit (default)",
    )
    mode.add_argument(
        "--daemon", "--serve", action="store_true", dest="daemon",
        help="stay running: local UI on --local-port + periodic rescan/export (startup script)",
    )
    ap.add_argument("--server", default=os_env_server(),
                    help="site server base URL (e.g. http://192.168.1.119:8787); "
                         "also WIMS_SERVER env. If omitted, discover via presence multicast.")
    ap.add_argument("--export", action="store_true",
                    help="one-shot: POST report when --server is set (also implied if --server given); "
                         "daemon: force auto-export each cycle")
    ap.add_argument("--no-export", action="store_true",
                    help="do not POST (local check only; daemon Export button still works)")
    ap.add_argument("--no-discover", action="store_true",
                    help="do not listen for site-server presence multicast")
    ap.add_argument("--presence-iface", default="0.0.0.0",
                    help="interface for presence multicast join (default 0.0.0.0)")
    ap.add_argument("--local-port", type=int, default=8790,
                    help="daemon: local operator UI port (default 8790)")
    ap.add_argument("--bind", default="127.0.0.1",
                    help="daemon: local UI bind (default 127.0.0.1; 0.0.0.0 for LAN)")
    ap.add_argument("--interval", type=float, default=30.0,
                    help="daemon: rescan / export interval seconds (default 30)")
    ap.add_argument("--agent-id", default=None, help="stable agent id (default: hostname)")
    ap.add_argument("--seat-id", default=None, help="contest seat label (e.g. ROY-222)")
    ap.add_argument("--lab", action="store_true",
                    help="lab mode: loopback WSJT-X UDP is warn, not error")
    ap.add_argument("--solo", action="store_true",
                    help="single-PC tester: this PC runs N1MM + WSJT-X + the WIMS server. "
                         "Plain-language check, no site-server search (implies --no-discover).")
    args = ap.parse_args(argv)

    # --daemon wins over default --once (mutually exclusive group handles flag; if only
    # default once is True and daemon False, one-shot. argparse with store_true default
    # True is awkward: use daemon flag as the mode switch.
    run_daemon = bool(args.daemon)

    state = AgentState()
    configured = (args.server or "").strip() or None
    state.configured_server = configured
    state.server_url = configured
    state.solo = bool(args.solo)
    state.fleet = not (args.lab or args.solo)
    state.agent_id = args.agent_id
    state.seat_id = args.seat_id
    state.presence_iface = args.presence_iface or "0.0.0.0"

    # Solo = everything on one PC: there is no separate site server to hunt for, and
    # the whole output is the plain-language single-PC check. Short-circuit here.
    if args.solo:
        from wims.agent.report import format_report_solo, _counts
        rep = state.refresh()
        print(format_report_solo(rep))
        errs, _warns = _counts(rep)
        return 1 if errs else 0

    # Discovery: one-shot does full UDP + optional HTTP /24 probe. Daemon must NOT
    # block binding the local UI on a long HTTP scan — use brief UDP only here;
    # background loop continues discovery (with HTTP fallback only if still unknown).
    if not args.no_discover:
        if P is None:
            print("(presence module not installed — git pull latest; scan still runs)",
                  flush=True)
        else:
            print("Looking for site WIMS server (no IP required)…", flush=True)
            print(f"  1) UDP presence {P.DEFAULT_GROUP}:{P.DEFAULT_PORT} "
                  f"+ LAN broadcast (~{P.STARTUP_LISTEN_S:.0f}s)", flush=True)
            if not run_daemon:
                print(f"  2) if needed: HTTP probe of local /24s on "
                      f":{P.DEFAULT_HTTP_PORT}/healthz", flush=True)
            else:
                print("  2) HTTP /24 probe deferred (daemon: local UI binds first)",
                      flush=True)
            beacon = state.discover_server(http_fallback=not run_daemon)
            if beacon:
                via = beacon.get("_via") or "udp"
                print(f"  FOUND via {via}: {beacon.get('hostname')} "
                      f"{beacon.get('console_base')}", flush=True)
                urls = beacon.get("urls") or {}
                if urls.get("operate"):
                    print(f"  Operate: {urls.get('operate')}", flush=True)
                if urls.get("status"):
                    print(f"  Status:  {urls.get('status')}", flush=True)
                if urls.get("setup"):
                    print(f"  Setup:   {urls.get('setup')}", flush=True)
                print("  → open those URLs in a browser "
                      f"(or daemon UI http://{args.bind}:{args.local_port}/)",
                      flush=True)
                if configured and configured.rstrip("/") != (beacon.get("console_base") or "").rstrip("/"):
                    print(f"  note: --server {configured} differs from discovery "
                          f"(export uses configured URL; UI links use discovery)",
                          flush=True)
            else:
                print("  NOT FOUND yet. On the site PC start/restart:", flush=True)
                print("    python -m wims.server.app --iface <contest-LAN-IP>", flush=True)
                print("  Escape hatch: set WIMS_SERVER=http://x.x.x.x:8787", flush=True)
        print(flush=True)

    rep = state.refresh()
    print(format_report_text(rep), flush=True)
    print(flush=True)

    if not run_daemon:
        # One-shot: export when we have a URL unless --no-export.
        export_rc = 0
        if state.server_url and not args.no_export:
            result = export_report(rep, state.server_url)
            state.set_export(result)
            if result.get("ok"):
                print(f"Exported OK -> {result.get('url')}")
            else:
                print(f"Export failed: {result}", file=sys.stderr)
                export_rc = 2
        elif not state.server_url:
            print("(no site server URL — local check only, not sent to dashboard)")
        errors = int((rep.get("wsjtx") or {}).get("error_count", 0) or 0)
        # Non-zero means "config/export problems", not a crash of the agent process.
        if errors:
            print(
                f"\nRESULT: {errors} WSJT-X config ERROR(s) — fix the !! lines above.\n"
                f"(exit code 1 is intentional for scripts; the agent itself ran fine.)",
                file=sys.stderr,
            )
            _print_next_steps(state)
            return 1
        if export_rc:
            print(
                "\nRESULT: export to site server failed (agent scan OK).",
                file=sys.stderr,
            )
            _print_next_steps(state)
            return export_rc
        print("\nRESULT: OK (no WSJT-X config errors)")
        _print_next_steps(state)
        return 0

    # Daemon: local UI + background scan; export each cycle unless --no-export
    auto_export = bool(state.server_url) and not args.no_export
    if args.export:
        auto_export = bool(state.server_url) or not args.no_export

    t = threading.Thread(
        target=_bg_loop, args=(state, args.interval, auto_export), daemon=True,
    )
    t.start()

    try:
        httpd = ThreadingHTTPServer((args.bind, args.local_port), make_handler(state))
    except OSError as e:
        print(f"ERROR: cannot bind agent UI on {args.bind}:{args.local_port}: {e}",
              file=sys.stderr, flush=True)
        print(f"  Is another agent already using port {args.local_port}?",
              file=sys.stderr, flush=True)
        return 2

    print(f"WIMS agent UI: http://{args.bind}:{args.local_port}/  (--daemon)",
          flush=True)
    print("  open that URL on this PC for clickable site-console links (zero memory)",
          flush=True)
    if state.server_url:
        print(f"  export -> {state.server_url}/api/agents/report"
              f" ({'auto every ' + str(args.interval) + 's' if auto_export else 'manual only'})",
              flush=True)
    else:
        print("  no site server URL yet — will keep listening for presence", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


def os_env_server() -> str | None:
    return os.environ.get("WIMS_SERVER") or None


def _print_next_steps(state: AgentState) -> None:
    """One-shot footer: how to open the site console (not the same as RESULT OK)."""
    print()
    print("What this was")
    print("-------------")
    print("  Seat config check only (WSJT-X / N1MM on THIS PC).")
    print("  It is not the site console and does not open a browser by itself.")
    print()
    print("Open the site WIMS console (roster / status)")
    print("-------------------------------------------")
    p = state.get_presence()
    base = None
    if p and p.get("console_base"):
        base = p["console_base"].rstrip("/")
    elif state.server_url:
        base = state.server_url.rstrip("/")
    if base:
        print(f"  Operate:  {base}/")
        print(f"  Status:   {base}/status")
        print(f"  Setup:    {base}/setup")
        print("  (paste into a browser on any machine that can reach that host)")
    else:
        print("  No server URL yet — presence multicast was not heard and --server")
        print("  / WIMS_SERVER was not set. On the site PC, start/restart:")
        print("    python -m wims.server.app --iface <LAN-IP> ...")
        print("  and confirm it prints: presence announce 224.0.0.73:8788")
        print("  Or pin the URL on this seat:")
        print("    set WIMS_SERVER=http://192.168.1.119:8787")
        print("    python scripts\\run_agent.py")
        print("  Then open that URL in the browser.")
    print()
    print("Clickable links on this seat (zero memory)")
    print("------------------------------------------")
    print("  python scripts\\run_agent.py --daemon")
    print("  then open  http://127.0.0.1:8790/")
    print("  (local agent page; uses presence or WIMS_SERVER for Operate/Status/Setup)")
    print()
    print("Send this seat's report to the wrangler dashboard")
    print("------------------------------------------------")
    if state.server_url:
        print(f"  Export target: {state.server_url}")
        print("  One-shot already POSTs unless you used --no-export.")
        print("  Continuous:  scripts\\windows\\Start-WimsAgent-Continuous.cmd")
    else:
        print("  Set WIMS_SERVER or wait until presence finds the site server, then re-run")
        print("  or use --daemon so Status → Seat agents updates.")


if __name__ == "__main__":
    raise SystemExit(main())