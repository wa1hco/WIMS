# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Forward N1MM Broadcast Data (localhost :12060) to the site server.

Fleet policy: every N1MM PC aims Broadcast Data at ``127.0.0.1:12060``.
The N1MM agent hears it locally and POSTs XML to the site server so Status
does not depend on LAN/Tailscale multicast for plane B.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

# Don't spam the server with RadioInfo (often 1–2 Hz). Contacts always go.
_RADIOINFO_MIN_INTERVAL_S = 2.0


def looks_like_n1mm_broadcast_xml(text: str) -> bool:
    t = (text or "").lstrip()
    if not t.startswith("<") and "<?xml" not in t[:80].lower():
        return False
    low = t.lower()
    return any(
        tag in low
        for tag in (
            "<radioinfo",
            "<contactinfo",
            "<contactreplace",
            "<contactdelete",
            "<appinfo",
            "<spot",
            "<lookupinfo",
        )
    )


def is_radioinfo(text: str) -> bool:
    return "<radioinfo" in (text or "").lower()


def is_contact_xml(text: str) -> bool:
    low = (text or "").lower()
    return any(
        t in low
        for t in ("<contactinfo", "<contactreplace", "<contactdelete")
    )


class BroadcastForwarder:
    """Rate-limited POST of Broadcast Data XML to ``{site}/api/n1mm/broadcast``."""

    def __init__(
        self,
        *,
        site_url: str | None,
        agent_id: str,
        lan_ip: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self.site_url = (site_url or "").strip().rstrip("/") or None
        self.agent_id = agent_id
        self.lan_ip = lan_ip or ""
        self.timeout = timeout
        self.n_fwd = 0
        self.n_skip = 0
        self.n_err = 0
        self.last_error: str | None = None
        self.last_ok_at: float | None = None
        self._last_radioinfo_fwd = 0.0

    def maybe_forward(self, xml_text: str, *, now: float | None = None) -> str:
        """Forward if appropriate. Returns status token: sent|skip|err|nosite."""
        now = time.time() if now is None else now
        if not self.site_url:
            self.n_skip += 1
            return "nosite"
        if not looks_like_n1mm_broadcast_xml(xml_text):
            self.n_skip += 1
            return "skip"
        if is_radioinfo(xml_text):
            if now - self._last_radioinfo_fwd < _RADIOINFO_MIN_INTERVAL_S:
                self.n_skip += 1
                return "skip"
        # Contacts always; RadioInfo after interval.
        return self._post(xml_text, now=now)

    def _post(self, xml_text: str, *, now: float) -> str:
        assert self.site_url
        url = self.site_url + "/api/n1mm/broadcast"
        body = {
            "agent_id": self.agent_id,
            "lan_ip": self.lan_ip,
            "ts": now,
            "xml": xml_text,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "wims-n1mm-agent/0.0.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    self.n_fwd += 1
                    self.last_ok_at = now
                    self.last_error = None
                    if is_radioinfo(xml_text):
                        self._last_radioinfo_fwd = now
                    return "sent"
                self.n_err += 1
                self.last_error = f"HTTP {resp.status}"
                return "err"
        except urllib.error.HTTPError as e:
            self.n_err += 1
            self.last_error = f"HTTP {e.code}"
            return "err"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.n_err += 1
            self.last_error = str(e)
            return "err"

    def snapshot(self) -> dict:
        return {
            "site_url": self.site_url,
            "agent_id": self.agent_id,
            "lan_ip": self.lan_ip,
            "n_fwd": self.n_fwd,
            "n_skip": self.n_skip,
            "n_err": self.n_err,
            "last_error": self.last_error,
            "last_ok_at": self.last_ok_at,
        }


def default_agent_id() -> str:
    host = socket.gethostname().split(".")[0] or "n1mm"
    return f"{host}-n1mm"


def default_lan_ip() -> str:
    try:
        from wims.discovery.presence import _primary_lan_ip
        return _primary_lan_ip("0.0.0.0") or ""
    except Exception:
        return ""
