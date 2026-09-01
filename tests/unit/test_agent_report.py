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

"""Unit tests for seat agent report + server ingest."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.agent.report import build_report, format_report_text  # noqa: E402
from wims.agent.export import export_report  # noqa: E402
from wims.server.app import LiveFleet  # noqa: E402
from wims.server.state import agents_to_dict  # noqa: E402


def test_build_report_shape():
    r = build_report(agent_id="test-agent", seat_id="SEAT-1", fleet=True, now=1000.0)
    assert r["schema"] == 1
    assert r["agent_id"] == "test-agent"
    assert r["seat_id"] == "SEAT-1"
    assert r["ts"] == 1000.0
    assert "host" in r and "hostname" in r["host"]
    assert "wsjtx" in r and "n1mm" in r and "apps" in r
    assert r["summary"]["severity"] in ("ok", "warn", "error")
    assert isinstance(r["summary"]["message"], str)
    text = format_report_text(r)
    assert "WIMS agent" in text
    assert "WSJT-X" in text


def test_build_report_with_synthetic_ini(monkeypatch=None):
    # Write a bad fleet ini and force discover to see it.
    from wims.integrations import wsjtx_config as W
    from wims.agent import report as R

    with tempfile.TemporaryDirectory() as td:
        ini = Path(td) / "WSJT-X.ini"
        ini.write_text(
            "UDPServer=127.0.0.1\n"
            "UDPServerPort=2237\n"
            "UDPInterface=@Invalid()\n"
            "AcceptUDPRequests=false\n"
            "MyCall=W1AW\n"
            "MyGrid=FN31\n",
            encoding="utf-8",
        )
        old = W.discover_ini_paths
        old_run = R._wsjtx_running_rig_names
        W.discover_ini_paths = lambda: [ini]  # type: ignore
        # Pretend this default profile is the live instance.
        R._wsjtx_running_rig_names = lambda: {"(active/default)"}  # type: ignore
        try:
            r = build_report(agent_id="vm1", fleet=True, now=1.0)
            assert r["wsjtx"]["error_count"] >= 1
            assert r["summary"]["severity"] == "error"
            assert r["wsjtx"]["configs"]
            cfg = r["wsjtx"]["configs"][0]
            assert cfg["udp_server"] == "127.0.0.1"
            assert cfg.get("running") is True
            sevs = {i["severity"] for i in cfg["issues"]}
            assert "error" in sevs
        finally:
            W.discover_ini_paths = old
            R._wsjtx_running_rig_names = old_run


def test_idle_bad_profile_does_not_override_running_ok():
    """Unused IC7300.ini on loopback must not headline when live instance is OK."""
    from wims.integrations import wsjtx_config as W
    from wims.agent import report as R

    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "WSJT-X.ini"
        bad = Path(td) / "WSJT-X - IC7300.ini"
        good.write_text(
            "UDPServer=224.0.0.73\n"
            "UDPServerPort=2237\n"
            "UDPInterface=enp13s0f1\n"
            "AcceptUDPRequests=true\n"
            "MyCall=W1AW\n"
            "MyGrid=FN31\n",
            encoding="utf-8",
        )
        bad.write_text(
            "UDPServer=127.0.0.1\n"
            "UDPServerPort=2237\n"
            "UDPInterface=@Invalid()\n"
            "AcceptUDPRequests=false\n"
            "MyCall=W1AW\n"
            "MyGrid=FN31\n",
            encoding="utf-8",
        )
        old = W.discover_ini_paths
        old_run = R._wsjtx_running_rig_names
        W.discover_ini_paths = lambda: [good, bad]  # type: ignore
        R._wsjtx_running_rig_names = lambda: {"(active/default)"}  # type: ignore
        try:
            r = build_report(agent_id="vm1", fleet=True, now=1.0)
            assert r["wsjtx"]["error_count"] == 0  # only running instance
            assert r["summary"]["severity"] == "ok"
            assert "127.0.0.1" not in r["summary"]["message"]
            assert "IC7300" not in r["summary"]["message"]
            by_name = {c["name"]: c for c in r["wsjtx"]["configs"]}
            assert by_name["(active/default)"]["running"] is True
            assert by_name["IC7300"]["running"] is False
            # Idle issues must not remain severity=error in the report.
            assert all(i["severity"] != "error" for i in by_name["IC7300"]["issues"])
            text = format_report_text(r)
            assert "(active/default)" in text
            assert "224.0.0.73" in text
            assert "IC7300" not in text  # idle profiles hidden from operator text
            assert "unused profile" in text.lower()
        finally:
            W.discover_ini_paths = old
            R._wsjtx_running_rig_names = old_run


def test_unknown_process_list_does_not_mark_all_running():
    """If argv detection fails, do not score .ini as live (no loopback red banner)."""
    from wims.integrations import wsjtx_config as W
    from wims.agent import report as R

    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "WSJT-X.ini"
        bad = Path(td) / "WSJT-X - IC7300.ini"
        good.write_text(
            "UDPServer=224.0.0.73\nUDPServerPort=2237\n"
            "UDPInterface=eth0\nAcceptUDPRequests=true\nMyCall=W1AW\nMyGrid=FN31\n",
            encoding="utf-8",
        )
        bad.write_text(
            "UDPServer=127.0.0.1\nUDPServerPort=2237\n"
            "UDPInterface=@Invalid()\nAcceptUDPRequests=false\nMyCall=W1AW\nMyGrid=FN31\n",
            encoding="utf-8",
        )
        old = W.discover_ini_paths
        old_run = R._wsjtx_running_rig_names
        old_proc = R._process_running
        W.discover_ini_paths = lambda: [good, bad]  # type: ignore
        R._wsjtx_running_rig_names = lambda: None  # type: ignore  # detection failed
        R._process_running = lambda *a, **k: False  # type: ignore
        try:
            r = build_report(agent_id="vm1", fleet=True, now=1.0)
            assert all(not c.get("running") for c in r["wsjtx"]["configs"])
            assert "127.0.0.1" not in r["summary"]["message"]
            text = format_report_text(r)
            assert "not running on this PC" in text.lower()
            assert "IC7300" not in text
        finally:
            W.discover_ini_paths = old
            R._wsjtx_running_rig_names = old_run
            R._process_running = old_proc


def test_wmic_no_instance_noise_is_not_running():
    """Windows WMIC empty noise must not mark (active/default) as live."""
    from wims.agent.report import _looks_like_wsjtx_cmdline

    assert not _looks_like_wsjtx_cmdline("No Instance(s) Available.")
    assert not _looks_like_wsjtx_cmdline("CommandLine")
    assert _looks_like_wsjtx_cmdline(
        r'"C:\Program Files\WSJT-X\wsjtx.exe" --rig-name=IC9700'
    )
    assert _looks_like_wsjtx_cmdline(r"C:\WSJT\wsjtx.exe")


def test_empty_process_list_marks_nothing_running():
    """Empty set means WSJT-X is not running — do not pretend default.ini is live."""
    from wims.integrations import wsjtx_config as W
    from wims.agent import report as R

    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "WSJT-X.ini"
        good.write_text(
            "UDPServer=224.0.0.73\nUDPServerPort=2237\n"
            "UDPInterface=eth0\nAcceptUDPRequests=true\nMyCall=W1AW\nMyGrid=FN31\n",
            encoding="utf-8",
        )
        old = W.discover_ini_paths
        old_run = R._wsjtx_running_rig_names
        old_proc = R._process_running
        W.discover_ini_paths = lambda: [good]  # type: ignore
        R._wsjtx_running_rig_names = lambda: set()  # type: ignore
        R._process_running = lambda *a, **k: False  # type: ignore
        try:
            r = build_report(agent_id="vm1", fleet=True, now=1.0)
            by_name = {c["name"]: c for c in r["wsjtx"]["configs"]}
            assert by_name["(active/default)"]["running"] is False
            assert r["wsjtx"]["running_names"] == []
            assert r["apps"]["wsjtx_running"] is False
            assert "not appear to be running" in r["summary"]["message"].lower()
            text = format_report_text(r)
            assert "not running on this PC" in text.lower()
            assert "UDP 224.0.0.73" not in text  # do not audit as live
        finally:
            W.discover_ini_paths = old
            R._wsjtx_running_rig_names = old_run
            R._process_running = old_proc


def test_livefleet_accept_agent_and_snapshot():
    live = LiveFleet()
    body = {
        "schema": 1,
        "agent_id": "win10-template",
        "seat_id": "TEMPLATE-01",
        "ts": 500.0,
        "host": {"hostname": "WIN10VM", "lan_ips": ["192.168.1.50"], "os": "Windows"},
        "wsjtx": {"configs": [], "error_count": 0, "warn_count": 0, "issues": []},
        "n1mm": {"found": False, "issues": []},
        "apps": {"wsjtx_running": False, "n1mm_running": False},
        "summary": {"severity": "warn", "message": "no WSJT-X configs"},
        "mode": "fleet",
    }
    res = live.accept_agent_report(body, now=500.0)
    assert res["ok"] is True
    snap = live.snapshot(now=501.0)
    assert "agents" in snap
    assert len(snap["agents"]) == 1
    a = snap["agents"][0]
    assert a["agent_id"] == "win10-template"
    assert a["seat_id"] == "TEMPLATE-01"
    assert a["severity"] == "warn"
    assert a["health"] == "ALIVE"
    assert a["age"] == 1.0


def test_agents_to_dict_stale():
    agents = {
        "a1": {
            "agent_id": "a1",
            "ts": 100.0,
            "summary": {"severity": "ok", "message": "fine"},
            "host": {"hostname": "h", "lan_ips": []},
            "wsjtx": {"configs": [], "error_count": 0, "warn_count": 0},
            "apps": {},
            "n1mm": {},
        }
    }
    rows = agents_to_dict(agents, now=100.0)
    assert rows[0]["health"] == "ALIVE"
    rows = agents_to_dict(agents, now=200.0)
    assert rows[0]["health"] == "STALE"
    rows = agents_to_dict(agents, now=400.0)
    assert rows[0]["health"] == "DEAD"


def test_export_report_no_url():
    r = export_report({"agent_id": "x"}, "")
    assert r["ok"] is False


def test_n1mm_probe_finds_userdir_databases(tmp_path, monkeypatch=None):
    """N1MM often keeps .s3db under {UserDir}/Databases, not Documents\\…\\Databases."""
    from wims.agent import n1mm_probe as N

    user = tmp_path / "User"
    dbdir = user / "Databases"
    dbdir.mkdir(parents=True)
    (dbdir / "N2OY.s3db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    (dbdir / "N2OY.s3db-wal").write_bytes(b"x" * 50)
    (dbdir / "N1MM Admin.s3db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

    real_user_dir = N._win_user_dir
    real_user_dirs = N.n1mm_user_dirs
    N._win_user_dir = lambda: user  # type: ignore
    N.n1mm_user_dirs = lambda: [user]  # type: ignore
    try:
        p = N.probe_n1mm()
        assert p["found"] is True
        assert p["databases_dir"]
        assert "N2OY.s3db" in p["s3db_files"]
        assert "N2OY.s3db" in (p.get("open_databases") or [])
        assert not any("No N1MM Databases folder" in (i.get("message") or "")
                       for i in p["issues"])
    finally:
        N._win_user_dir = real_user_dir
        N.n1mm_user_dirs = real_user_dirs


def test_process_match_n1mmlogger_net_via_tasklist_mock():
    """N1MM Logger+ image is N1MMLogger.net.exe — old exact names missed it.

    Force the Windows tasklist branch even on Linux so the mock is exercised
    portably (seat agents run on Win; CI/dev often runs tests on Linux).
    """
    import os
    import subprocess
    from wims.agent import report as R

    fake = (
        '"chrome.exe","1","Console","1","1 K"\r\n'
        '"N1MMLogger.net.exe","6216","Console","1","70 K"\r\n'
        '"wsjtx.exe","8128","Console","1","100 K"\r\n'
    )
    real_out = subprocess.check_output
    real_name = os.name

    def fake_check_output(cmd, **kwargs):
        if cmd and cmd[0] == "tasklist":
            return fake
        return real_out(cmd, **kwargs)

    subprocess.check_output = fake_check_output  # type: ignore
    os.name = "nt"  # type: ignore[misc]
    try:
        assert R._process_running(
            ("n1mm logger+.exe",),
            substrings=("n1mmlogger",),
        ) is True
        assert R._process_running(
            ("n1mmlogger.net.exe", "n1mmlogger.net"),
        ) is True
        assert R._process_running(("not-a-real-app.exe",)) is False
        assert R._process_running(("wsjtx.exe",), substrings=("wsjtx",)) is True
    finally:
        subprocess.check_output = real_out
        os.name = real_name  # type: ignore[misc]


def main():
    test_build_report_shape()
    test_build_report_with_synthetic_ini()
    test_livefleet_accept_agent_and_snapshot()
    test_agents_to_dict_stale()
    test_export_report_no_url()
    test_process_match_n1mmlogger_net_via_tasklist_mock()
    # No pytest: drive the tmp_path test with a real TemporaryDirectory.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_n1mm_probe_finds_userdir_databases(Path(td))
    print("test_agent_report: OK")


if __name__ == "__main__":
    main()
