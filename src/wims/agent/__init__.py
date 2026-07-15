"""WIMS host agent — local seat config/network checks + optional export to site server.

Local-first: the station operator can verify WSJT-X / N1MM settings on this PC
without a site server. When a server URL is configured, the same report is POSTed
to the wrangler dashboard (design sec 3.3 / 3.15 / networking sec 12).

Not the site server. Not a TX controller. Fast mute / leases come later.
"""

from wims.agent.report import build_report

__all__ = ["build_report"]
