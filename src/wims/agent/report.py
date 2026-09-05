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
import sys
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
    return sorted({n["ipv4"] for n in _netif_addrs() if n.get("ipv4")})


def _netif_addrs() -> list[dict]:
    """NIC name → IPv4 for WSJT-X Outgoing interface (needs names like ``enp3s0``).

    Prefers ``ip -br -4 addr`` (Linux). Falls back to ioctl per ``if_nameindex``.
    Skips loopback and interfaces with no IPv4.
    """
    rows: list[dict] = []
    # Fast path: iproute2 brief table — "enp3s0 UP 192.168.1.181/24"
    try:
        out = subprocess.check_output(
            ["ip", "-br", "-4", "addr"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            name, state = parts[0], parts[1]
            if name == "lo" or name.startswith("lo:"):
                continue
            ipv4 = None
            for tok in parts[2:]:
                if "/" in tok and not tok.startswith("fe80"):
                    ipv4 = tok.split("/", 1)[0]
                    break
            if ipv4 and not ipv4.startswith("127."):
                rows.append({"name": name, "ipv4": ipv4, "state": state})
        if rows:
            # Also list UP links that have no IPv4 yet (WSJT-X still needs the name).
            try:
                link = subprocess.check_output(
                    ["ip", "-br", "link"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2,
                )
                have = {r["name"] for r in rows}
                for line in link.splitlines():
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    name, state = parts[0], parts[1]
                    if name in have or name == "lo" or name.startswith("lo"):
                        continue
                    if "UP" in state.upper():
                        rows.append({"name": name, "ipv4": "(no IPv4)", "state": state})
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            return rows
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    # Fallback: enumerate interfaces + SIOCGIFADDR (Linux/macOS).
    try:
        import fcntl
        import struct

        for _idx, name in socket.if_nameindex():
            if name == "lo" or name.startswith("lo"):
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    ifreq = struct.pack("256s", name[:15].encode("utf-8"))
                    res = fcntl.ioctl(s.fileno(), 0x8915, ifreq)  # SIOCGIFADDR
                    ip = socket.inet_ntoa(res[20:24])
                finally:
                    s.close()
            except OSError:
                continue
            if ip and not ip.startswith("127."):
                rows.append({"name": name, "ipv4": ip, "state": "?"})
    except (OSError, AttributeError, ImportError, ValueError):
        pass

    if rows:
        return rows

    # Last resort: IPs without names (WSJT-X still needs a name — operator picks).
    for ip in _lan_ips_fallback():
        rows.append({"name": "?", "ipv4": ip, "state": "?"})
    return rows


def _lan_ips_fallback() -> list[str]:
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
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


def _looks_like_wsjtx_cmdline(s: str) -> bool:
    """True if *s* is a real wsjtx.exe command line (not WMIC noise)."""
    low = (s or "").lower().strip()
    if not low:
        return False
    # WMIC / CIM empty-result noise that must never count as "running".
    if "no instance" in low:
        return False
    if low in ("commandline", "name", "processid"):
        return False
    if "wims" in low and "agent" in low:
        return False
    if "jt9" in low and "wsjtx" not in low:
        return False
    # Require the binary name somewhere (path or bare).
    if "wsjtx.exe" in low:
        return True
    parts = low.split()
    if not parts:
        return False
    base = Path(parts[0].strip('"')).name
    return base in ("wsjtx", "wsjtx.exe") or base.endswith("wsjtx.exe")


def _windows_wsjtx_cmdlines() -> list[str] | None:
    """Return wsjtx.exe CommandLine strings, or None if process list unavailable."""
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Prefer CIM/PowerShell — WMIC is removed/broken on many Win11 images and
    # often prints "No Instance(s) Available." which must not look like argv.
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='wsjtx.exe'\" | "
        "ForEach-Object { $_.CommandLine }"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=12,
            creationflags=creation,
        )
        return [ln.strip() for ln in out.splitlines() if _looks_like_wsjtx_cmdline(ln)]
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name='wsjtx.exe'", "get", "CommandLine"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            creationflags=creation,
        )
        return [ln.strip() for ln in out.splitlines() if _looks_like_wsjtx_cmdline(ln)]
    except (OSError, subprocess.SubprocessError):
        return None


def _wsjtx_running_rig_names() -> set[str] | None:
    """Rig-names of live ``wsjtx`` processes (not jt9 helpers).

    Returns:
      - ``None`` if process list unavailable
      - empty set if WSJT-X is not running
      - ``{"(active/default)"}`` and/or named ``--rig-name`` values
    """
    try:
        if os.name == "nt":
            lines = _windows_wsjtx_cmdlines()
            if lines is None:
                # Last resort: image-name only (no --rig-name).
                running = _process_running(("wsjtx.exe", "wsjtx"), substrings=())
                if running:
                    return {"(active/default)"}
                if running is False:
                    return set()
                return None
        else:
            out = subprocess.check_output(
                ["ps", "-eo", "args="],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=8,
            )
            lines = []
            for ln in out.splitlines():
                if _looks_like_wsjtx_cmdline(ln):
                    lines.append(ln.strip())
    except (OSError, subprocess.SubprocessError):
        return None

    if not lines:
        return set()

    import re
    names: set[str] = set()
    for s in lines:
        m = re.search(r"--rig-name(?:=|\s+)(\S+)", s)
        if m:
            names.add(m.group(1).strip("\"'"))
        else:
            names.add("(active/default)")
    return names


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
    running_names = _wsjtx_running_rig_names()
    configs: list[dict] = []
    error_count = 0
    warn_count = 0
    idle_error_count = 0
    for path in paths:
        try:
            parsed = W.parse_ini(path)
        except OSError as e:
            configs.append({
                "name": path.name,
                "source": str(path),
                "running": False,
                "issues": [{"severity": "error", "message": f"cannot read: {e}"}],
            })
            error_count += 1
            continue
        for c in parsed:
            raw_issues = [{"severity": sev, "message": msg}
                          for sev, msg in W.validate(c, fleet=fleet, solo=solo)]
            # Never treat every on-disk --rig-name profile as live.
            # empty set → not running (config does not matter).
            # None (unknown) → also do not score as live; loopback .ini must not
            # red-banner a seat where WSJT-X is simply closed.
            if running_names is None:
                is_running = False
            else:
                is_running = c.name in running_names
            n_err = sum(1 for i in raw_issues if i["severity"] == "error")
            n_warn = sum(1 for i in raw_issues if i["severity"] == "warn")
            if is_running:
                issues = raw_issues
                error_count += n_err
                warn_count += n_warn
            else:
                idle_error_count += n_err
                # Idle profiles: keep for JSON tooling, but never as operator errors.
                issues = [
                    {
                        "severity": "info",
                        "message": f"Unused profile (not running): {i['message']}",
                    }
                    for i in raw_issues
                    if i["severity"] in ("error", "warn")
                ]
            configs.append({
                "name": c.name,
                "source": c.source or str(path),
                "running": is_running,
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
            "idle_error_count": 0,
            "running_names": sorted(running_names) if running_names is not None else None,
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
        "idle_error_count": idle_error_count,
        "running_names": sorted(running_names) if running_names is not None else None,
        "issues": [],
    }


def _summary(wsjtx: dict, n1mm: dict, apps: dict) -> dict:
    """One plain-language headline for the operator and the dashboard.

    Prefer issues on **running** WSJT-X instances. Idle ``--rig-name`` profiles
    (e.g. an old IC7300.ini while hamlib NET rigctl is in use) must not claim
    the UDP server is 127.0.0.1 when the live instance is correct.
    """
    msgs: list[tuple[str, str]] = []  # severity, message
    idle_bad: list[str] = []

    for cfg in wsjtx.get("configs") or []:
        name = cfg.get("name") or "?"
        running = cfg.get("running", True)
        for iss in cfg.get("issues") or []:
            if iss["severity"] not in ("error", "warn"):
                continue
            if running:
                msgs.append((iss["severity"], f"WSJT-X [{name}]: {iss['message']}"))
            elif iss["severity"] == "error" and name not in idle_bad:
                idle_bad.append(name)

    for iss in wsjtx.get("issues") or []:
        if iss["severity"] in ("error", "warn"):
            msgs.append((iss["severity"], iss["message"]))
    for iss in n1mm.get("issues") or []:
        if iss["severity"] in ("error", "warn"):
            msgs.append((iss["severity"], f"N1MM: {iss['message']}"))

    if apps.get("wsjtx_running") is False and (wsjtx.get("configs") or wsjtx.get("ini_paths")):
        msgs.append(("warn", "WSJT-X does not appear to be running on this PC"))
    if (
        apps.get("n1mm_running") is False
        and n1mm.get("found")
        and not n1mm.get("leftover_data")
    ):
        msgs.append(("info", "N1MM does not appear to be running on this PC"))

    # Prefer first error on a running instance, else first warn, else ok.
    for want in ("error", "warn"):
        for sev, msg in msgs:
            if sev == want:
                return {"severity": sev, "message": msg}

    if wsjtx.get("configs"):
        running = [c for c in wsjtx["configs"] if c.get("running")]
        if running and not any(
            i.get("severity") == "error"
            for c in running for i in (c.get("issues") or [])
        ):
            names = ", ".join(c.get("name") or "?" for c in running)
            # Keep the headline about the live instance only.
            return {
                "severity": "ok",
                "message": f"Running WSJT-X OK ({names})",
            }
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
    n1mm = dict(probe_n1mm())
    apps = {
        # wsjtx.exe only — orphan jt9 must not look like "WSJT-X is running".
        "wsjtx_running": _process_running(
            ("wsjtx.exe", "wsjtx"),
            substrings=(),
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
    # Linux/macOS often keep a copied Documents/N1MM Logger+ tree with no Logger
    # installed — same rule as launcher seat_detect: not an N1MM seat.
    leftover = (
        bool(n1mm.get("found"))
        and not apps["n1mm_running"]
        and not sys.platform.startswith("win")
    )
    n1mm["leftover_data"] = leftover
    if leftover:
        where = (n1mm.get("roots") or [None])[0] or n1mm.get("databases_dir") or "?"
        n1mm["issues"] = [{
            "severity": "info",
            "message": (
                f"Leftover N1MM data under {where} — ignored on this PC "
                "(N1MM is not running; not an N1MM seat)."
            ),
        }]
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
            "netifs": _netif_addrs(),
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


def _wsjtx_shown(wx: dict, apps: dict) -> tuple[list[dict], int, bool]:
    """Live configs to show, unused count, and whether WSJT-X looks stopped."""
    configs = wx.get("configs") or []
    shown = [c for c in configs if c.get("running")]
    rn = wx.get("running_names")
    known_stopped = (apps.get("wsjtx_running") is False) or (rn == [])
    if not shown and configs and not known_stopped:
        shown = [c for c in configs if c.get("name") == "(active/default)"]
        if not shown:
            shown = [
                c for c in configs
                if str(c.get("udp_server") or "").startswith("224.")
            ][:1]
        if not shown:
            shown = configs[:1]
    idle_n = max(0, len(configs) - len(shown))
    if known_stopped and not shown:
        idle_n = 0
    return shown, idle_n, known_stopped


def _wsjtx_rig_label(c: dict) -> str:
    name = (c.get("name") or "?").strip()
    if name in ("(active/default)", "WSJT-X", "wsjtx"):
        return "default"
    if name.lower().startswith("wsjt-x - "):
        return name[9:].strip() or "default"
    return name


def _wsjtx_accept_label(c: dict) -> str:
    v = str(c.get("accept_udp") or "").strip().lower()
    if v in ("true", "1", "yes", "on"):
        return "yes"
    if v in ("false", "0", "no", "off"):
        return "no"
    return v or "-"


def _wsjtx_note(c: dict) -> str:
    """One short note for the table (worst issue severity)."""
    issues = c.get("issues") or []
    if not issues:
        return "ok"
    order = {"error": 0, "warn": 1, "info": 2}
    best = min(issues, key=lambda i: order.get(i.get("severity"), 9))
    sev = best.get("severity") or "info"
    msg = (best.get("message") or "").strip()
    # Keep the cell short — full text still in Details / hover via HTML title.
    if sev == "error":
        return "ERROR"
    if sev == "warn":
        return "WARN"
    if "outgoing interface" in msg.lower() or "contest lan" in msg.lower():
        return "check iface"
    return "info"


def _format_wsjtx_table_lines(
    shown: list[dict],
    idle_n: int,
    known_stopped: bool,
    wx: dict,
) -> list[str]:
    """Fixed-column WSJT-X table for console / local status."""
    lines: list[str] = []
    configs = wx.get("configs") or []
    if not configs:
        lines.append("  (no WSJT-X configs found)")
        return lines
    if known_stopped and not shown:
        lines.append("  (WSJT-X not running on this PC)")
        lines.append(
            f"  ({len(configs)} profile(s) on disk — start WSJT-X to audit live)"
        )
        return lines

    # Column widths tuned for common fleet names without wrapping in a 100-char terminal.
    hdr = (
        f"  {'Rig':<16} {'Call':<8} {'Grid':<6} {'UDP':<18} "
        f"{'Iface':<14} {'Acc':<3} {'Note':<12}"
    )
    sep = (
        f"  {'-'*16} {'-'*8} {'-'*6} {'-'*18} "
        f"{'-'*14} {'-'*3} {'-'*12}"
    )
    lines.append(hdr)
    lines.append(sep)
    for c in shown:
        udp = f"{c.get('udp_server') or '-'}:{c.get('udp_port') or '-'}"
        iface = (c.get("udp_iface") or "(empty)").strip() or "(empty)"
        lines.append(
            f"  {_wsjtx_rig_label(c)[:16]:<16} "
            f"{(c.get('my_call') or '-')[:8]:<8} "
            f"{(c.get('my_grid') or '-')[:6]:<6} "
            f"{udp[:18]:<18} "
            f"{iface[:14]:<14} "
            f"{_wsjtx_accept_label(c)[:3]:<3} "
            f"{_wsjtx_note(c)[:12]:<12}"
        )
    # Issue details under the table (full text, one per line — not in the wide row).
    detail_lines: list[str] = []
    for c in shown:
        for iss in c.get("issues") or []:
            if iss.get("severity") == "info" and _wsjtx_note(c) in ("ok", "check iface", "info"):
                # Collapse routine iface info — table Note already says check iface.
                if "outgoing interface" in (iss.get("message") or "").lower():
                    continue
            tag = {"error": "!!", "warn": " ~", "info": "  "}.get(iss["severity"], "  ")
            detail_lines.append(
                f"  {tag} {_wsjtx_rig_label(c)}: [{iss['severity']}] {iss['message']}"
            )
    if detail_lines:
        lines.append("")
        lines.extend(detail_lines)
    if idle_n:
        lines.append(f"  ({idle_n} unused profile(s) on disk — not shown)")
    for iss in wx.get("issues") or []:
        lines.append(f"  !! [{iss['severity']}] {iss['message']}")
    return lines


def format_wsjtx_html_table(report: dict) -> str:
    """HTML table for the local status page (no long wrapping lines)."""
    import html as _html

    wx = report.get("wsjtx") or {}
    apps = report.get("apps") or {}
    shown, idle_n, known_stopped = _wsjtx_shown(wx, apps)
    configs = wx.get("configs") or []
    if not configs:
        return "<p class=\"meta\">No WSJT-X configs found.</p>"
    if known_stopped and not shown:
        return (
            "<p class=\"meta\">WSJT-X not running on this PC "
            f"({len(configs)} profile(s) on disk).</p>"
        )

    rows = []
    for c in shown:
        udp = f"{_html.escape(str(c.get('udp_server') or '-'))}:" \
              f"{_html.escape(str(c.get('udp_port') or '-'))}"
        iface = _html.escape((c.get("udp_iface") or "(empty)").strip() or "(empty)")
        note = _wsjtx_note(c)
        note_cls = {
            "ok": "ok", "ERROR": "err", "WARN": "warn",
            "check iface": "warn", "info": "warn",
        }.get(note, "")
        # Full issue text as title tooltip on the Note cell.
        tips = "; ".join(
            f"{i.get('severity')}: {i.get('message')}"
            for i in (c.get("issues") or [])
        )
        title = f" title=\"{_html.escape(tips)}\"" if tips else ""
        src = _html.escape(str(c.get("source") or ""))
        rows.append(
            "<tr>"
            f"<td title=\"{src}\">{_html.escape(_wsjtx_rig_label(c))}</td>"
            f"<td>{_html.escape(str(c.get('my_call') or '-'))}</td>"
            f"<td>{_html.escape(str(c.get('my_grid') or '-'))}</td>"
            f"<td class=\"mono\">{udp}</td>"
            f"<td class=\"mono\">{iface}</td>"
            f"<td>{_html.escape(_wsjtx_accept_label(c))}</td>"
            f"<td class=\"ln {note_cls}\"{title}>{_html.escape(note)}</td>"
            "</tr>"
        )
    foot = ""
    if idle_n:
        foot = f"<p class=\"meta\">{idle_n} unused profile(s) on disk — not shown.</p>"
    return (
        "<table class=\"wsjt\">"
        "<thead><tr>"
        "<th>Rig</th><th>Call</th><th>Grid</th><th>UDP</th>"
        "<th>Iface</th><th>Acc</th><th>Note</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"{foot}"
    )


def format_report_text(report: dict, *, skip_wsjtx: bool = False) -> str:
    """Human-readable text for console / local page.

    ``skip_wsjtx=True`` omits the WSJT-X block (local status page renders it as HTML).
    """
    lines: list[str] = []
    h = report.get("host") or {}
    s = report.get("summary") or {}
    lines.append("WIMS agent — seat configuration check")
    lines.append("=" * 48)
    lines.append(f"agent_id : {report.get('agent_id')}")
    if report.get("seat_id"):
        lines.append(f"seat_id  : {report.get('seat_id')}")
    lines.append(f"host     : {h.get('hostname')}")
    netifs = h.get("netifs") or []
    if netifs:
        lines.append("netifs   :  (WSJT-X Settings → Reporting → Outgoing interface)")
        for n in netifs:
            lines.append(
                f"           {n.get('name') or '?':16}  {n.get('ipv4') or '-'}"
                + (f"  [{n.get('state')}]" if n.get("state") and n.get("state") != "?" else "")
            )
    else:
        lines.append(f"ips      : {', '.join(h.get('lan_ips') or []) or '-'}")
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

    if not skip_wsjtx:
        wx = report.get("wsjtx") or {}
        lines.append("WSJT-X")
        lines.append("-" * 48)
        shown, idle_n, known_stopped = _wsjtx_shown(wx, apps)
        lines.extend(_format_wsjtx_table_lines(shown, idle_n, known_stopped, wx))
        lines.append("")

    n1 = report.get("n1mm") or {}
    if apps.get("n1mm_running"):
        # Full section only when Logger+ is actually running on this PC.
        lines.append("N1MM")
        lines.append("-" * 48)
        lines.append(f"  running  user_dir={n1.get('user_dir') or '-'}")
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
    elif sys.platform.startswith("win") and n1.get("found") and not n1.get("leftover_data"):
        lines.append("N1MM: installed, not running")
    else:
        # Linux leftover Documents/N1MM trees, or nothing at all — one line only.
        lines.append("N1MM: not on this PC")

    lines.append("")
    # Footer only when there is something to fix — keyed off summary, not a
    # second pass over the body.
    if sev in ("error", "warn"):
        lines.append("Operator: fix ERROR/WARN items above, then Re-scan.")
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
    shown = [c for c in configs if c.get("running")]
    if not shown:
        shown = configs
    for c in shown:
        if len(shown) > 1:
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
