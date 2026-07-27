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

"""Build a seat agent report: host, WSJT-X configs, N1MM probe, process hints."""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from pathlib import Path

from wims.agent.n1mm_probe import probe_n1mm
from wims.integrations import wsjtx_config as W


SCHEMA = 1


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _lan_ips() -> list[str]:
    """Best-effort non-loopback IPv4 addresses for this host."""
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    # UDP trick: discover primary outbound interface IP (no packet sent).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
        finally:
            s.close()
    except OSError:
        pass
    return sorted(ips)


def _process_running(names: tuple[str, ...], *, substrings: tuple[str, ...] = ()) -> bool | None:
    """Return True/False if we can list processes; None if unknown.

    `names` are exact image names (with or without .exe). `substrings` match if
    they appear in the process image name (e.g. ``n1mmlogger`` catches
    N1MMLogger.net.exe on Windows).
    """
    names_l = {n.lower() for n in names}
    names_l |= {n if n.endswith(".exe") else n + ".exe" for n in names_l}
    names_l |= {n[:-4] for n in list(names_l) if n.endswith(".exe")}
    subs = tuple(s.lower() for s in substrings if s)

    def _match(image: str) -> bool:
        img = image.lower().strip()
        if not img:
            return False
        if img in names_l:
            return True
        stem = img[:-4] if img.endswith(".exe") else img
        if stem in names_l:
            return True
        return any(s in img for s in subs)

    try:
        if os.name == "nt":
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in out.splitlines():
                # "image.exe","pid",...
                part = line.split(",", 1)[0].strip().strip('"')
                if _match(part):
                    return True
            return False
        out = subprocess.check_output(
            ["ps", "-A", "-o", "comm="],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
        for line in out.splitlines():
            if _match(line.strip()):
                return True
        return False
    except (OSError, subprocess.SubprocessError):
        return None


def _wsjtx_section(*, fleet: bool = True, solo: bool = False) -> dict:
    paths = W.discover_ini_paths()
    configs: list[dict] = []
    error_count = 0
    warn_count = 0
    for path in paths:
        try:
            parsed = W.parse_ini(path)
        except OSError as e:
            configs.append({
                "name": path.name,
                "source": str(path),
                "issues": [{"severity": "error", "message": f"cannot read: {e}"}],
            })
            error_count += 1
            continue
        for c in parsed:
            issues = [{"severity": sev, "message": msg}
                      for sev, msg in W.validate(c, fleet=fleet, solo=solo)]
            error_count += sum(1 for i in issues if i["severity"] == "error")
            warn_count += sum(1 for i in issues if i["severity"] == "warn")
            configs.append({
                "name": c.name,
                "source": c.source or str(path),
                "udp_server": c.g("UDPServer"),
                "udp_port": c.g("UDPServerPort"),
                "udp_iface": c.g("UDPInterface"),
                "udp_ttl": c.g("UDPTTL"),
                "accept_udp": c.g("AcceptUDPRequests"),
                "my_call": c.g("MyCall"),
                "my_grid": c.g("MyGrid"),
                "issues": issues,
            })
    if not paths:
        return {
            "ini_paths": [],
            "configs": [],
            "error_count": 1,
            "warn_count": 0,
            "issues": [{
                "severity": "warn",
                "message": (
                    "No WSJT-X.ini found on this host — install WSJT-X or pass a path; "
                    "fleet seats need UDP Server=multicast and Outgoing interface=LAN NIC"
                ),
            }],
        }
    return {
        "ini_paths": [str(p) for p in paths],
        "configs": configs,
        "error_count": error_count,
        "warn_count": warn_count,
        "issues": [],
    }


def _summary(wsjtx: dict, n1mm: dict, apps: dict) -> dict:
    """One plain-language headline for the operator and the dashboard."""
    msgs: list[tuple[str, str]] = []  # severity, message

    for cfg in wsjtx.get("configs") or []:
        for iss in cfg.get("issues") or []:
            if iss["severity"] in ("error", "warn"):
                msgs.append((iss["severity"], f"WSJT-X [{cfg.get('name')}]: {iss['message']}"))
    for iss in wsjtx.get("issues") or []:
        if iss["severity"] in ("error", "warn"):
            msgs.append((iss["severity"], iss["message"]))
    for iss in n1mm.get("issues") or []:
        if iss["severity"] in ("error", "warn"):
            msgs.append((iss["severity"], f"N1MM: {iss['message']}"))

    if apps.get("wsjtx_running") is False and (wsjtx.get("configs") or wsjtx.get("ini_paths")):
        msgs.append(("warn", "WSJT-X does not appear to be running on this PC"))
    if apps.get("n1mm_running") is False and n1mm.get("found"):
        msgs.append(("info", "N1MM does not appear to be running on this PC"))

    # Prefer first error, else first warn, else ok.
    for want in ("error", "warn"):
        for sev, msg in msgs:
            if sev == want:
                return {"severity": sev, "message": msg}
    if wsjtx.get("configs"):
        return {
            "severity": "ok",
            "message": (
                f"WSJT-X config OK for fleet check "
                f"({len(wsjtx['configs'])} config(s)); confirm N1MM Broadcast Data on LAN"
            ),
        }
    return {
        "severity": "warn",
        "message": "No WSJT-X configs audited — install/configure WSJT-X for this seat",
    }


def _rotators_from_env() -> list[dict]:
    """Optional rotator status for agent → server (plan §3.3.1 / §2.10).

    ``WIMS_ROTATOR_REPORT`` = JSON list of rotator objects, or a single object.
    Minimal lab form without K3NG:

      WIMS_ROTATOR_ID=ROT-6M
      WIMS_ROTATOR_AZ=45
      WIMS_ROTATOR_INSTANCES=WSJT-X

    Full TCP/serial poll is a later agent step; this ships the status path.
    """
    raw = (os.environ.get("WIMS_ROTATOR_REPORT") or "").strip()
    if raw:
        try:
            import json
            data = json.loads(raw)
            if isinstance(data, dict):
                return [data]
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except (json.JSONDecodeError, TypeError):
            pass
    rid = (os.environ.get("WIMS_ROTATOR_ID") or "").strip()
    if not rid:
        return []
    az_s = (os.environ.get("WIMS_ROTATOR_AZ") or "").strip()
    az = None
    try:
        az = float(az_s) if az_s else None
    except ValueError:
        az = None
    inst = [x.strip() for x in (os.environ.get("WIMS_ROTATOR_INSTANCES") or "").split(",")
            if x.strip()]
    return [{
        "id": rid,
        "az": az,
        "moving": False,
        "link_ok": True,
        "health": "OK",
        "instances": inst,
        "label": rid,
    }]


def build_report(
    *,
    agent_id: str | None = None,
    seat_id: str | None = None,
    fleet: bool = True,
    solo: bool = False,
    now: float | None = None,
) -> dict:
    """Full agent report (local UI and server POST body). `solo` = single-PC tester
    lens (this PC runs N1MM + WSJT-X + the WIMS server)."""
    host_name = _hostname()
    aid = (agent_id or os.environ.get("WIMS_AGENT_ID") or host_name).strip()
    sid = (seat_id or os.environ.get("WIMS_SEAT_ID") or "").strip() or None
    ts = time.time() if now is None else now

    wsjtx = _wsjtx_section(fleet=fleet, solo=solo)
    n1mm = probe_n1mm()
    apps = {
        "wsjtx_running": _process_running(
            ("wsjtx.exe", "wsjtx", "jt9.exe", "jt9"),
            substrings=("wsjtx",),
        ),
        # N1MM Logger+ ships as N1MMLogger.net.exe (not "N1MM Logger+.exe").
        "n1mm_running": _process_running(
            (
                "n1mmlogger.net.exe",
                "n1mmlogger.net",
                "n1mm logger+.exe",
                "n1mmlogger+.exe",
                "n1mm logger.exe",
                "n1mmlogger.exe",
            ),
            substrings=("n1mmlogger", "n1mm logger"),
        ),
    }
    summary = _summary(wsjtx, n1mm, apps)
    rotators = _rotators_from_env()

    return {
        "schema": SCHEMA,
        "agent_id": aid,
        "seat_id": sid,
        "ts": ts,
        "host": {
            "hostname": host_name,
            "lan_ips": _lan_ips(),
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "wsjtx": wsjtx,
        "n1mm": n1mm,
        "apps": apps,
        "rotators": rotators,
        "summary": summary,
        "mode": "solo" if solo else ("fleet" if fleet else "lab"),
    }


def format_report_text(report: dict) -> str:
    """Human-readable text for console / local page."""
    lines: list[str] = []
    h = report.get("host") or {}
    s = report.get("summary") or {}
    lines.append("WIMS agent — seat configuration check")
    lines.append("=" * 48)
    lines.append(f"agent_id : {report.get('agent_id')}")
    if report.get("seat_id"):
        lines.append(f"seat_id  : {report.get('seat_id')}")
    lines.append(f"host     : {h.get('hostname')}  ips={', '.join(h.get('lan_ips') or []) or '-'}")
    lines.append(f"os       : {h.get('os')}")
    lines.append(f"mode     : {report.get('mode')}")
    apps = report.get("apps") or {}
    lines.append(
        f"apps     : wsjtx_running={apps.get('wsjtx_running')}  "
        f"n1mm_running={apps.get('n1mm_running')}"
    )
    lines.append("")
    sev = s.get("severity", "?")
    mark = {"ok": "OK", "warn": "WARN", "error": "ERROR"}.get(sev, sev.upper())
    lines.append(f"SUMMARY [{mark}]: {s.get('message', '')}")
    lines.append("")

    wx = report.get("wsjtx") or {}
    lines.append("WSJT-X")
    lines.append("-" * 48)
    if wx.get("ini_paths"):
        for p in wx["ini_paths"]:
            lines.append(f"  ini: {p}")
    else:
        lines.append("  (no ini paths)")
    for c in wx.get("configs") or []:
        lines.append(f"  [{c.get('name')}]  ({c.get('source')})")
        lines.append(
            f"    UDP {c.get('udp_server') or '-'}:{c.get('udp_port') or '-'} "
            f"iface={c.get('udp_iface') or '(empty)'} "
            f"acceptUDP={c.get('accept_udp') or '-'}"
        )
        lines.append(f"    Stn {c.get('my_call') or '-'} / {c.get('my_grid') or '-'}")
        for iss in c.get("issues") or []:
            tag = {"error": "!!", "warn": " ~", "info": "  "}.get(iss["severity"], "  ")
            lines.append(f"    {tag} [{iss['severity']}] {iss['message']}")
    for iss in wx.get("issues") or []:
        lines.append(f"  !! [{iss['severity']}] {iss['message']}")

    n1 = report.get("n1mm") or {}
    lines.append("")
    lines.append("N1MM")
    lines.append("-" * 48)
    lines.append(f"  found={n1.get('found')}  user_dir={n1.get('user_dir') or '-'}")
    db_dirs = n1.get("databases_dirs") or (
        [n1["databases_dir"]] if n1.get("databases_dir") else []
    )
    lines.append(f"  databases={', '.join(db_dirs) if db_dirs else '-'}")
    if n1.get("s3db_files"):
        lines.append(f"  contest s3db: {', '.join(n1['s3db_files'][:12])}")
    if n1.get("open_databases"):
        lines.append(f"  likely open (WAL): {', '.join(n1['open_databases'][:8])}")
    for iss in n1.get("issues") or []:
        tag = {"error": "!!", "warn": " ~", "info": "  "}.get(iss["severity"], "  ")
        lines.append(f"  {tag} [{iss['severity']}] {iss['message']}")
    if n1.get("ini_files"):
        lines.append(f"  ini files scanned: {len(n1['ini_files'])}")

    lines.append("")
    lines.append("Operator: fix ERROR/WARN items above, then re-run the agent.")
    lines.append("Export: same report can POST to the site WIMS server dashboard.")
    return "\n".join(lines)


OK, WARN, BAD = "[OK]", "[! ]", "[XX]"


def _solo_body(report: dict) -> tuple[list[str], int, int]:
    """Build the ✓/!/✗ body lines and count the (errors, warns) actually shown, so
    the verdict header always matches the body. Single-PC (solo) lens."""
    body: list[str] = []
    err = warn = 0

    def add(marker: str, text: str) -> None:
        nonlocal err, warn
        if marker == BAD:
            err += 1
        elif marker == WARN:
            warn += 1
        body.append(f"  {marker} {text}")

    # --- WSJT-X --------------------------------------------------------------
    wx = report.get("wsjtx") or {}
    configs = wx.get("configs") or []
    body.append("WSJT-X")
    if not configs:
        add(BAD, "No WSJT-X settings found on this PC. Is WSJT-X installed here?")
    for c in configs:
        if len(configs) > 1:
            body.append(f"  [{c.get('name')}]")
        server, port = c.get("udp_server") or "", c.get("udp_port") or "2237"
        accept = (c.get("accept_udp") or "").lower() == "true"
        call, grid = c.get("my_call") or "", c.get("my_grid") or ""
        if server:
            add(OK, f"Sending decodes to {server}:{port} — WIMS will see them.")
        else:
            add(BAD, "Not sending decodes over UDP (Settings → Reporting → tick 'UDP Server').")
        if accept:
            add(OK, "'Accept UDP requests' is ON — WIMS can Work/Halt this radio.")
        else:
            add(WARN, "'Accept UDP requests' is OFF — WIMS can watch but cannot transmit "
                      "until you tick it (Settings → Reporting).")
        if call and grid:
            add(OK, f"Station: {call} / {grid}")
        # Any remaining solo-lens issues (blank interface, missing call/grid, …). Skip
        # the 'no UDP server' error — already shown as the BAD line above.
        for i in c.get("issues") or []:
            sev, msg = i["severity"], i["message"]
            if sev == "error" and not server:
                continue
            if "Accept UDP requests" in msg:      # already surfaced above
                continue
            add(BAD if sev == "error" else WARN, msg)

    # --- N1MM ----------------------------------------------------------------
    n1 = report.get("n1mm") or {}
    body.append("")
    body.append("N1MM  (for the needed-vs-dupe roster test)")
    dbs = n1.get("databases_dirs") or ([n1["databases_dir"]] if n1.get("databases_dir") else [])
    if dbs:
        add(OK, f"Log folder found: {dbs[0]}")
        if n1.get("s3db_files"):
            add(OK, f"Log file present ({len(n1['s3db_files'])} .s3db) — dupe/needed can be tested.")
        else:
            add(WARN, "No log file yet — open a log in N1MM so dupe/needed shows in the roster.")
    else:
        add(WARN, "N1MM not detected here. Fine to just watch decodes; "
                  "run N1MM (with a log) to test needed-vs-dupe.")
    return body, err, warn


def _counts(report: dict) -> tuple[int, int]:
    """(errors, warns) as surfaced by the solo view — drives the verdict + exit code."""
    _body, err, warn = _solo_body(report)
    return err, warn


def format_report_solo(report: dict) -> str:
    """Noob-friendly single-PC setup check: a plain-language verdict, then one
    [OK]/[! ]/[XX] line per thing that matters, each with the exact WSJT-X/N1MM fix.
    No jargon, no site-server hunt — this PC runs everything."""
    body, err, warn = _solo_body(report)
    out = ["WIMS setup check — this PC", "=" * 34]
    if err:
        out.append(f"{BAD} {err} thing{'s' if err != 1 else ''} to fix before testing.")
    elif warn:
        out.append(f"{WARN} Ready to test — {warn} note{'s' if warn != 1 else ''} below.")
    else:
        out.append(f"{OK} Ready to test.")
    out.append("")
    out.extend(body)
    out.append("")
    if err:
        out.append("Fix the [XX] item(s) above, then run this check again.")
    else:
        out.append("Next: start WIMS (Start-Wims-Solo.cmd, or `python -m wims.solo`)")
        out.append("      then open  http://localhost:8787/  and watch the roster.")
    return "\n".join(out)
