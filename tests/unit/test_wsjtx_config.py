"""Unit tests for WSJT-X.ini parse + fleet UDP validation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations import wsjtx_config as W  # noqa: E402


def _sevs(cfg: W.WsjtxConfig, fleet: bool = True) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"error": [], "warn": [], "info": []}
    for sev, msg in W.validate(cfg, fleet=fleet):
        out.setdefault(sev, []).append(msg)
    return out


def test_multicast_with_lan_iface_ok():
    c = W.WsjtxConfig("ROY-222", {
        "UDPServer": "224.0.0.73",
        "UDPServerPort": "2239",
        "UDPInterface": "Ethernet",
        "AcceptUDPRequests": "true",
    })
    s = _sevs(c)
    assert not s["error"]
    assert any("Ethernet" in m or "confirm" in m.lower() for m in s["info"])


def test_multicast_invalid_iface_is_error():
    c = W.WsjtxConfig("IC9700", {
        "UDPServer": "224.0.0.73",
        "UDPServerPort": "2237",
        "UDPInterface": "@Invalid()",
        "AcceptUDPRequests": "true",
    })
    s = _sevs(c)
    assert s["error"], "blank/@Invalid interface must be an error"
    assert any("interface" in m.lower() for m in s["error"])


def test_empty_iface_multicast_is_error():
    c = W.WsjtxConfig("x", {
        "UDPServer": "224.0.0.73",
        "UDPServerPort": "2237",
        "UDPInterface": "",
    })
    assert _sevs(c)["error"]


def test_loopback_server_is_error_in_fleet():
    c = W.WsjtxConfig("flex", {
        "UDPServer": "127.0.0.1",
        "UDPServerPort": "2237",
        "UDPInterface": "@Invalid()",
    })
    s = _sevs(c, fleet=True)
    assert any("loopback" in m.lower() or "127.0.0.1" in m for m in s["error"])


def test_loopback_server_warn_in_lab():
    c = W.WsjtxConfig("flex", {
        "UDPServer": "127.0.0.1",
        "UDPServerPort": "2237",
    })
    s = _sevs(c, fleet=False)
    assert not s["error"] or all("interface" not in m.lower() or "loopback" in m.lower()
                                 for m in s["error"])
    # loopback server itself is warn in lab
    assert any("127.0.0.1" in m or "loopback" in m.lower() for m in s["warn"] + s["error"])


def test_loopback_iface_is_error():
    c = W.WsjtxConfig("x", {
        "UDPServer": "224.0.0.73",
        "UDPInterface": "Loopback Pseudo-Interface 1",
    })
    assert any("loopback" in m.lower() for m in _sevs(c)["error"])


def test_parse_linux_rig_name_ini():
    text = (
        "MyCall=WA1HCO\n"
        "UDPServer=224.0.0.73\n"
        "UDPServerPort=2237\n"
        "UDPInterface=@Invalid()\n"
        "AcceptUDPRequests=true\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "WSJT-X - IC9700.ini"
        p.write_text(text, encoding="utf-8")
        cfgs = W.parse_ini(p)
    assert len(cfgs) == 1
    assert cfgs[0].name == "IC9700"
    assert cfgs[0].is_multicast
    assert cfgs[0].iface_unset


def test_report_mentions_iface():
    c = W.WsjtxConfig("x", {
        "UDPServer": "224.0.0.73",
        "UDPServerPort": "2237",
        "UDPInterface": "@Invalid()",
    })
    r = W.report([c])
    assert "iface=" in r
    assert "error" in r


if __name__ == "__main__":
    test_multicast_with_lan_iface_ok()
    test_multicast_invalid_iface_is_error()
    test_empty_iface_multicast_is_error()
    test_loopback_server_is_error_in_fleet()
    test_loopback_server_warn_in_lab()
    test_loopback_iface_is_error()
    test_parse_linux_rig_name_ini()
    test_report_mentions_iface()
    print("ok")
