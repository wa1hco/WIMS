# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wims.console.kiosk import (  # noqa: E402
    firefox_kiosk_profile_dir,
    is_snap_firefox,
)


class SnapFirefoxTests(unittest.TestCase):
    def test_detects_snap_paths(self):
        self.assertTrue(is_snap_firefox("/snap/bin/firefox"))
        self.assertTrue(is_snap_firefox(
            "/snap/firefox/8995/usr/lib/firefox/firefox",
        ))
        self.assertFalse(is_snap_firefox(
            "/usr/lib/firefox/firefox",
        ))
        self.assertFalse(is_snap_firefox(
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
        ))
        self.assertFalse(is_snap_firefox(None))

    def test_detects_ubuntu_snap_wrapper_script(self):
        with tempfile.TemporaryDirectory() as td:
            wrapper = Path(td) / "firefox"
            wrapper.write_text(
                "#!/bin/sh\n"
                "if ! [ -x /snap/bin/firefox ]; then\n"
                "    echo missing\n"
                "    exit 1\n"
                "fi\n"
                "exec /snap/bin/firefox \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            self.assertTrue(is_snap_firefox(str(wrapper)))
            other = Path(td) / "plain"
            other.write_text("#!/bin/sh\nexec /usr/lib/firefox/firefox \"$@\"\n", encoding="utf-8")
            other.chmod(0o755)
            self.assertFalse(is_snap_firefox(str(other)))

    def test_snap_profile_is_not_a_hidden_home_folder(self):
        home = Path("/home/jeff")
        got = firefox_kiosk_profile_dir("/snap/bin/firefox", home=home)
        self.assertEqual(
            got,
            home / "snap" / "firefox" / "common" / "ws-hub-console-profile",
        )
        self.assertNotIn(".local", got.parts)
        # A regular Firefox still uses the XDG data folder.
        regular = firefox_kiosk_profile_dir("/usr/lib/firefox/firefox", home=home)
        self.assertEqual(
            regular,
            home / ".local" / "share" / "wims" / "kiosk-profile",
        )



if __name__ == "__main__":
    unittest.main()
