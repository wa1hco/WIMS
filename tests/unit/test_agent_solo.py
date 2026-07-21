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

"""Agent solo (single-PC tester) lens: the fleet 'blank outgoing interface' ERROR
must become a friendly note, and the readable verdict must match the body."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.wsjtx_config import WsjtxConfig, validate  # noqa: E402
from wims.agent.report import format_report_solo, _counts, OK, WARN, BAD  # noqa: E402


def _cfg(**settings) -> WsjtxConfig:
    return WsjtxConfig(name="(active/default)", settings=settings)


def _sev(cfg) -> set:
    return {sev for sev, _ in validate(cfg, solo=True)}


def test_solo_multicast_blank_iface_is_not_error():
    # The exact real-world config that the FLEET lens flags as ERROR.
    cfg = _cfg(UDPServer="224.0.0.73", UDPServerPort="2237", UDPInterface="@Invalid()",
               AcceptUDPRequests="true", MyCall="WA1HCO", MyGrid="FN42")
    # Fleet lens: hard error. Solo lens: at most a warn, never an error.
    assert "error" in {s for s, _ in validate(cfg, fleet=True)}
    assert all(s != "error" for s, _ in validate(cfg, solo=True))


def test_solo_loopback_is_fine():
    cfg = _cfg(UDPServer="127.0.0.1", UDPServerPort="2237", UDPInterface="",
               AcceptUDPRequests="true", MyCall="WA1HCO", MyGrid="FN42")
    assert all(s != "error" for s, _ in validate(cfg, solo=True))


def test_solo_no_udp_server_is_error():
    cfg = _cfg(UDPServer="", AcceptUDPRequests="true")
    assert "error" in _sev(cfg)


def test_solo_accept_udp_off_is_warn_not_error():
    cfg = _cfg(UDPServer="224.0.0.73", UDPServerPort="2237", UDPInterface="Ethernet",
               AcceptUDPRequests="false", MyCall="WA1HCO", MyGrid="FN42")
    sevs = _sev(cfg)
    assert "warn" in sevs and "error" not in sevs


def _report(configs, n1mm=None) -> dict:
    return {"wsjtx": {"configs": configs}, "n1mm": n1mm or {"found": False}}


def test_solo_verdict_ready_when_clean():
    rep = _report(
        [{"udp_server": "224.0.0.73", "udp_port": "2237", "accept_udp": "true",
          "my_call": "WA1HCO", "my_grid": "FN42", "issues": []}],
        n1mm={"found": True, "databases_dirs": ["/db"], "s3db_files": ["x.s3db"]},
    )
    errs, warns = _counts(rep)
    assert errs == 0 and warns == 0
    text = format_report_solo(rep)
    assert text.splitlines()[2].startswith(f"{OK} Ready to test.")


def test_solo_verdict_counts_match_body():
    # accept off (warn) + no N1MM (warn) → header says "2 notes", body has 2 [! ] lines.
    rep = _report(
        [{"udp_server": "224.0.0.73", "udp_port": "2237", "accept_udp": "false",
          "my_call": "WA1HCO", "my_grid": "FN42", "issues": []}],
        n1mm={"found": False},
    )
    errs, warns = _counts(rep)
    assert errs == 0 and warns == 2
    text = format_report_solo(rep)
    assert text.count(f"  {WARN} ") == 2
    assert "Ready to test — 2 notes" in text


def test_solo_verdict_error_blocks():
    rep = _report(
        [{"udp_server": "", "udp_port": "2237", "accept_udp": "false", "issues": []}],
        n1mm={"found": False},
    )
    errs, _w = _counts(rep)
    assert errs >= 1
    text = format_report_solo(rep)
    assert BAD in text.splitlines()[2] and "to fix before testing" in text.splitlines()[2]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
