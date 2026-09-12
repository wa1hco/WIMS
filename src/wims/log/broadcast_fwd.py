# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Forward N1MM Broadcast Data (localhost :12060) to the site server.

Fleet policy: every N1MM PC aims Broadcast Data at ``127.0.0.1:12060``.
The N1MM agent hears it locally and POSTs XML to the site server so Status
does not depend on LAN multicast for plane B.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request

from wims import __version__ as _WIMS_VERSION

# Don't spam the server with RadioInfo (often 1–2 Hz). Contacts always go.
_RADIOINFO_MIN_INTERVAL_S = 2.0
_CONTACT_RETRIES = 4
_QUEUE_MAX = 256


def format_fwd_error(exc: BaseException | str) -> str:
    """Short operator-facing reason (not a raw WinError dump)."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    s = str(exc)
    low = s.lower()
    if "10061" in s or "refused" in low:
        return "connection refused"
    if "10060" in s or "timed out" in low or "timeout" in low:
        return "timed out"
    if "11001" in s or "getaddrinfo" in low or "name or service not known" in low:
        return "host not found"
    return s[:120]


def discover_site_console(*, duration_s: float = 0.8) -> str | None:
    """UDP presence → site console_base, or None. Fast; no subnet HTTP scan."""
    try:
        from wims.discovery.presence import discover_site_server
        beacon = discover_site_server(duration_s=duration_s, http_fallback=False)
    except Exception:
        return None
    if not beacon:
        return None
    return (beacon.get("console_base") or "").rstrip("/") or None


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
        timeout: float = 1.0,
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
        self._last_radioinfo_try = 0.0
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._worker: threading.Thread | None = None
        if self.site_url:
            t = threading.Thread(
                target=self._run, name="n1mm-bcast-fwd", daemon=True,
            )
            t.start()
            self._worker = t

    def submit(self, xml_text: str, *, now: float | None = None) -> str:
        """Non-blocking enqueue for the RadioInfo UDP thread.

        HTTP POST used to run inline; a 1s timeout blocked N1MM Broadcast
        recv and dropped contactinfo (QSOs never reached the site).
        """
        now = time.time() if now is None else now
        if not self.site_url:
            self.n_skip += 1
            return "nosite"
        if not looks_like_n1mm_broadcast_xml(xml_text):
            self.n_skip += 1
            return "skip"
        if is_radioinfo(xml_text):
            if now - self._last_radioinfo_try < _RADIOINFO_MIN_INTERVAL_S:
                self.n_skip += 1
                return "skip"
            self._last_radioinfo_try = now
        contact = is_contact_xml(xml_text)
        try:
            self._q.put_nowait((xml_text, contact, 0))
            return "queued"
        except queue.Full:
            self.n_err += 1
            self.last_error = "queue full"
            return "err"

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            xml_text, contact, tries = item
            st = self._post(xml_text, now=time.time())
            if st == "err" and contact and tries < _CONTACT_RETRIES:
                time.sleep(min(1.0, 0.15 * (tries + 1)))
                try:
                    self._q.put_nowait((xml_text, True, tries + 1))
                except queue.Full:
                    pass

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
            if now - self._last_radioinfo_try < _RADIOINFO_MIN_INTERVAL_S:
                self.n_skip += 1
                return "skip"
            self._last_radioinfo_try = now
        # Contacts always; RadioInfo after interval (including failed attempts).
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
                "User-Agent": f"wims-n1mm-agent/{_WIMS_VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    self.n_fwd += 1
                    self.last_ok_at = now
                    self.last_error = None
                    return "sent"
                self.n_err += 1
                self.last_error = f"HTTP {resp.status}"
                return "err"
        except urllib.error.HTTPError as e:
            self.n_err += 1
            self.last_error = format_fwd_error(e)
            return "err"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.n_err += 1
            self.last_error = format_fwd_error(e)
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
