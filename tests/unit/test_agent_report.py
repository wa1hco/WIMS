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
        W.discover_ini_paths = lambda: [ini]  # type: ignore
        try:
            r = build_report(agent_id="vm1", fleet=True, now=1.0)
            assert r["wsjtx"]["error_count"] >= 1
            assert r["summary"]["severity"] == "error"
            assert r["wsjtx"]["configs"]
            cfg = r["wsjtx"]["configs"][0]
            assert cfg["udp_server"] == "127.0.0.1"
            sevs = {i["severity"] for i in cfg["issues"]}
            assert "error" in sevs
        finally:
            W.discover_ini_paths = old


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


def main():
    test_build_report_shape()
    test_build_report_with_synthetic_ini()
    test_livefleet_accept_agent_and_snapshot()
    test_agents_to_dict_stale()
    test_export_report_no_url()
    print("test_agent_report: OK")


if __name__ == "__main__":
    main()
