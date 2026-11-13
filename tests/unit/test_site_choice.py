# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.launcher.site_choice import (  # noqa: E402
    LOCAL_SITE,
    adopt_discovered_server_url,
    same_site_host,
    should_host_local_site_server,
    site_url_is_this_pc,
)


class DefaultSiteTests(unittest.TestCase):
    def test_builtin_default_is_localhost_not_a_lan_address(self):
        self.assertEqual(LOCAL_SITE, "http://127.0.0.1:8787")
        self.assertNotIn("192.168.1.119", LOCAL_SITE)


class ShouldHostTests(unittest.TestCase):
    def test_waits_until_discovery_finishes(self):
        self.assertFalse(should_host_local_site_server(
            discovery_done=False, site_reachable=False,
        ))

    def test_does_not_start_a_second_server(self):
        self.assertFalse(should_host_local_site_server(
            discovery_done=True, site_reachable=True,
        ))

    def test_fresh_install_hosts_when_none_found(self):
        self.assertTrue(should_host_local_site_server(
            discovery_done=True, site_reachable=False,
            last_site_url=None, env_server=None,
        ))

    def test_loopback_last_site_hosts_again_when_down(self):
        self.assertTrue(should_host_local_site_server(
            discovery_done=True, site_reachable=False,
            last_site_url="http://127.0.0.1:8787",
        ))

    def test_this_pc_lan_last_site_hosts_again_when_down(self):
        self.assertTrue(should_host_local_site_server(
            discovery_done=True, site_reachable=False,
            last_site_url="http://192.168.2.165:8787",
            lan_ips=["192.168.2.165"],
        ))

    def test_fleet_seat_does_not_host_when_remembered_remote_is_down(self):
        self.assertFalse(should_host_local_site_server(
            discovery_done=True, site_reachable=False,
            last_site_url="http://192.168.1.50:8787",
            lan_ips=["192.168.2.165"],
        ))

    def test_env_pin_to_a_remote_host_does_not_auto_host(self):
        self.assertFalse(should_host_local_site_server(
            discovery_done=True, site_reachable=False,
            last_site_url=None,
            env_server="http://192.168.1.50:8787",
            lan_ips=["192.168.2.165"],
        ))


class SameSiteTests(unittest.TestCase):
    def test_loopback_matches_this_pc_lan(self):
        self.assertTrue(same_site_host(
            "http://127.0.0.1:8787",
            "http://192.168.2.165:8787",
            lan_ips=["192.168.2.165"],
        ))
        self.assertFalse(same_site_host(
            "http://127.0.0.1:8787",
            "http://192.168.1.50:8787",
            lan_ips=["192.168.2.165"],
        ))

    def test_site_url_is_this_pc(self):
        self.assertTrue(site_url_is_this_pc("http://127.0.0.1:8787"))
        self.assertTrue(site_url_is_this_pc(
            "http://192.168.2.165:8787", lan_ips=["192.168.2.165"],
        ))
        self.assertFalse(site_url_is_this_pc(
            "http://192.168.1.50:8787", lan_ips=["192.168.2.165"],
        ))


class AdoptServerTests(unittest.TestCase):
    def test_empty_current_takes_discovered(self):
        self.assertEqual(
            adopt_discovered_server_url(None, "http://127.0.0.1:8787"),
            "http://127.0.0.1:8787",
        )

    def test_keeps_working_configured_url(self):
        self.assertEqual(
            adopt_discovered_server_url(
                "http://10.0.0.5:8787",
                "http://127.0.0.1:8787",
                configured="http://10.0.0.5:8787",
                current_reachable=True,
            ),
            "http://10.0.0.5:8787",
        )

    def test_repoints_when_configured_url_is_down(self):
        self.assertEqual(
            adopt_discovered_server_url(
                "http://10.0.0.5:8787",
                "http://127.0.0.1:8787",
                configured="http://10.0.0.5:8787",
                current_reachable=False,
            ),
            "http://127.0.0.1:8787",
        )


if __name__ == "__main__":
    unittest.main()
