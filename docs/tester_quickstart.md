# WIMS — Tester quick start

**Goal:** evaluate WIMS at home or in the lab without needing a full multi-multi contest.

Pick the **track** that matches what you have. Each track builds on the previous one.

| Track | You have | You prove |
|-------|----------|-----------|
| **A** | Nothing (no WSJT-X / N1MM) | Install, Python, server, browser, agent |
| **B** | Local **WSJT-X** only | Decodes → roster (read-only; no dupe/needed from log) |
| **C** | **WSJT-X + N1MM** (+ optional unique **rig-name**) | Needed/dupe + click-to-Work |
| **D** | Multi-PC / multi-WSJT (optional) | Fleet-style — separate, more like W2SZ |

**WIMS vs GridTracker at home:** GridTracker is excellent for maps, awards, and day-to-day FT8.
WIMS is aimed at **contest-style ranking** (needed vs worked, mult-aware roster) and **click-to-work**
through a controlled path. On one radio at home it is still useful to try; multi-instance is where it
really differs.

**Not an autobot:** a human always starts TX (roster click). **Call CQ** is done in WSJT-X, not WIMS.

---

## Track A — Install and console only (no radio apps)

**Time:** ~15 minutes · **No** WSJT-X or N1MM required.

### A1. Get the tree

| Method | |
|--------|--|
| Git | `git clone https://github.com/wa1hco/WIMS.git` then `cd WIMS` |
| ZIP / USB | Folder must contain `src\wims\` and `scripts\windows\` (or `scripts/` on Linux) |

### A2. Install prerequisites

**Windows**

1. Open `scripts\windows\`
2. Double-click **`Install-Wims.cmd`** → allow UAC once  
3. Expect: Python, optional Git, firewall **TCP 8787**, desktop launchers  
4. Log: `scripts\windows\install-log.txt`

**Linux**

```bash
sudo apt install -y git python3   # 3.10+; 3.12–3.14 fine
# no pip packages required
```

### A3. Start the server and open the browser

**Windows:** double-click **`Start-WimsServer.cmd`** (or Desktop **WIMS Server**).  
**Linux:**

```bash
cd WIMS
PYTHONPATH=src python3 src/wims/server/app.py --iface 127.0.0.1 --no-presence
```

Open:

| Page | URL |
|------|-----|
| **Operate** | http://localhost:8787/ |
| **Status** | http://localhost:8787/status |
| **Setup** | http://localhost:8787/setup |

**Pass:** pages load; Status shows live UI (instances/loggers may be empty — normal).

### A4. Optional — seat agent (still no WSJT-X)

**Windows:** **`Start-WimsAgent.cmd`** (one-shot check) or **WIMS Agent** continuous.  
Local agent UI: http://127.0.0.1:8790/  

**Linux:**

```bash
PYTHONPATH=src python3 -m wims.agent --solo
# continuous:  python3 -m wims.agent --daemon --server http://127.0.0.1:8787
```

**Pass:** agent prints a setup report; continuous agent appears under Status/Setup **agents** if the server URL is correct.

### A5. Optional — no-RF “fleet” (emulator)

With the **server already running** on the same machine:

```bash
PYTHONPATH=src python3 testbed/simulators/emulator.py --iface 127.0.0.1 \
  --instances SIM-6M:50313000,SIM-2M:144174000
```

**Pass:** Status shows simulated instances; Operate may show synthetic activity depending on emulator traffic.

**Stop:** Ctrl+C the server (and emulator/agent) windows.

---

## Track B — One local WSJT-X (no N1MM)

**Time:** ~20 minutes · Proves **decode path** and **roster**. No contest log → no needed/dupe from N1MM (everything looks “needed”).

### B1. Finish Track A (server + browser working)

Prefer **solo** on one PC (simplest):

| OS | Start |
|----|--------|
| Windows | **`Start-Wims-Solo.cmd`** |
| Linux | `scripts/start-wims-solo.sh` or `PYTHONPATH=src python3 -m wims.solo` |

Solo = local server, no fleet presence election, browser to Operate.

### B2. Configure WSJT-X

**Settings → Reporting:**

| Setting | Value |
|---------|--------|
| UDP Server | `224.0.0.73` |
| UDP Server port | **2237** (or your band port — see table) |
| Accept UDP requests | ✅ ON |
| Outgoing interface | This PC’s main NIC if roster stays empty |

| Band | Port |
|------|------|
| 50 MHz | **2237** |
| 144 | **2238** |
| 222 | **2239** |
| 432 | **2240** |

WIMS solo defaults to **2237**. If you use another port, start with that port, e.g. `python -m wims.solo --port 2238`.

Optional but good: **`--rig-name=HOME-FT8`** (or any unique name) so the Status instance id is not the default `WSJT-X`.

### B3. Check setup

**Windows:** **`Check-WimsSetup.cmd`**  
**Linux:** `PYTHONPATH=src python3 -m wims.agent --solo`

Fix anything marked **`[XX]`** before continuing.

### B4. Decode

Leave WSJT-X decoding (any band/mode FT8 is fine). Wait 1–2 cycles.

**Pass:**

- Status → instance row (id + host, usually this PC)  
- Operate → **Call roster** populates  
- Clicking a row may fill DX / Enable Tx if Accept UDP is on (use dummy load / low power if testing TX)

**Without N1MM you will not get** real needed/dupe greying from a contest log (Track C).

---

## Track C — WSJT-X + N1MM (home or single seat)

**Time:** ~30 minutes · Full single-seat evaluation: **needed/dupe** + **Work**.

### C1. Tracks A–B working (roster sees decodes)

### C2. N1MM

1. N1MM running and logging (any contest/casual log is fine).  
2. **Config → Configure Ports → Broadcast Data:** enable **Contacts** (and Radio if you use it) so WIMS sees log updates.  
3. WSJT-X port in N1MM’s WSJT reader = **same** port as WSJT-X / WIMS (e.g. both 2237).  
4. **Historical log (dupe/mult seed):** WIMS reads `.s3db` files only on the **machine running the WIMS server**.  
   - Same PC as N1MM → auto-scans N1MM `UserDir\Databases` (registry), `%USERPROFILE%\Databases`, and `Documents\N1MM Logger+\Databases`. Check server console for **N1MM seed scan dirs**.  
   - If Setup still says no logs while N1MM has `wa1hco.s3db` open: note the full path in N1MM and set `WIMS_SEED_DB_DIR` or pass `--seed-db` to that file.  
   - Server on another host/VM → **copy** the open log `.s3db` onto the server (or point `WIMS_SEED_DB_DIR` at a share), then Setup → **Rescan** and pick **DX** (or your contest).  
   - UDP Contacts alone do **not** load your past 11k QSOs — only new QSOs after start.

### C3. Unique rig-name (recommended even with one radio)

Stops future pain if you add a second PC later.

| Place | What |
|-------|------|
| Shortcut / Startup | `"…\wsjtx.exe" --rig-name=HOME-FT8` |
| WIMS seat pack | `scripts\windows\seat-local.cmd` → `WSJTX_RIG_NAME=HOME-FT8` |
| Helper | **`Find-And-Set-WsjtxRigName.cmd -RigName HOME-FT8 -Apply`** then exit all `wsjtx.exe` and restart |

### C4. Prove needed / dupe

1. Callsign on roster as **needed**.  
2. Log it in N1MM → row goes **dupe** (grey).  
3. Delete QSO in N1MM → **needed** again.

### C5. Prove Work (dummy load / low power)

1. **Accept UDP** still ON.  
2. Manual double-click in WSJT-X Band Activity works (proves radio).  
3. Fresh CQ still on Band Activity → **click the roster line** in WIMS.  
4. WSJT-X fills DX / Enable Tx; **Halt TX** in WIMS stops.

If click works in WIMS UI but WSJT-X ignores DX: firewall allow **wsjtx.exe** inbound UDP (not only port 2237 — control uses an ephemeral port). Details: [tester_runbook.md](tester_runbook.md) §6.

### C6. What “useful at home” looks like

- One radio, contest or casual log → ranked **needed** list while you S&P.  
- Click-to-work without hunting Band Activity.  
- Optional later: second radio / second PC → Track D.

GridTracker remains better for maps and long-term awards; WIMS is better for **“who do I still need and can I answer them from one console?”**

---

## Track D — Multi-WSJT / multi-PC (fleet-style, optional)

**This is not required for home evaluation.** It emulates multi-multi / multi-seat setup (e.g. W2SZ-style).

| Topic | Where |
|-------|--------|
| Band ports (one stream per band) | [plan/wims_networking.md](plan/wims_networking.md) §4 |
| Unique `--rig-name` per radio | Required — never two `WSJT-X` defaults |
| One N1MM per band as logger-of-record | Same networking doc |
| Site server vs seat agent | Server on one host; seats run agent + browser |
| Windows seat pack / Startup | [scripts/windows/README.md](../scripts/windows/README.md) |
| Rig-name on all shortcuts | `Find-And-Set-WsjtxRigName.cmd` |

**Minimum dual-PC lab:**

1. **Server PC:** WIMS server (joins ports **2237–2240** by default).  
2. **Each radio PC:** unique rig-name; UDP `224.0.0.73` + **band port**; Outgoing interface = LAN; Accept UDP ON.  
3. Browser → `http://<server-lan-ip>:8787/`.

---

## Cheat sheet — Windows double-clicks

| File | Track | Role |
|------|-------|------|
| **`Install-Wims.cmd`** | A | Prerequisites |
| **`Start-WimsServer.cmd`** | A / D | Site server |
| **`Start-Wims-Solo.cmd`** | B / C | One-PC server + browser |
| **`Check-WimsSetup.cmd`** | B / C | Plain-language setup audit |
| **`Start-WimsAgent.cmd`** | A | One-shot agent report |
| **`WIMS Agent` (desktop)** | A / D | Continuous agent |
| **`Find-And-Set-WsjtxRigName.cmd`** | C / D | Unique UDP id on launchers |

---

## Troubleshooting (all tracks)

| Symptom | Likely fix |
|---------|------------|
| Browser can’t open :8787 | Server not running; another app on 8787; firewall (server install adds TCP 8787) |
| Roster empty (Track B/C) | WSJT-X port ≠ WIMS port; UDP Server not multicast; Outgoing interface blank |
| Two PCs, one WSJT row | Same default id `WSJT-X` — set unique `--rig-name` |
| Work “ok” but DX blank | Accept UDP off; Windows firewall on **wsjtx.exe**; stale Band Activity line |
| Needed never greys | N1MM Broadcast Contacts off; wrong contest log on Setup; no N1MM (Track B) |
| Bind warning on :2240 | Harmless if you don’t use 432; other app holds UDP 2240 — skip or free the port |

More detail: [tester_runbook.md](tester_runbook.md) (solo deep dive) · [plan/wims_networking.md](plan/wims_networking.md) (fleet).

---

## Suggested evaluation checklist

Copy this and tick what you care about:

- [ ] **A** Install completes; Operate/Status/Setup load  
- [ ] **A** Agent one-shot report runs (optional continuous)  
- [ ] **B** Local WSJT-X → instance + roster lines  
- [ ] **C** N1MM log flip needed ↔ dupe  
- [ ] **C** Roster click → Work (dummy load)  
- [ ] **C** Halt stops TX  
- [ ] **D** (optional) Two unique rig-names, two hosts on Status  

When reporting issues, note **track**, OS, and whether N1MM/WSJT-X/rig-name were in use.
