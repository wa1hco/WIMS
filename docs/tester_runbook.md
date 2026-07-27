# WIMS — Solo Tester Runbook

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

In WSJT-X: **Settings → Reporting**, and set:

| Setting | Value |
|---|---|
| UDP Server | `224.0.0.73` |
| UDP Server port number | **Band port** (see table) — solo default often `2237` |
| Accept UDP requests | ✅ checked |

| Band | Port (must match N1MM WSJT reader **and** WIMS `--port`) |
|------|----------------------------------------------------------|
| 50 MHz | **2237** |
| 144 MHz | **2238** |
| 222 MHz | **2239** |
| 432 MHz | **2240** |

Example: 2 m seat already on N1MM `224.0.0.73:2238` → use port **2238** in WSJT-X and start
WIMS with that port (see step 4). Do not leave WIMS on 2237 while WSJT-X is on 2238 — roster
stays empty even though the waterfall is full.

Click OK. (The "Accept UDP requests" box is what lets WIMS answer stations for you
later. Leave "Outgoing interface" alone for now — the setup check in step 3 will tell
you if it needs attention.)

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

If your plane A port is **not** 2237 (e.g. 2 m → **2238**), start with an explicit port so
WIMS joins the same stream as WSJT-X / N1MM:

```bat
python -m wims.solo --port 2238
```

(or set the port flag your wrapper passes through to the server — defaults are still 2237).

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
| **UDP port** | same | Same port WIMS is using for that band (solo often `2237`; 2 m may be `2238`) |
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

**Symptom if control path fails:** Work “succeeds” on Operate, but WSJT-X **DX Call / DX Grid
stay blank** and **Enable Tx does not turn on** (as if you never double‑clicked).

| Requirement | Why |
|-------------|-----|
| **Accept UDP requests** ON | Without it, Reply is ignored; double‑click still works |
| WIMS `--iface` = **Linux contest LAN IP** | Multicast leave path |
| Same port as WSJT-X UDP Server | Reply ignored if 2237 vs 2238 mismatch |
| **Unicast to the VM** | WIMS auto-sends Reply to the **last source IP** of that instance, then also the multicast group. Prefer a **fresh** CQ still visible in WSJT-X Band Activity |
| Optional: `--tx-host <VM-LAN-IP> --tx-port <port>` | Force control host if auto unicast is wrong |
| Windows firewall allows UDP from the WIMS host | Else Work ok on WIMS, silence in WSJT-X |

If DX/Enable still do not change after Work: note `tx-meta` destinations (should list the **VM
IP** first) and confirm the CQ is still on WSJT-X’s Band Activity list (old roster rows can age
out of WSJT-X while still showing in WIMS for up to 5 min).

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
| **Roster stays empty** | Re-check step 2: UDP Server `224.0.0.73` and **band port** (e.g. 144 → `2238`). WIMS `--port` must match. Re-run `Check-WimsSetup.cmd`. If it mentions the *outgoing interface*, set WSJT-X → Reporting → Outgoing interface to your main network adapter (or Loopback), OK, and restart WSJT-X. |
| **Test CAT connection refused** (wfview seats) | Enable **RigCtld** in wfview External Control; confirm `127.0.0.1:4533` LISTENING. See networking §3.3. |
| **`[XX]` "not sending decodes over UDP"** | WSJT-X UDP Server box is empty — set it per step 2. |
| **Work / roster click does nothing** | WSJT-X → Reporting → **"Accept UDP requests"** must be checked; WIMS must not be started with `--no-tx`. |
| **Work says ok but DX/Enable unchanged in WSJT-X** | Control packet not accepted — Accept UDP, multi-host dest (VM IP in `tx-meta`), fresh decode still on Band Activity (6c). |
| **TX OFF (read-only)** | Server was started with `--no-tx`. Restart without that flag. |
| **Manual double‑click works, Work does not** | Control path only — Accept UDP + dest (6a/6c). || **Everything shows as "new mult"** | Expected on a sparse or non-VHF log — WIMS counts grid×band mults. Not a problem for testing. |
| **"needed/dupe" doesn't change when I log** | Make sure N1MM's "Broadcast Data" is on (Config → Configure Ports → Broadcast Data) so edits reach WIMS live; or use the **Resync log** button on the Setup page. |
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
Same WSJT-X settings (UDP Server `224.0.0.73` + **band port**, Accept UDP requests on).
