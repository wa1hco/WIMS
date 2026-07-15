"""POST agent report to the site WIMS server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def export_report(report: dict, server_url: str, *, timeout: float = 8.0) -> dict:
    """POST report to ``{server_url}/api/agents/report``.

    ``server_url`` may be ``http://192.168.1.119:8787`` or include a trailing slash.
    Returns a small result dict: ok, status, body/error.
    """
    base = (server_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "no server_url"}
    url = base + "/api/agents/report"
    data = json.dumps(report).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "wims-agent/0.0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw}
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body, "url": url}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        return {"ok": False, "status": e.code, "error": raw or str(e), "url": url}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": str(e), "url": url}
