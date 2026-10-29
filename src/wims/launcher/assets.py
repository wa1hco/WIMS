# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect running apps and remember seat **intent** (what this PC will run).

Running list = observational. Intent checkboxes = operator desire (remembered);
WIMS starts the matching agents.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Agent process ids (launcher _procs / roles).
AGENT_LOG = "log"          # legacy id; N1MM intent now starts AGENT_N1MM_SEAT
AGENT_WSJT = "wsjt"
AGENT_KEY = "key"          # legacy id; SSB/CW intent now starts AGENT_N1MM_SEAT
AGENT_N1MM_SEAT = "n1mm_seat"  # combined wims.seat (--log / --key)
AGENT_SERVER = "server"

# Seat intent checkbox ids (remembered prefs).
INTENT_N1MM = "n1mm"
INTENT_WSJT = "wsjt"
INTENT_SSB_CW = "ssb_cw"
INTENT_ANTENNAS = "antennas"
INTENT_SERVER = "server"

_ALL_AGENTS = (AGENT_LOG, AGENT_WSJT, AGENT_KEY, AGENT_N1MM_SEAT, AGENT_SERVER)
_ALL_INTENTS = (
    INTENT_N1MM, INTENT_WSJT, INTENT_SSB_CW, INTENT_ANTENNAS, INTENT_SERVER,
)

# Intent → agent to start/stop.
# N1MM + SSB/CW share one seat process. Antennas is the antenna side of
# that same seat agent (it does not start a second program).
INTENT_TO_AGENT: dict[str, str] = {
    INTENT_N1MM: AGENT_N1MM_SEAT,
    INTENT_WSJT: AGENT_WSJT,
    INTENT_SSB_CW: AGENT_N1MM_SEAT,
    INTENT_ANTENNAS: AGENT_WSJT,
    INTENT_SERVER: AGENT_SERVER,
}


@dataclass
class AssetSnapshot:
    n1mm_running: bool = False
    n1mm_found: bool = False
    wsjt_running: bool = False
    wsjt_ini_count: int = 0
    wsjt_running_names: list[str] = field(default_factory=list)

    @property
    def wsjt_present(self) -> bool:
        return self.wsjt_running or self.wsjt_ini_count > 0

    @property
    def n1mm_present(self) -> bool:
        if self.n1mm_running:
            return True
        if sys.platform.startswith("win") and self.n1mm_found:
            return True
        return False


def _intent_pref_path() -> Path:
    env = (os.environ.get("WIMS_SEAT_INTENT") or "").strip()
    if env:
        return Path(env)
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "wims" / "seat_intent.json"
    if sys.platform == "win32":
        appdata = (os.environ.get("APPDATA") or "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "wims" / "seat_intent.json"
    return Path.home() / ".config" / "wims" / "seat_intent.json"


def _read_pref_raw() -> dict:
    try:
        raw = json.loads(_intent_pref_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _write_pref_raw(raw: dict) -> None:
    path = _intent_pref_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(raw, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_seat_intent() -> dict[str, bool]:
    """Remembered seat intent checkboxes for this PC."""
    raw = _read_pref_raw()
    intent = raw.get("intent") or {}
    return {k: bool(intent.get(k)) for k in _ALL_INTENTS}


def seat_intent_saved() -> bool:
    """True when this PC has a stored intent (including all-unchecked)."""
    raw = _read_pref_raw()
    return isinstance(raw.get("intent"), dict)


def seed_intent_from_assets(snap: AssetSnapshot) -> dict[str, bool]:
    """First-run defaults: start agents for apps this PC actually has.

    N1MM installed/running → N1MM agent. WSJT-X running, or WSJT-X present
    on a non-N1MM PC (ini on disk) → Seat agent. Never auto-enables KEY
    (needs a COM pick), Antennas (needs a rotator address), or Site server
    (one per LAN).
    """
    n1mm = bool(snap.n1mm_present)
    wsjt = bool(snap.wsjt_running) or (bool(snap.wsjt_present) and not n1mm)
    return {
        INTENT_N1MM: n1mm,
        INTENT_WSJT: wsjt,
        INTENT_SSB_CW: False,
        INTENT_ANTENNAS: False,
        INTENT_SERVER: False,
    }


def missing_intent_agent_labels(
    intent: dict[str, bool],
    *,
    n1mm_seat_up: bool,
    wsjt_up: bool,
    server_up: bool,
) -> list[str]:
    """Wanted agents that are not up (N1MM + KEY share one process)."""
    missing: list[str] = []
    if (intent.get(INTENT_N1MM) or intent.get(INTENT_SSB_CW)) and not n1mm_seat_up:
        missing.append("N1MM agent")
    if (intent.get(INTENT_WSJT) or intent.get(INTENT_ANTENNAS)) and not wsjt_up:
        missing.append("Seat agent")
    if (
        intent.get(INTENT_SERVER)
        and not server_up
        and not is_wsjt_only_seat(intent)
    ):
        missing.append("Site server")
    return missing


def save_seat_intent(intent: dict[str, bool]) -> None:
    raw = _read_pref_raw()
    raw["schema"] = max(2, int(raw.get("schema") or 1))
    raw["intent"] = {k: bool(intent.get(k)) for k in _ALL_INTENTS}
    _write_pref_raw(raw)


def load_key_device() -> str:
    """Remembered KEY/CTS device path (COM port or /dev/tty…)."""
    env = (os.environ.get("WIMS_KEY_DEVICE") or "").strip()
    if env:
        return env
    raw = _read_pref_raw()
    return str(raw.get("key_device") or "").strip()


def new_antenna_id() -> str:
    """Opaque id for one remembered antenna. Not a host or a port."""
    return "ant-" + uuid.uuid4().hex[:8]


def new_device_id() -> str:
    """Opaque id for one device on an antenna."""
    return "dev-" + uuid.uuid4().hex[:8]


def _clean_opaque_id(raw_id: object, used: set[str], prefix: str) -> str:
    rid = str(raw_id or "").strip()
    if not rid or ":" in rid or rid in used or len(rid) > 32:
        rid = prefix + uuid.uuid4().hex[:8]
        while rid in used:
            rid = prefix + uuid.uuid4().hex[:8]
    return rid


def _port_of(raw: dict) -> int | None:
    port_raw = raw.get("port")
    if port_raw is None or str(port_raw).strip() == "":
        return None
    try:
        port_i = int(str(port_raw).strip())
    except (TypeError, ValueError):
        return None
    if 1 <= port_i <= 65535:
        return port_i
    return None


def _remembered_device(raw: object, used: set[str]) -> dict | None:
    """One device on an antenna.

    Rotator devices remember host and port for rotctld. Tuner and switch
    are kept as a kind only — this step does not store a serial path and
    does not open one.
    """
    if not isinstance(raw, dict):
        return None
    from wims.integrations.antenna.model import DEVICE_KINDS, KIND_ROTATOR
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in DEVICE_KINDS:
        if raw.get("host") or raw.get("port") is not None:
            kind = KIND_ROTATOR
        else:
            return None
    rid = _clean_opaque_id(raw.get("id"), used, "dev-")
    used.add(rid)
    entry: dict = {"id": rid, "kind": kind}
    if kind != KIND_ROTATOR:
        return entry
    host = str(raw.get("host") or "").strip()[:253]
    if any(ch.isspace() for ch in host):
        host = ""
    entry["host"] = host
    port = _port_of(raw)
    if port is not None:
        entry["port"] = port
    return entry


def _remembered_antenna(raw: object, used_ant: set[str], used_dev: set[str]) -> dict | None:
    """One antenna and its devices. A half-typed name is kept."""
    if not isinstance(raw, dict):
        return None
    name = " ".join(str(raw.get("name") or "").split())[:24]
    devices: list[dict] = []
    raw_devices = raw.get("devices")
    if isinstance(raw_devices, list):
        for item in raw_devices:
            dev = _remembered_device(item, used_dev)
            if dev:
                devices.append(dev)
    if not name and not devices:
        return None
    rid = _clean_opaque_id(raw.get("id"), used_ant, "ant-")
    used_ant.add(rid)
    return {"id": rid, "name": name, "devices": devices}


def _clean_antennas(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []
    used_ant: set[str] = set()
    used_dev: set[str] = set()
    out: list[dict] = []
    for item in items:
        ant = _remembered_antenna(item, used_ant, used_dev)
        if ant:
            out.append(ant)
    return out


def load_antennas() -> list[dict]:
    """Remembered antennas on this PC (name, and each device)."""
    raw = _read_pref_raw()
    return _clean_antennas(raw.get("antennas"))


def save_antennas(items: list) -> None:
    """Persist antennas beside seat intent. No flag and no env var."""
    raw = _read_pref_raw()
    raw["schema"] = max(2, int(raw.get("schema") or 1))
    if not isinstance(raw.get("intent"), dict):
        raw["intent"] = {k: False for k in _ALL_INTENTS}
    raw["antennas"] = _clean_antennas(items)
    _write_pref_raw(raw)


def load_antenna_side() -> tuple[bool, list[dict]] | None:
    """``(antennas_checked, antennas)``.

    ``None`` when the seat file exists but could not be read (a save in
    progress). A missing file is Antennas off and an empty list.
    """
    path = _intent_pref_path()
    if not path.is_file():
        return False, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    intent = raw.get("intent") if isinstance(raw.get("intent"), dict) else {}
    on = bool(intent.get(INTENT_ANTENNAS))
    return on, _clean_antennas(raw.get("antennas"))


def save_key_device(device: str) -> None:
    """Persist KEY device; also mirrors into WIMS_KEY_DEVICE for child processes."""
    device = (device or "").strip()
    raw = _read_pref_raw()
    raw["schema"] = max(2, int(raw.get("schema") or 1))
    if "intent" not in raw:
        raw["intent"] = {k: False for k in _ALL_INTENTS}
    raw["key_device"] = device
    _write_pref_raw(raw)
    if device:
        os.environ["WIMS_KEY_DEVICE"] = device
    else:
        os.environ.pop("WIMS_KEY_DEVICE", None)


def detect_assets() -> AssetSnapshot:
    snap = AssetSnapshot()
    try:
        from wims.agent.report import _process_running, _wsjtx_running_rig_names
        from wims.agent.n1mm_probe import probe_n1mm
        from wims.integrations.wsjtx_config import discover_ini_paths

        snap.n1mm_running = bool(
            _process_running(
                ("n1mmlogger.net.exe", "n1mmlogger.net", "n1mm logger+.exe",
                 "n1mmlogger+.exe", "n1mm logger.exe"),
                substrings=("n1mmlogger",),
            )
        )
        snap.n1mm_found = bool(probe_n1mm().get("found"))
        snap.wsjt_running = bool(
            _process_running(("wsjtx.exe", "wsjtx"), substrings=())
        )
        snap.wsjt_ini_count = len(discover_ini_paths())
        names = _wsjtx_running_rig_names()
        if names:
            snap.wsjt_running_names = sorted(names)
    except Exception:
        pass
    return snap


def is_wsjt_only_seat(intent: dict[str, bool]) -> bool:
    """True when this PC is a WSJT-X seat (no N1MM logger)."""
    return bool(intent.get(INTENT_WSJT)) and not bool(intent.get(INTENT_N1MM))


def offer_site_server(
    intent: dict[str, bool],
    *,
    site_reachable: bool,
    local_server: bool,
) -> bool:
    """Whether the launcher should offer Site server (checkbox / Start).

    WSJT-X-only seat: never. N1MM (and dedicated host) PCs: do not offer
    when a *remote* site server is already running. Local hosting still
    shows the checkbox so the operator can stop it.
    """
    if is_wsjt_only_seat(intent):
        return False
    if site_reachable and not local_server:
        return False
    return True


def agents_for_intent(intent: dict[str, bool]) -> dict[str, bool]:
    """Which agents should be running given seat intent."""
    want_server = bool(intent.get(INTENT_SERVER)) and not is_wsjt_only_seat(intent)
    want: dict[str, bool] = {
        AGENT_WSJT: bool(intent.get(INTENT_WSJT) or intent.get(INTENT_ANTENNAS)),
        AGENT_SERVER: want_server,
        AGENT_N1MM_SEAT: bool(intent.get(INTENT_N1MM) or intent.get(INTENT_SSB_CW)),
        # Legacy keys for older UI/tests — same process as n1mm_seat.
        AGENT_LOG: bool(intent.get(INTENT_N1MM)),
        AGENT_KEY: bool(intent.get(INTENT_SSB_CW)),
    }
    return want


def n1mm_seat_flags(intent: dict[str, bool]) -> tuple[bool, bool]:
    """Return (want_log, want_key) for the combined seat process."""
    return bool(intent.get(INTENT_N1MM)), bool(intent.get(INTENT_SSB_CW))


# --- Backward-compat stubs (older tests / imports) ----------------------------

def load_wanted_agents() -> dict[str, bool]:
    """Map seat intent → agent wants (compat)."""
    return agents_for_intent(load_seat_intent())


def save_wanted_agents(wanted: dict[str, bool]) -> None:
    """Compat: treat agent ids as intent where names overlap."""
    intent = load_seat_intent()
    if AGENT_LOG in wanted:
        intent[INTENT_N1MM] = bool(wanted[AGENT_LOG])
    if AGENT_WSJT in wanted:
        intent[INTENT_WSJT] = bool(wanted[AGENT_WSJT])
    if AGENT_KEY in wanted:
        intent[INTENT_SSB_CW] = bool(wanted[AGENT_KEY])
    if AGENT_SERVER in wanted:
        intent[INTENT_SERVER] = bool(wanted[AGENT_SERVER])
    save_seat_intent(intent)


def live_checks(
    snap: AssetSnapshot,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Deprecated name — observational only; do not drive intent checkboxes."""
    _ = site_reachable
    return {
        AGENT_LOG: bool(snap.n1mm_running),
        AGENT_WSJT: bool(snap.wsjt_running),
        AGENT_KEY: False,
        AGENT_SERVER: False,
    }


def suggested_checks(
    snap: AssetSnapshot,
    wanted: dict[str, bool] | None = None,
    *,
    site_reachable: bool = False,
) -> dict[str, bool]:
    """Compat: prefer saved intent over live detection."""
    _ = snap
    _ = site_reachable
    if wanted:
        return {k: bool(wanted.get(k)) for k in _ALL_AGENTS}
    return agents_for_intent(load_seat_intent())
