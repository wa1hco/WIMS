# Seat agents → server Status / Setup display

Handoff for the **site server** (e.g. Linux at `192.168.1.119`). Windows seat VMs run the **agent**; this host runs **only** the site server and shows aggregated reports.

**Discovery (plane E):** the site server multicasts a JSON presence beacon on
`224.0.0.73:8788` ~1 Hz. Agents listen and show **clickable** Operate / Status / Setup links on
`http://127.0.0.1:8790/` so operators need not remember the server IP. A second `wims.server`
process hears the beacon and **refuses to start** (see [wims_networking.md](wims_networking.md) §3.1).

## On the Linux server (do this first)

```bash
cd /path/to/WIMS   # your checkout
git pull
# restart however you normally run the server, e.g.:
#   python -m wims.server.app --iface <LAN-IP> --n1mm-group 224.0.0.73 --http-port 8787
# Use the real contest LAN address for --iface (not 127.0.0.1) so multi-host UDP works.
```

Confirm the new API exists:

```bash
curl -s http://127.0.0.1:8787/healthz
curl -s http://127.0.0.1:8787/api/agents
# → {"agents":[...]}  (empty list is OK until seats report)
# 404 means old code still running — pull/restart again
```

Browser (from any machine that can reach the server):

| Page | What to look for |
|------|------------------|
| `http://<server>:8787/status` | **Seat agents (config / host audit)** table — severity, age, message |
| `http://<server>:8787/setup` | **Host app configs — from seat agents** detail (WSJT-X UDP fields, N1MM probe) |

SSE state key: **`agents`** (same `/events` feed as the rest of the console).

## API contract (implemented on site server)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/agents/report` | Seat posts full JSON report |
| `GET` | `/api/agents` | List last report per `agent_id` (with age/health) |
| SSE | `/events` → `agents` | Same rows pushed to Status/Setup UI |

Ingest stores last report per `agent_id` (5‑minute prune). Status renders the summary table;
Setup renders the nested WSJT-X.ini + N1MM probe detail. **Note:** Setup must not require
the Status-only `#agents-body` element (fixed 2026-07-15).

Example one-shot push from a seat (or from the server for a smoke test):

```bash
# From a seat with the repo:
#   python -m wims.agent --server http://192.168.1.119:8787 --seat-id TEMPLATE-01
#
# Or POST a minimal body:
curl -s -X POST http://127.0.0.1:8787/api/agents/report \
  -H "Content-Type: application/json" \
  -d '{"schema":1,"agent_id":"smoke-test","seat_id":"DEV","ts":1,"summary":{"severity":"ok","message":"smoke"},"host":{"hostname":"dev","lan_ips":[]},"wsjtx":{"configs":[],"error_count":0,"warn_count":0},"n1mm":{"found":false},"apps":{}}'
curl -s http://127.0.0.1:8787/api/agents
```

Agents silent for **>5 minutes** are pruned from the server store.

## What a seat should be doing (Windows template)

| Script | Role |
|--------|------|
| `scripts/windows/WIMS.cmd` | Seat menu (check / agent / seat pack / open pages / Desktop shortcut) |
| `scripts/windows/Start-WimsSeat.cmd` | Start N1MM/WSJT-X if missing; restart agent only (`START_AGENT_RESTART=1`) |
| `Install-WimsSeatStartup.cmd` | Auto-run seat pack at logon (auto-login VMs) |
| `Start-WimsAgent.cmd` | One-shot local check only |
| `Start-WimsAgent-Continuous.cmd` | Daemon only (`--daemon`) |

Config: `scripts/windows/seat-local.cmd` (gitignored) — `WIMS_SERVER=http://192.168.1.119:8787`, `WIMS_SEAT_ID=…`, `START_AGENT_RESTART=1`.

- Local operator UI on the seat: `http://127.0.0.1:8790/`
- Continuous agent POSTs to: `http://<server>:8787/api/agents/report`

## Status table columns (expected UX)

- **Agent / seat** — `seat_id` and `agent_id`
- **Host** — hostname + LAN IPs
- **Health** — ALIVE / STALE / DEAD from report age
- **Severity** — ok / warn / error from last config audit
- **Age** — seconds since last POST
- **WSJT err** — count of config errors
- **Message** — plain-language first fault (e.g. iface, loopback UDP, N1MM broadcast)

Setup page expands the nested report (per WSJT-X.ini UDP Server / Outgoing interface, N1MM Databases / N2OY.s3db, process running flags).

## Not in this slice (later)

Full agent capability matrix (design **[wims_design.md §3.3.1](wims_design.md)**):

- **10 ms interlock** — SSB/CW CTS sensor + WSJT-X host fast mute (peer-to-peer, not via server)
- **Rotator** — K3NG/Yaesu status + control (Az ant); serial owned on the seat
- Thumbnails, process lifecycle, local readiness 🟢/🔴, watchdog fail-safe
- Contest profile expected-vs-actual board
- Multi-port WSJT-X join 2238–2240 (still single `--port` on server unless extended)

**This slice only:** setup/config test + report + discovery + local UI.

## Code map

| Area | Path |
|------|------|
| Agent | `src/wims/agent/` |
| Ingest + prune | `src/wims/server/app.py` (`accept_agent_report`, snapshot `agents`) |
| JSON shape | `src/wims/server/state.py` (`agents_to_dict`) |
| UI | `static/status.html`, `static/setup.html`, `static/wims.js` (`renderAgents`) |
| Tests | `tests/unit/test_agent_report.py` |
