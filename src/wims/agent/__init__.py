"""WIMS host agent — local seat config/network checks + optional export to site server.

Local-first: the station operator can verify WSJT-X / N1MM settings on this PC
without a site server. Default CLI is **one-shot** (print and exit). Continuous
dashboard reporting uses ``--daemon`` / Start-WimsAgent-Continuous.cmd.

Not the site server. Not a TX controller. Fast mute / leases come later.
"""

from wims.agent.report import build_report

__all__ = ["build_report"]
