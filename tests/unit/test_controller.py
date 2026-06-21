"""TxController send path — builds valid Reply/Halt addressed to an instance."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.udp import messages as M  # noqa: E402
from wims.udp import encode as E  # noqa: E402
from wims.udp.controller import TxController  # noqa: E402


class _FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, dest):
        self.sent.append((data, dest))


def test_reply_mirrors_decode_and_addresses_instance():
    d = M.parse(E.build_decode("SIM-6M", time_ms=8_145_000, snr=-7, delta_time=0.2,
                               delta_frequency=1500, message="CQ K1ABC FN42"))
    fs = _FakeSock()
    c = TxController(fs, ("224.0.0.73", 2237))
    raw = c.reply("SIM-6M", d)
    assert fs.sent[0][1] == ("224.0.0.73", 2237)
    r = M.parse(raw)
    assert r.type == M.REPLY and r.id == "SIM-6M"     # addressed to the right instance


def test_halt_sends_halt_tx():
    fs = _FakeSock()
    c = TxController(fs, ("224.0.0.73", 2237))
    c.halt("SIM-6M")
    assert M.parse(fs.sent[0][0]).type == M.HALT_TX


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
