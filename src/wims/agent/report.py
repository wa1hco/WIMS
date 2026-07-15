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


def _process_running(names: tuple[str, ...]) -> bool | None:
    """Return True/False if we can list processes; None if unknown."""
    names_l = {n.lower() for n in names}
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
                part = line.split(",", 1)[0].strip().strip('"').lower()
                if part in names_l:
                    return True
            return False
        out = subprocess.check_output(
            ["ps", "-A", "-o", "comm="],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
        running = {line.strip().lower() for line in out.splitlines() if line.strip()}
        return any(n in running or n.replace(".exe", "") in running for n in names_l)
    except (OSError, subprocess.SubprocessError):
        return None


def _wsjtx_section(*, fleet: bool = True) -> dict:
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
                      for sev, msg in W.validate(c, fleet=fleet)]
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


def build_report(
    *,
    agent_id: str | None = None,
    seat_id: str | None = None,
    fleet: bool = True,
    now: float | None = None,
) -> dict:
    """Full agent report (local UI and server POST body)."""
    host_name = _hostname()
    aid = (agent_id or os.environ.get("WIMS_AGENT_ID") or host_name).strip()
    sid = (seat_id or os.environ.get("WIMS_SEAT_ID") or "").strip() or None
    ts = time.time() if now is None else now

    wsjtx = _wsjtx_section(fleet=fleet)
    n1mm = probe_n1mm()
    apps = {
        "wsjtx_running": _process_running(
            ("wsjtx.exe", "wsjtx", "jt9.exe", "jt9"),
        ),
        "n1mm_running": _process_running(
            ("n1mm logger+.exe", "n1mmlogger+.exe", "n1mm logger.exe", "n1mmlogger.exe"),
        ),
    }
    summary = _summary(wsjtx, n1mm, apps)

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
        "summary": summary,
        "mode": "fleet" if fleet else "lab",
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
    lines.append(f"  found={n1.get('found')}  databases={n1.get('databases_dir') or '-'}")
    if n1.get("s3db_files"):
        lines.append(f"  s3db: {', '.join(n1['s3db_files'][:8])}")
    for iss in n1.get("issues") or []:
        tag = {"error": "!!", "warn": " ~", "info": "  "}.get(iss["severity"], "  ")
        lines.append(f"  {tag} [{iss['severity']}] {iss['message']}")
    if n1.get("ini_files"):
        lines.append(f"  scanned {len(n1['ini_files'])} ini file(s) with network-related keys")

    lines.append("")
    lines.append("Operator: fix ERROR/WARN items above, then re-run the agent.")
    lines.append("Export: same report can POST to the site WIMS server dashboard.")
    return "\n".join(lines)
