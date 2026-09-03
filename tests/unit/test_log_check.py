# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for log helper scoped config checks + RadioInfo band."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.agent.n1mm_probe import _parse_wsjt_udp_reader_from_ini, probe_wsjt_udp_reader
from wims.log.check import pin_from_hostname, resolve_pin, run_checks
from wims.log.app import adif_band, deliver_to_n1mm, ensure_adif_datetime, wrap_adif
from wims.log.radioinfo import band_from_radioinfo_xml, n1mm_freq_units_to_hz


class PinTests(unittest.TestCase):
    def test_hostname_suffix(self):
        self.assertEqual(pin_from_hostname("wims-test-50"), "6m")
        self.assertEqual(pin_from_hostname("TRAILER-144"), "2m")
        self.assertIsNone(pin_from_hostname("desktop-jeff"))

    def test_resolve_band_arg(self):
        self.assertEqual(resolve_pin("2m", env={}, hostname="x"), "2m")

    def test_resolve_env(self):
        self.assertEqual(
            resolve_pin(None, env={"WIMS_BAND": "70cm"}, hostname="x"),
            "70cm",
        )


class AdifWrapTests(unittest.TestCase):
    def test_band_2m_despite_hf_freq(self):
        adif = "<CALL:4>K1AB<BAND:2>2M<FREQ:8>14.074000<MODE:3>FT8 <eor>"
        self.assertEqual(adif_band(adif), "2m")

    def test_band_from_freq_when_no_band(self):
        adif = "<CALL:4>K1AB<FREQ:8>14.074000<MODE:3>FT8 <eor>"
        self.assertEqual(adif_band(adif), "20m")

    def test_n1mm_log_envelope(self):
        payload = wrap_adif("<CALL:4>K1AB<BAND:2>2m <eor>")
        self.assertTrue(payload.startswith(b"<command:3>Log <parameters:"))
        self.assertIn(b"<CALL:4>K1AB", payload)
        self.assertIn(b"<QSO_DATE:", payload)
        self.assertIn(b"<TIME_ON:", payload)

    def test_ensure_datetime_idempotent(self):
        adif = "<CALL:4>K1AB<QSO_DATE:8>20260829<TIME_ON:6>120000 <eor>"
        self.assertEqual(ensure_adif_datetime(adif), adif)

    def test_deliver_prefers_tcp(self):
        class FakeSock:
            def sendall(self, data):
                self.data = data

            def shutdown(self, *_a):
                pass

            def settimeout(self, *_a):
                pass

            def recv(self, *_a):
                return b""

            def close(self):
                pass

        with mock.patch("socket.create_connection", return_value=FakeSock()) as conn:
            ok, how = deliver_to_n1mm(b"<command:3>Log <parameters:3>x", prefer_tcp=True)
        self.assertTrue(ok)
        self.assertTrue(how.startswith("TCP"))
        conn.assert_called()

    def test_tcp_client_reuses_socket(self):
        from wims.log.app import N1mmTcpClient

        class FakeSock:
            def __init__(self):
                self.n_send = 0
                self.n_close = 0

            def sendall(self, data):
                self.n_send += 1
                self.data = data

            def setsockopt(self, *_a):
                pass

            def settimeout(self, *_a):
                pass

            def shutdown(self, *_a):
                pass

            def recv(self, *_a):
                return b""

            def close(self):
                self.n_close += 1

        sock = FakeSock()
        client = N1mmTcpClient("127.0.0.1", 52001)
        with mock.patch("socket.create_connection", return_value=sock) as conn:
            ok1, how1 = deliver_to_n1mm(b"one", prefer_tcp=True, tcp_client=client)
            ok2, how2 = deliver_to_n1mm(b"two", prefer_tcp=True, tcp_client=client)
        self.assertTrue(ok1 and ok2)
        self.assertTrue(how1.startswith("TCP") and how2.startswith("TCP"))
        self.assertEqual(conn.call_count, 1)
        self.assertEqual(sock.n_send, 2)
        self.assertEqual(sock.n_close, 0)
        client.close()
        self.assertEqual(sock.n_close, 1)
        self.assertFalse(client.alive)


class RadioInfoTests(unittest.TestCase):
    def test_freq_units(self):
        self.assertEqual(n1mm_freq_units_to_hz("5012345"), 50_123_450)
        self.assertEqual(n1mm_freq_units_to_hz("14417400"), 144_174_000)

    def test_parse_radioinfo_6m(self):
        xml = """<?xml version="1.0"?>
        <RadioInfo>
          <RadioNr>1</RadioNr>
          <Freq>5017400</Freq>
          <TXFreq>5017400</TXFreq>
          <Mode>USB</Mode>
          <ActiveRadioNr>1</ActiveRadioNr>
        </RadioInfo>
        """
        band, meta = band_from_radioinfo_xml(xml)
        self.assertEqual(band, "6m")
        self.assertEqual(meta["freq_hz"], 50_174_000)

    def test_ignore_contactinfo(self):
        xml = "<contactinfo><band>50</band><call>K1ABC</call></contactinfo>"
        band, meta = band_from_radioinfo_xml(xml)
        self.assertIsNone(band)
        self.assertEqual(meta, {})


class WsjtUdpReaderIniTests(unittest.TestCase):
    def test_reader_off(self):
        text = "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n"
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertFalse(rows[0]["enabled"])

    def test_reader_on_defaults_2237(self):
        text = (
            "[ExternalProgramInput]\n"
            "EnableWSJTJTDXUDPReader=True\n"
            "WSJTJTDXUDPIP=224.0.0.73\n"
        )
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["port"], 2237)

    def test_reader_on_2333_not_fleet(self):
        text = (
            "[ExternalProgramInput]\n"
            "EnableWSJTJTDXUDPReader=True\n"
            "WSJTJTDXUDPPort=2333\n"
        )
        rows = _parse_wsjt_udp_reader_from_ini(text)
        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["port"], 2333)

    def test_ini_true_without_runtime_is_not_conflict(self):
        """Stale ini Enable=True must not yellow-warn if N1MM is not bound."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\n"
                "EnableWSJTJTDXUDPReader=True\n"
                "WSJTJTDXUDPPort=2237\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertFalse(info["fleet_conflict"])
        self.assertIn("not bound", info["summary"].lower())

    def test_runtime_bind_is_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[{"port": 2237, "pid": 99, "local": "0.0.0.0:2237"}],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertTrue(info["fleet_conflict"])
        self.assertIn("2237", info["summary"])

    def test_probe_off_no_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "N1MM Logger.ini"
            ini.write_text(
                "[ExternalProgramInput]\nEnableWSJTJTDXUDPReader=False\n",
                encoding="utf-8",
            )
            with mock.patch(
                "wims.agent.n1mm_probe._find_ini_files",
                return_value=[ini],
            ):
                with mock.patch(
                    "wims.agent.n1mm_probe.n1mm_user_dirs",
                    return_value=[],
                ):
                    with mock.patch(
                        "wims.agent.n1mm_probe.n1mm_fleet_udp_binds",
                        return_value=[],
                    ):
                        info = probe_wsjt_udp_reader()
        self.assertFalse(info["fleet_conflict"])
        self.assertIn("off", info["summary"].lower())


class RadioSocketTests(unittest.TestCase):
    """RadioInfo listener must hear fleet multicast AND plain unicast."""

    def _free_port(self):
        import socket as s
        tmp = s.socket(s.AF_INET, s.SOCK_DGRAM)
        tmp.bind(("127.0.0.1", 0))
        port = tmp.getsockname()[1]
        tmp.close()
        return port

    def test_unicast_still_heard_with_group_join(self):
        import socket as s
        from wims.log.app import _open_radio_socket
        port = self._free_port()
        sock, where, warn = _open_radio_socket(port, "224.0.0.73", "127.0.0.1")
        try:
            self.assertIn("224.0.0.73", where)
            tx = s.socket(s.AF_INET, s.SOCK_DGRAM)
            tx.sendto(b"<RadioInfo/>", ("127.0.0.1", port))
            tx.close()
            data, _ = sock.recvfrom(65535)
            self.assertEqual(data, b"<RadioInfo/>")
        finally:
            sock.close()

    def test_multicast_heard(self):
        import socket as s
        from wims.log.app import _open_radio_socket
        port = self._free_port()
        sock, where, warn = _open_radio_socket(port, "224.0.0.73", "127.0.0.1")
        try:
            tx = s.socket(s.AF_INET, s.SOCK_DGRAM)
            tx.setsockopt(s.IPPROTO_IP, s.IP_MULTICAST_IF,
                          s.inet_aton("127.0.0.1"))
            tx.setsockopt(s.IPPROTO_IP, s.IP_MULTICAST_LOOP, 1)
            tx.sendto(b"<RadioInfo><Freq>5017400</Freq></RadioInfo>",
                      ("224.0.0.73", port))
            tx.close()
            sock.settimeout(2.0)
            data, _ = sock.recvfrom(65535)
            self.assertIn(b"5017400", data)
        finally:
            sock.close()

    def test_no_group_plain_bind(self):
        from wims.log.app import _open_radio_socket
        port = self._free_port()
        sock, where, warn = _open_radio_socket(port, None)
        try:
            self.assertIsNone(warn)
            self.assertIn(str(port), where)
        finally:
            sock.close()

    def test_bad_group_falls_back_to_unicast(self):
        from wims.log.app import _open_radio_socket
        port = self._free_port()
        # Not a multicast address — the IGMP join fails, bind must survive.
        sock, where, warn = _open_radio_socket(port, "10.9.9.9")
        try:
            self.assertIsNotNone(warn)
            self.assertIn("unicast", warn)
        finally:
            sock.close()


class CheckTests(unittest.TestCase):
    def test_waiting_for_band_is_warn(self):
        rep = run_checks(live_band=None, joined=None, tcp_probe=lambda h, p: False)
        self.assertEqual(rep.severity, "warn")
        self.assertTrue(any(i.id == "band" and i.severity == "warn" for i in rep.items))
        self.assertTrue(any("Waiting for N1MM" in i.message for i in rep.items))

    def test_waiting_message_names_multicast_group(self):
        rep = run_checks(
            live_band=None, radio_group="224.0.0.73", joined=None,
            tcp_probe=lambda h, p: False,
        )
        band = next(i for i in rep.items if i.id == "band")
        self.assertIn("224.0.0.73:12060", band.message)

    def test_waiting_message_unicast_when_no_group(self):
        rep = run_checks(
            live_band=None, radio_group=None, joined=None,
            tcp_probe=lambda h, p: False,
        )
        band = next(i for i in rep.items if i.id == "band")
        self.assertNotIn("224.0.0.73:12060", band.message)
        self.assertIn("12060", band.message)

    def test_joined_and_tcp_ok(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            with mock.patch("wims.log.check._wsjt_udp_reader_conflict") as c:
                from wims.log.check import CheckItem
                n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
                c.return_value = CheckItem("conflict", "ok", "reader off")
                rep = run_checks(
                    live_band="6m", joined=True, dry_run=False,
                    tcp_probe=lambda h, p: True,
                )
        self.assertEqual(rep.severity, "ok")
        self.assertTrue(any(i.id == "mcast" and i.severity == "ok" for i in rep.items))
        self.assertTrue(any(i.id == "delivery" and i.severity == "ok" for i in rep.items))
        text = "\n".join(rep.lines())
        text.encode("cp1252")

    def test_conflict_warn_only_when_detected(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            with mock.patch("wims.log.check._wsjt_udp_reader_conflict") as c:
                from wims.log.check import CheckItem
                n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
                c.return_value = CheckItem(
                    "conflict", "ok", "N1MM WSJT/JTDX UDP reader is off (Logger.ini).",
                )
                rep = run_checks(
                    live_band="6m", joined=True, dry_run=True,
                    tcp_probe=lambda h, p: True,
                )
        conflict = next(i for i in rep.items if i.id == "conflict")
        self.assertEqual(conflict.severity, "ok")

    def test_expect_mismatch_warns(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            from wims.log.check import CheckItem
            n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
            rep = run_checks(
                live_band="2m", expect_band="6m", joined=True,
                tcp_probe=lambda h, p: True,
            )
        self.assertTrue(any(i.id == "expect" and i.severity == "warn" for i in rep.items))

    def test_tcp_missing_warns(self):
        with mock.patch("wims.log.check._n1mm_presence") as n1:
            from wims.log.check import CheckItem
            n1.return_value = CheckItem("n1mm", "ok", "N1MM ok")
            rep = run_checks(
                live_band="6m", joined=True,
                tcp_probe=lambda h, p: False,
            )
        delivery = next(i for i in rep.items if i.id == "delivery")
        self.assertEqual(delivery.severity, "warn")
        self.assertIn("52001", delivery.message)


if __name__ == "__main__":
    unittest.main()
