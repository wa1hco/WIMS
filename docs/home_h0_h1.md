# Home testing: H0 Operate + H1 Inhibit

**Audience:** one PC at home (one TRX, often dual RX or TRX+SDR).  
**Goal:** try WIMS **chunks** without a contest LAN or CAT handoff.  
**Radio control:** unchanged (manual / N1MM / WSJT as you already run). See  
[`decisions/2026-09-17-shared-trx-radio-ownership.md`](decisions/2026-09-17-shared-trx-radio-ownership.md)  
and stages H2–H4 in [`plan/wims_home_dual_rx_slice.md`](plan/wims_home_dual_rx_slice.md).

## Absolute minimum (most home digi ops)

**One radio. One WSJT-X. Operate page.**

You want WIMS to **filter and rank decodes** and **click-to-Work** (Reply) — not a fleet, not KEY, not dual RX.

| Have | Do |
|------|-----|
| WSJT-X on air (Reporting → `224.0.0.73:2237`, **Accept UDP ON**) | `Start-Wims-Solo.cmd` / `python -m wims.solo` |
| Browser | `http://localhost:8787/` → **Operate** |
| Optional N1MM log | Auto-seed needed vs dupe; or `--no-seed` (all look needed) |

Operate: filters (**needed only**, max age, band) + **click a row = Work**. **Halt TX** stops that Work. Call CQ stays in WSJT-X.

Nothing else is required for this minimum.

| Stage | What you run | Site server? |
|-------|----------------|--------------|
| **H0 min** | **Operate**: filter + Work | No |
| **H0 + log** | Same + N1MM `.s3db` seed | No |
| **H1** | Standalone **Inhibit** (KEY → digi hold) | No |
| H2+ | Dual-RX layout, mute, CAT | Later |

---

## H0 — Operate only

Operate is one console. It has **two UDP modes**.

### Operate modes

| Mode | When | WIMS bind | WSJT-X Reporting |
|------|------|-----------|------------------|
| **Local** | Operate on the **same PC** as WSJT-X | Loopback (`--iface 127.0.0.1`) | Multicast `224.0.0.73:2237` on this PC, **or** unicast to `127.0.0.1` (then add WIMS `--tx-host 127.0.0.1`) |
| **Network** | Operate (or site server) on a PC that must hear **LAN** digi | Contest LAN NIC (`--iface` = that IPv4) | Multicast `224.0.0.73:2237`, **Outgoing interface = contest LAN NIC** |

Both modes need **Accept UDP requests ON** for Work (Reply).  
Same Operate page either way: roster → click Work → Halt TX.

**Local** = home H0 / `wims.solo` default.  
**Network** = fleet site server, or solo started with a LAN `--iface` (and WSJT Outgoing interface set to that LAN).

Do not mix them by accident: Local bind will **not** see VM/LAN WSJT traffic.

### What you need

- WSJT-X with UDP Reporting (Work needs **Accept UDP requests ON**)
- Optional: N1MM `.s3db` so needed/dupe scoring works (`--no-seed` if none)
- WIMS install (`Install-Wims.cmd` on Windows)

### WSJT-X Reporting (Local default)

- UDP Server: `224.0.0.73`
- Port: `2237`
- **Accept UDP requests:** ON  
- Unique `--rig-name` if more than one instance  
- Same-PC multicast is enough; no LAN NIC required for Local

### Start Operate (Local)

| OS | Action |
|----|--------|
| Windows | `scripts\windows\Start-Wims-Solo.cmd` |
| Linux | `scripts/start-wims-solo.sh` |
| CLI | `python -m wims.solo` |
| Launcher | **Other tools… → Start Operate (home)** |

Browser: `http://localhost:8787/` — **Operate** tab (roster). Click a line to Work; **Halt TX** to stop.

Setup check only: `Check-WimsSetup.cmd` / `python -m wims.agent --solo`.

### Start Operate (Network)

| OS | Action |
|----|--------|
| Windows | Site server / `Start-WimsServer.cmd` (LAN iface) |
| Linux | `python -m wims.server --iface <lan-ipv4>` |
| CLI solo on LAN | `python -m wims.solo --iface <lan-ipv4>` |

WSJT-X on each seat: Outgoing interface = contest LAN NIC.  
Full fleet notes: [`operator_setup.md`](operator_setup.md).

### Not required for H0 Local

- Fleet site server on another PC  
- KEY / inhibit  
- CAT / mute / shared-trx handoff  
- Contest LAN multicast from other hosts  

---

## H1 — Inhibit only

Footswitch (or KEY sense) holds **local** digi TX. No Operate required. No site server required.

### What you need

- **Patched WSJT-X** with TxInhibit (type 18), prefer port **22372**
- Keyline (or serial CTS) KEY sense — or lab `sim:up` / `sim:down`
- WIMS on the same PC as the digi instance you will hold

### Start Inhibit (home recipe)

Uses **explicit localhost target** so you do **not** need N1MM RadioInfo / live band.

| OS | Action |
|----|--------|
| Windows | `scripts\windows\Start-Wims-Inhibit-Home.cmd` |
| Linux | `scripts/start-wims-inhibit-home.sh` |
| CLI | see below |

```text
# Device: COM port, /dev/tty…, or sim:up for a lab stick-down
set WIMS_KEY_DEVICE=COM3          # Windows example
export WIMS_KEY_DEVICE=/dev/ttyUSB0

python -m wims.seat --key --targets 127.0.0.1:22372
```

Optional GUI seat window: omit `--no-gui` (scripts keep the small seat UI by default).

### Check

1. KEY idle → digi can TX (Enable Tx as usual).  
2. KEY down → digi PTT gated (inhibit).  
3. KEY up → after hang, digi can TX again.

### Sister tool

[`inhibit-agent`](plan/inhibit_agent.md) in **wsjtx-inhibit** is the same idea (CTS → localhost gate).  
For WIMS home docs, prefer **`Start-Wims-Inhibit-Home`** so one install covers H0+H1.

### Not required for H1

- Operate / Solo  
- N1MM Broadcast (targets are overridden)  
- CAT / mute  

---

## H0 + H1 together

Typical home desk:

1. Start WSJT-X (Reporting as above).  
2. `Start-Wims-Solo` → Operate.  
3. `Start-Wims-Inhibit-Home` → KEY holds digi while you work SSB/CW on the same TRX (mode still yours until H3/H4).

---

## Dual RX note (still H0/H1)

You may run a second WSJT-X on SUB or SDR for decode only.  
H0 shows both if they share plane A.  
H1 should target the **TX-capable** gate (`127.0.0.1:22372` for that instance).  
Marking TX-capable vs decode-only in config is **H2**.

---

## If something fails

| Symptom | Check |
|---------|--------|
| Empty roster | UDP `224.0.0.73:2237`; Solo running; firewall |
| Work does nothing | Accept UDP ON; correct instance |
| KEY never holds | Patched gate; port 22372; `--targets`; KEY device / CTS |
| Want fleet multi-PC KEY | Use launcher **SSB/CW KEY** + discovery — not this home override |

Full fleet setup: [`operator_setup.md`](operator_setup.md).  
Windows script index: [`scripts/windows/README.md`](../scripts/windows/README.md).
