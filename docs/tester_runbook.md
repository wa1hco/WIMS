# WIMS — Solo Tester Runbook

> **Start here for most people:** [tester_quickstart.md](tester_quickstart.md)  
> (install-only · WSJT-X only · WSJT-X+N1MM · optional multi-PC).  
> **Roles / what ships:** [tester_roles.md](tester_roles.md).  
> This runbook is the **deep solo path** (WSJT-X + N1MM on one PC).

**Try WIMS on one PC, on a single FT8 frequency (any band).** You already run WSJT-X
and N1MM; WIMS adds a browser console that ranks the stations you're hearing, shows
which are *needed* vs *worked*, and lets you answer one with a click.

You do **not** need a contest, a second computer, or any networking knowledge.

> Status of this guide: steps 1–5 (install, watch, needed-vs-dupe) are verified.
> Steps 6–7 (transmitting, CQ) are **provisional pending first on-air testing** — do
> them into a **dummy load / low power** and tell us what you see.

---

## What you need

- Windows 10/11 (Linux/macOS works too — see the end).
- **WSJT-X** and **N1MM+** already installed and working with your radio.
- 10 minutes.

---

## 1. Install WIMS

Double-click **`scripts\windows\Install-Wims.cmd`**. It installs Python + the WIMS
files and adds a firewall rule. It may ask for Administrator (UAC) once. That's all it
installs — it does **not** touch WSJT-X or N1MM.

## 2. Point WSJT-X at WIMS (the one fiddly step)

**Canonical checklist:** [operator_setup.md](operator_setup.md).

In WSJT-X: **Settings → Reporting**, and set:

| Setting | Value |
|---|---|
| UDP Server | `224.0.0.73` |
| UDP Server port number | **`2237`** (all bands — current fleet) |
| Accept UDP requests | ✅ checked |
| Outgoing interface | Contest LAN NIC if roster stays empty |

Click OK. ("Accept UDP requests" lets WIMS Work/Halt. Unique `--rig-name` if you run more
than one WSJT-X.)

**Radio CAT** is separate from WIMS UDP. If the seat uses **wfview** (Icom USB), WSJT-X CAT is
Hamlib NET `127.0.0.1:4533` with RigCtld enabled in wfview — not the radio COM port. Full seat
recipe: [`docs/plan/wims_networking.md`](plan/wims_networking.md) §3.2–§3.3.

## 3. Check your setup

Double-click **`scripts\windows\Check-WimsSetup.cmd`**. You'll get a plain-language
report:

```
WIMS setup check — this PC
==================================
[OK] Ready to test.

WSJT-X
  [OK] Sending decodes to 224.0.0.73:<band-port> — WIMS will see them.
  [OK] 'Accept UDP requests' is ON — WIMS can Work/Halt this radio.
  [OK] Station: <yourcall> / <yourgrid>
...
```

- **`[OK]`** = good. **`[! ]`** = a note (usually fine, read it). **`[XX]`** = fix this first.
- If it says the roster might stay empty because the *outgoing interface* is blank, note
  it — you'll only need to fix it if step 5's roster really is empty.

## 4. Start WIMS and watch

Double-click **`scripts\windows\Start-Wims-Solo.cmd`**. It runs the setup check again,
then starts WIMS and opens your browser to **http://localhost:8787/**.

Default plane A is **`2237`**. Do not use the old per-band ports (2238–2243) unless you
are deliberately running a lab multi-port experiment.

With WSJT-X decoding, the **Call roster** fills with the stations you're hearing, ranked,
newest activity and best opportunities near the top. This is the read-only view — nothing
transmits. If the roster stays empty after a couple of FT8 cycles, see **Troubleshooting**.

## 5. Verify the "needed vs dupe" logic

This is the core thing to test — WIMS reads *your* N1MM log to decide who you still need:

1. Pick a callsign showing in the roster as **needed**.
2. In **N1MM**, log a QSO with that callsign (or add it manually).
3. Within a second, that roster row flips to **dupe** (greyed / marked worked).
4. **Delete** that QSO in N1MM → the row flips back to **needed**.

Add and remove a few and confirm the roster tracks your log both ways. You don't need a
contest — any N1MM log works. (On a small/HF log, lots of rows may show as "new mult";
that's expected and harmless.)

## 6. Transmitting — answer a station  *(dummy load / low power first)*

WIMS does **not** key the radio by itself. **Work** sends a WSJT-X **Reply** UDP packet
(same idea as double‑clicking a decode in WSJT-X). There is **no Enable/Disable TX arm** —
same idea as GridTracker2: **click a line on the call roster** to work that station.

### 6a. Pre-flight (must pass before blaming WIMS)

| Check | Where | Pass looks like |
|--------|--------|-----------------|
| **Accept UDP requests** | WSJT-X → Settings → Reporting | ✅ checked |
| **UDP Server** | same | Fleet multicast e.g. `224.0.0.73` (not blank) |
| **UDP port** | same | **`2237`** (all bands) |
| **Manual double‑click** | WSJT-X Band Activity | Station is called — proves radio + WSJT-X TX path |
| **Roster sees the CQ** | WIMS Operate | Row for that call (proves decode path *to* WIMS) |

If manual double‑click works but roster click does not, the problem is almost always the
**control path** (Accept UDP, or WIMS sending Reply to the wrong host/port).

### 6b. Operate steps

1. Confirm the station is on the roster (**fresh** decode — still on WSJT-X Band Activity).
2. **Click the roster line** (or its **Work** button).
3. Watch the status line under the TX controls (`tx-meta`):
   - Success: `→ Work CALL on INSTANCE → host:port, …` plus a short note.
   - Failure: plain-language reason (unknown row, group busy, `--no-tx`, etc.).
4. In **WSJT-X**, DX Call/Grid should fill and Enable Tx engage (same as a double‑click).
5. **Halt TX** = panic stop (always available).

### 6c. Multi-host (WIMS on Linux, WSJT-X in a Windows VM)

**Symptom if control path fails:** Work “succeeds” on Operate (or a `TX Reply ok` log line
appears), but WSJT-X **DX Call / DX Grid stay blank** and **Enable Tx does not turn on**
(as if you never double‑clicked).

| Requirement | Why |
|-------------|-----|
| **Accept UDP requests** ON | Necessary; not sufficient alone |
| WIMS `--iface` = **Linux contest LAN IP** | Multicast leave path |
| **Unicast to MessageClient** | WSJT-X binds an **ephemeral** control port. WIMS must Reply to the **last `recvfrom` source IP:port** of that instance (not host:2237). `tx-meta` first dest looks like `192.168.x.x:5xxxx` |
| **Windows firewall** | Allow inbound UDP to **wsjtx.exe** (or from the WIMS host). A rule limited to LocalPort **2237 only is wrong** for control — control arrives on the ephemeral port. Outbound Status/Decode can work while inbound Reply is blocked |
| Fresh CQ | Decode must still be on WSJT-X Band Activity; WIMS roster keeps rows longer (5 min) |

**Quick Windows firewall test** (on the VM, PowerShell as Admin) — prefer program-based:

```powershell
# Prefer: any UDP to the WSJT-X process (covers ephemeral control ports)
New-NetFirewallRule -DisplayName "WSJT-X UDP control (process)" -Direction Inbound `
  -Program "C:\WSJT\wsjtx\bin\wsjtx.exe" -Protocol UDP -Action Allow -Profile Any
# Adjust -Program path to your install (e.g. "C:\Program Files\wsjtx\bin\wsjtx.exe")
```

Then Work again and watch the **WIMS server console** for:

```text
TX Reply ok 'INSTANCE' 'CALL' msg='CQ …' → [192.168.x.x:54321, 224.0.0.73:2237]
```

The **first** dest must be the VM IP with a **high/ephemeral port** (not `:2237`). If you still
see only `host:2237`, restart WIMS after this fix and wait for a fresh Status/Decode so the
control endpoint is learned.

If that line is missing, the click never reached Work (or server is old). If it is present but
WSJT-X still ignores DX/Enable: firewall, stale Band Activity line, Accept UDP off, or id mismatch.

Server startup log should show something like:

```text
TX control -> 224.0.0.73:2237  (roster click = Work; Halt always on; Reply also unicast …)
```

If you see **TX control disabled (--no-tx)**, Work cannot send at all.

### 6d. What “success” means

| Layer | Pass |
|-------|------|
| WIMS | Work returns ok; `tx-meta` shows call + dests |
| WSJT-X | Begins calling that station (Tx Enable / sequence) |
| N1MM | QSO logs when the contact completes (same as a manual QSO) |

Manual WSJT-X + N1MM logging **without** WIMS only proves the radio stack. To pass
the WIMS TX test, roster **Work** must start the QSO without using the WSJT-X double‑click.

## 7. Calling CQ

**Call CQ from WSJT-X itself** (Enable Tx / your normal CQ), the same as you do today.
WSJT-X's remote-control interface has no "call CQ" command, so the WIMS **Call CQ** button
is intentionally disabled — WIMS's job is watching the roster and helping you *answer*
stations, not originating your CQ. (An experimental one-shot CQ exists behind a flag but
is off by default and not part of this test.)

## 8. Stop

Close the browser tab and close the **Start-Wims-Solo** window (or Ctrl-C in it). WSJT-X
and N1MM keep running normally.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Roster stays empty** | Re-check step 2: UDP Server `224.0.0.73` port **`2237`**. Re-run `Check-WimsSetup.cmd`. If it mentions *outgoing interface*, set WSJT-X → Reporting → Outgoing interface to the contest LAN NIC, OK, restart WSJT-X. |
| **Test CAT connection refused** (wfview seats) | Enable **RigCtld** in wfview External Control; confirm `127.0.0.1:4533` LISTENING. See networking §3.3. |
| **`[XX]` "not sending decodes over UDP"** | WSJT-X UDP Server box is empty — set it per step 2. |
| **Work / roster click does nothing** | WSJT-X → Reporting → **"Accept UDP requests"** must be checked; WIMS must not be started with `--no-tx`. |
| **Work says ok but DX/Enable unchanged in WSJT-X** | Control packet not accepted — Accept UDP, multi-host dest (VM IP in `tx-meta`), fresh decode still on Band Activity (6c). |
| **TX OFF (read-only)** | Server was started with `--no-tx`. Restart without that flag. |
| **Manual double‑click works, Work does not** | Control path only — Accept UDP + dest (6a/6c). || **Everything shows as "new mult"** | Expected on a sparse or non-VHF log — WIMS counts grid×band mults. Not a problem for testing. |
| **"needed/dupe" doesn't change when I log** | Broadcast Data **Contacts** → `127.0.0.1:12060` + **N1MM agent** with `WIMS_SERVER`; or **N1MM → Resync log**. |
| **Port 8787 already in use** | Start with a different port: `python -m wims.solo --http-port 8788` (then open that port). |

## What to report back

- Did the roster populate, and did needed↔dupe track your log edits?
- (If you tried TX) did **Work** start the right QSO, and did **Halt** stop it?
- Anything confusing in the console or the setup check wording.

---

## Linux / macOS

```bash
scripts/start-wims-solo.sh        # setup check + server, opens the browser
# or:  PYTHONPATH=src python3 -m wims.solo
# setup check only:  PYTHONPATH=src python3 -m wims.agent --solo
```
Same WSJT-X settings (UDP Server `224.0.0.73` port **`2237`**, Accept UDP requests on).
