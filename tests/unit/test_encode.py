"""Round-trip tests: encode.build_x -> messages.parse -> same values."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp import encode as E  # noqa: E402


def test_heartbeat_roundtrip():
    m = M.parse(E.build_heartbeat("SIM-6M-1", max_schema=3, version="2.7.0"))
    assert isinstance(m, M.Heartbeat)
    assert m.id == "SIM-6M-1" and m.version == "2.7.0" and m.max_schema == 3


def test_status_roundtrip():
    raw = E.build_status("SIM-6M-1", 50_313_000, mode="FT8", de_call="WA1HCO",
                         de_grid="FN42", dx_call="K1ABC", dx_grid="FN31",
                         transmitting=True, rx_df=1200, tx_df=1500, config_name="SIM")
    m = M.parse(raw)
    assert isinstance(m, M.Status)
    assert m.dial_frequency == 50_313_000
    assert m.mode == "FT8" and m.de_call == "WA1HCO" and m.dx_call == "K1ABC"
    assert m.transmitting is True and m.rx_df == 1200 and m.tx_df == 1500
    assert m.config_name == "SIM"
    assert m.frequency_tolerance is None and m.tr_period is None  # defaulted to N/A


def test_decode_roundtrip_with_grid():
    raw = E.build_decode("SIM-6M-1", time_ms=8_145_000, snr=-7, delta_time=0.2,
                         delta_frequency=1500, message="CQ NJ1H FN42")
    m = M.parse(raw)
    assert isinstance(m, M.Decode)
    assert m.snr == -7 and abs(m.delta_time - 0.2) < 1e-9 and m.delta_frequency == 1500
    assert m.message == "CQ NJ1H FN42"
    assert m.is_cq is True and m.dx_call == "NJ1H" and m.grid == "FN42"


def test_halt_and_reply_parse_as_known_types():
    halt = M.parse(E.build_halt_tx("SIM-6M-1", auto_only=False))
    assert halt.type == M.HALT_TX and halt.id == "SIM-6M-1"
    reply = M.parse(E.build_reply("SIM-6M-1", time_ms=8_145_000, snr=-7, delta_time=0.2,
                                  delta_frequency=1500, message="CQ NJ1H FN42"))
    assert reply.type == M.REPLY and reply.id == "SIM-6M-1"


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
