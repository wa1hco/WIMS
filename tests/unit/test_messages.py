"""Parser tests against real captured WSJT-X datagrams (captures/).

The hex fixtures below are taken verbatim from a live multicast capture
(captures/wsjtx-20260616-221551.jsonl) on a 6 m FT8 instance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as m  # noqa: E402

HEARTBEAT = bytes.fromhex(
    "adbccbda00000002000000000000000657534a542d58"
    "0000000300000005332e302e3000000006616239373662"
)
STATUS = bytes.fromhex(
    "adbccbda00000002000000010000000657534a542d580000000002ffb728"
    "00000003465438000000054b3447444a000000032d31350000000346543800"
    "0001000005dc000003600000000657413148434f00000006464e3432455600"
    "000004454c393800ffffffff0000ffffffffffffffff0000000744656661756c74ffffffff"
)
DECODE = bytes.fromhex(
    "adbccbda00000002000000020000000657534a542d5801007c4868000000143f"
    "c99999a00000000000031b000000017e0000000c4351204e4a314820464e34320000"
)


def test_heartbeat():
    msg = m.parse(HEARTBEAT)
    assert isinstance(msg, m.Heartbeat)
    assert msg.id == "WSJT-X"
    assert msg.version == "3.0.0"
    assert msg.max_schema == 3


def test_status():
    msg = m.parse(STATUS)
    assert isinstance(msg, m.Status)
    assert msg.dial_frequency == 50_313_000  # 50.313 MHz, 6 m
    assert msg.mode == "FT8"
    assert msg.dx_call == "K4GDJ"
    assert msg.report == "-15"
    assert msg.de_call == "WA1HCO"
    assert msg.de_grid == "FN42EV"
    assert msg.dx_grid == "EL98"
    assert msg.rx_df == 1500
    assert msg.tx_df == 864
    assert msg.config_name == "Default"
    assert msg.tx_enabled is False
    assert msg.frequency_tolerance is None  # 0xFFFFFFFF -> N/A


def test_decode_and_grid():
    msg = m.parse(DECODE)
    assert isinstance(msg, m.Decode)
    assert msg.new is True
    assert msg.snr == 20
    assert abs(msg.delta_time - 0.2) < 1e-6
    assert msg.delta_frequency == 795
    assert msg.mode == "~"  # FT8
    assert msg.message == "CQ NJ1H FN42"
    assert msg.is_cq is True
    assert msg.dx_call == "NJ1H"
    assert msg.grid == "FN42"  # the rover/mult-critical field


def test_non_wsjtx_returns_none():
    assert m.parse(b"not a wsjtx datagram") is None


def test_grid_extractor_excludes_signoffs():
    assert m.extract_grid("CQ NJ1H FN42") == "FN42"
    assert m.extract_grid("K1ABC NJ1H FN42") == "FN42"
    assert m.extract_grid("K1ABC NJ1H R-12") is None
    assert m.extract_grid("K1ABC NJ1H RR73") is None
    assert m.extract_grid("K1ABC NJ1H 73") is None
    assert m.extract_grid("CQ DX K1ABC EM48bk") == "EM48BK"


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
