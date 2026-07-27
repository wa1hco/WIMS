# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for experimental GridTracker UDP bridge."""

from __future__ import annotations

import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import encode as E  # noqa: E402
from wims.udp import messages as M  # noqa: E402
from wims.udp.gt_bridge import (  # noqa: E402
    DEFAULT_GT_BRIDGE_PORT,
    DEFAULT_GT_FORWARD_PORT,
    GridTrackerBridge,
    message_type_name,
    parse_host_port,
    peek_message_type,
)


def test_parse_host_port():
    assert parse_host_port("192.168.1.50:22370") == ("192.168.1.50", 22370)
    assert parse_host_port("192.168.1.50") == ("192.168.1.50", DEFAULT_GT_FORWARD_PORT)
    assert DEFAULT_GT_FORWARD_PORT != DEFAULT_GT_BRIDGE_PORT


def test_peek_reply_type():
    raw = E.build_reply(
        "WSJT-X", time_ms=1000, snr=-10, delta_time=0.1,
        delta_frequency=500, message="CQ K1ABC FN42", mode="~",
    )
    assert peek_message_type(raw) == M.REPLY
    assert message_type_name(M.REPLY) == "Reply"


def test_forward_and_control_roundtrip():
    """Bridge forwards WSJT→GT peer and relays Reply→control_addr."""
    # GT peer: listens for forwarded traffic.
    gt_peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gt_peer.bind(("127.0.0.1", 0))
    gt_peer.settimeout(1.0)
    gt_port = gt_peer.getsockname()[1]

    # Fake WSJT MessageClient control port.
    wsjt_ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    wsjt_ctrl.bind(("127.0.0.1", 0))
    wsjt_ctrl.settimeout(1.0)
    ctrl_port = wsjt_ctrl.getsockname()[1]

    logs: list[str] = []
    # Bind bridge on ephemeral local port to avoid colliding with a live WIMS.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    bind_port = probe.getsockname()[1]
    probe.close()

    br = GridTrackerBridge(
        "127.0.0.1", gt_port,
        bind_host="127.0.0.1",
        bind_port=bind_port,
        control_enabled=True,
        control_addr_for=lambda mid: [("127.0.0.1", ctrl_port)] if mid else [],
        log=logs.append,
    )
    try:
        # --- forward path ---
        decode = E.build_decode(
            "W10VM-144", time_ms=12_000, snr=-8, delta_time=0.2,
            delta_frequency=800, mode="~", message="CQ N1MM FN42",
            low_confidence=False, off_air=False,
        )
        br.forward_wsjt(decode)
        got, addr = gt_peer.recvfrom(65535)
        assert got == decode
        assert br.forwarded == 1

        # --- reverse path (simulates GT sending Reply to bridge bind port) ---
        reply = E.build_reply(
            "W10VM-144", time_ms=12_000, snr=-8, delta_time=0.2,
            delta_frequency=800, message="CQ N1MM FN42", mode="~",
        )
        # Inject as if received from GT (use handle_gt_datagram directly).
        r = br.handle_gt_datagram(reply, ("127.0.0.1", 9))
        assert r.get("ok") is True
        assert r.get("type") == "Reply"
        ctrl_got, _ = wsjt_ctrl.recvfrom(65535)
        assert ctrl_got == reply
        assert br.control_fwd == 1

        # Non-control Status should not be forwarded to WSJT.
        status = E.build_status(
            "W10VM-144", 144_174_000, mode="FT8", dx_call="",
            de_call="WA1HCO", de_grid="FN42", decoding=True,
        )
        r2 = br.handle_gt_datagram(status, ("127.0.0.1", 9))
        assert r2.get("ok") is False
        assert br.control_drop >= 1
    finally:
        br.close()
        gt_peer.close()
        wsjt_ctrl.close()


def test_control_disabled_drops_reply():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    bind_port = probe.getsockname()[1]
    probe.close()
    br = GridTrackerBridge(
        "127.0.0.1", 9,
        bind_host="127.0.0.1",
        bind_port=bind_port,
        control_enabled=False,
        control_addr_for=lambda mid: [("127.0.0.1", 1)],
        log=lambda _m: None,
    )
    try:
        reply = E.build_reply(
            "X", time_ms=1, snr=0, delta_time=0.0,
            delta_frequency=0, message="CQ A B", mode="~",
        )
        r = br.handle_gt_datagram(reply, ("127.0.0.1", 1))
        assert r.get("error") == "control_disabled"
        assert br.control_fwd == 0
    finally:
        br.close()


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
            failed += 1
    raise SystemExit(1 if failed else 0)
