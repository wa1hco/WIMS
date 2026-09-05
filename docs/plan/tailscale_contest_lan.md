# Tailscale vs contest LAN (N1MM / WSJT-X) — deferred

**Status:** noted for later (2026-09-04). Not implemented yet.  
**Context:** Multi-homed Windows seats (contest `192.168.1.0/24` + Tailscale `100.x`) can send
N1MM Broadcast Data / mesh and WSJT multicast out the wrong NIC. N1MM has no “outgoing
interface” picker; WSJT-X does.

## Goals

- Allow Tailscale on the W2SZ network for **remote ops** (RDP, WIMS HTTP) without silent
  snatching of contest UDP.
- Scale to volunteer PCs — no per-N1MM typing of the WIMS server LAN IP.
- WIMS **audits** and surfaces Tailscale footguns on Setup / agent UI.

## Direction (agreed in discussion)

1. **N1MM → WIMS path:** Broadcast Data = **`127.0.0.1:12060` only** (fleet-identical).
   **N1MM agent** Broadcast section hears locally and reports presence to the site server.
   Do **not** depend on LAN multicast 12060 or on **12070** for WIMS.
2. **N1MM ↔ N1MM (12070):** leave to N1MM; keep on contest LAN via host/Tailscale policy
   (WIMS does not bridge 12070).
3. **Tailscale seat policy (scales via gold image / Install-Wims.ps1):**
   - No **accept-routes** overlapping the contest LAN on radio/logger seats.
   - No **exit node** on those seats.
   - Raise Tailscale **interface metric** above the contest NIC (e.g. 5000).
   - Contest NIC = Windows **Private** profile (helps TCP 12070 firewall).
4. **WSJT-X:** Outgoing interface = contest LAN (existing check).
5. **WIMS audit (TODO):** Tailscale present; metric vs LAN; contest subnet routed via
   `100.x`; exit node; WSJT iface wrong; N1MM Broadcast dest contains `100.`; hearing
   12070 peers but no local 12060 RadioInfo.

## Non-goals

- Per-app Tailscale “exclude N1MM/WSJT” (not available cleanly).
- Making WIMS a participant in N1MM multi-computer networking on 12070.

## Related

- N1MM agent sections: **Broadcast** · **Log** · **KEY** (`wims.seat`).
- Live-band / RadioInfo: [../decisions/2026-08-29-n1mm-live-band.md](../decisions/2026-08-29-n1mm-live-band.md)
- Networking plane B: [wims_networking.md](wims_networking.md) § plane B / Broadcast Data
