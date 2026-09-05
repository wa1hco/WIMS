# Operator setup — WSJT-X, N1MM, Keyline

**Audience:** contest seat operators and the person wiring the fleet.  
**Goal:** one place that says **exactly** what to set so WIMS can see digi, log, and KEY.

Related: [User-manual.md](User-manual.md) · [plan/wims_networking.md](plan/wims_networking.md) ·  
[decisions/2026-08-29-n1mm-live-band.md](decisions/2026-08-29-n1mm-live-band.md) ·  
[hardware/keyline_interface/eeprom/README.md](../hardware/keyline_interface/eeprom/README.md)

---

## Which PC runs what

| PC role | Apps | WIMS |
|---------|------|------|
| **Site server** (one per LAN) | Optional N1MM for log seed | Desktop **WIMS** → **Site server** · console `http://<server>:8787/` |
| **N1MM / SSB-CW logger** | N1MM (+ optional KEY hardware) | Desktop **WIMS** → check **N1MM** (+ **SSB/CW KEY**) → **N1MM agent** |
| **WSJT-X digi** | One or more WSJT-X | Multicast settings below; optional **WSJT-X** intent → monitor agent `:8790` |
| **Operator laptop** | Browser only | `http://<server>:8787/` |

Console top nav: **Operate · Overview · WSJT-X · N1MM · Setup** (no single “Status” link).

---

## 1. Install WIMS (once per PC that runs agents or the server)

### Windows

1. Put the tree on disk (`git clone` or copy so you have `src\wims\` and `scripts\windows\`).  
2. Double-click **`scripts\windows\Install-Wims.cmd`** (UAC once on a golden image).  
3. Day-to-day: Desktop **WIMS**. Update: Desktop **Update WIMS** or launcher banner.  

Details: [scripts/windows/README.md](../scripts/windows/README.md).

### Linux

```bash
sudo apt install -y git python3 python3-tk   # 3.10+; 3.12–3.14 fine
cd WIMS
scripts/install-wims-desktop.sh              # optional Desktop entry
PYTHONPATH=src python3 -m wims               # launcher
```

No `pip` packages for runtime.

---

## 2. WSJT-X (every digi instance)

**Settings → Reporting**

| Setting | Value |
|---------|--------|
| **UDP Server** | `224.0.0.73` |
| **UDP Server port** | **`2237`** (all bands — see [decision 2026-09-05](decisions/2026-09-05-plane-a-single-port-2237.md)) |
| **Accept UDP requests** | ✅ ON (needed for Operate **Work** / Halt) |
| **Outgoing interface** | Contest **LAN** NIC (not Tailscale, not blank if the roster stays empty) |

Do **not** use per-band ports 2238–2243 for the current fleet. Every digi instance shares
`224.0.0.73:2237`. Band comes from the radio dial (Status), not from the UDP port.

**Also required**

- Unique **`--rig-name=`** per instance (fleet-wide), e.g. `TRAILER-144-FT8`. Default name `WSJT-X` collides if two instances use it.  
- **Secondary UDP / “Broadcast to N1MM”** → **OFF** when the **N1MM agent Log** path owns logging (avoids double-log).  
- CAT/PTT stays **seat-local** (e.g. Icom + wfview) — not configured in WIMS.

**Check:** launcher **WSJT-X** intent or `Check-WimsSetup.cmd` / `python -m wims.agent --solo`.  
**See live:** console **WSJT-X** tab (`/wsjt`).

---

## 3. N1MM (every logger PC)

### 3a. Broadcast Data (WIMS presence + live contacts)

**Config → Configure Ports → Broadcast Data**

| Item | Value |
|------|--------|
| **Radio** | ✅ ON |
| **Contacts** | ✅ ON |
| **Destination (both)** | **`127.0.0.1:12060`** only |

Same string on **every** N1MM PC. Do **not** put Tailscale `100.x` addresses here.  
Do **not** confuse this with N1MM↔N1MM networking (**UDP/TCP 12070** — Network Status); WIMS does not use 12070.

### 3b. N1MM WSJT / digi UDP reader — **OFF (obsolete)**

Do **not** enable N1MM’s **WSJT/JTDX UDP reader** (Configurer → WSJT/JTDX Setup).
That joins plane A and double-logs against the agent.

The **N1MM agent** owns digi → this N1MM (Log), Broadcast relay, and KEY.

### 3c. N1MM agent (WIMS) — Log + Broadcast + KEY

On the same PC as N1MM:

1. Set `WIMS_SERVER=http://<site-server-lan-ip>:8787` (env or launcher discovery).  
2. Desktop **WIMS** → check **N1MM** (and **SSB/CW KEY** if this seat has KEY).  
3. That starts the **N1MM agent** (`wims.seat`) with three sections:

| Section | What it does |
|---------|----------------|
| **Log** | Joins `224.0.0.73:2237`, filters by live band (RadioInfo), forwards Logged QSOs → local N1MM (`127.0.0.1:52001`, then `:2333`) |
| **Broadcast** | Hears N1MM Broadcast Data on `127.0.0.1:12060` → POSTs XML to the site (`/api/n1mm/broadcast`) so the **N1MM** tab shows this logger |
| **KEY** | CTS → same-band type-18 holds (needs Keyline / serial + patched WSJT-X gate) |

**See live:** console **N1MM** tab (`/n1mm`).

### 3d. Contest log file (dupe/mult seed)

WIMS reads `.s3db` on the **site server** machine (Setup → pick contest / Resync).  
Copy the open log onto the server if N1MM runs elsewhere.

---

## 4. Keyline interface (SSB/CW KEY → inhibit)

Hardware: [hardware/keyline_interface/](../hardware/keyline_interface/)  
Identity / flash: [eeprom/README.md](../hardware/keyline_interface/eeprom/README.md)

### Wiring (operator view)

- KEY/PTT sense from the SSB/CW radio → Keyline **CTS** (asserted = KEY down = inhibit).  
- Digi seats need **patched WSJT-X** that listens for **TxInhibit type 18** (prefer UDP **22372**, else ephemeral announced in InhibitStatus).  
- Same-band digi instances are held while KEY is down (leases OR across KEY controllers).

### Software on the N1MM / KEY PC

1. Plug Keyline (Windows: COMx; Linux: `/dev/serial/by-id/…Keyline…` or `/dev/ttyUSB*`).  
2. Desktop **WIMS** → check **SSB/CW KEY**.  
3. **KEY device** combobox: pick the Keyline COM/tty (Refresh after plug-in).  
4. N1MM agent **KEY** section should show CTS idle / KEY down; targets appear after digi instances announce InhibitStatus on this band.

Lab without hardware: device `sim:up` / `sim:down`.

**Not yet:** full Tailscale-proofing of contest UDP — see [plan/tailscale_contest_lan.md](plan/tailscale_contest_lan.md). For bring-up, disable Tailscale on logger VMs or raise its interface metric.

---

## 5. Site console checklist

| Check | Where |
|-------|--------|
| Roster fills | **Operate** `/` |
| Digi instances alive | **WSJT-X** `/wsjt` |
| Both N1MMs listed | **N1MM** `/n1mm` (needs agent + `127.0.0.1:12060`) |
| Contest log / resync | **Setup** `/setup` |
| Band policy / agents | **Overview** `/overview` |

**Work** = click a roster line (answer). **Call CQ** = in WSJT-X, not WIMS.

---

## Common failures

| Symptom | Likely fix |
|---------|------------|
| Roster empty, waterfall full | Wrong band **port** or Outgoing interface not LAN |
| Two digis, one Source | Both using default `--rig-name` / UDP id `WSJT-X` |
| N1MM Network Status OK, WIMS N1MM tab empty | That is **12070**. Set Broadcast Data to **`127.0.0.1:12060`** and run **N1MM agent** with `WIMS_SERVER` |
| N1MM agent “Waiting for Broadcast” | Radio unchecked, wrong dest, or Tailscale snatch — use localhost dest |
| KEY never holds digi | Wrong COM; digi not on inhibit port / no type-17; band coordinated not interlock |
| Double QSOs in N1MM | N1MM **WSJT UDP reader** still ON, and/or WSJT Secondary UDP 2333 **and** N1MM agent Log both on |

---

## Document history

| Date | Note |
|------|------|
| 2026-09-05 | Initial operator setup (N1MM agent Broadcast/Log/KEY, localhost Broadcast Data, console tabs) |
