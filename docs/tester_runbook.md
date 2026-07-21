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
| UDP Server port number | `2237` |
| Accept UDP requests | ✅ checked |

Click OK. (The "Accept UDP requests" box is what lets WIMS answer stations for you
later. Leave "Outgoing interface" alone for now — the setup check in step 3 will tell
you if it needs attention.)

## 3. Check your setup

Double-click **`scripts\windows\Check-WimsSetup.cmd`**. You'll get a plain-language
report:

```
WIMS setup check — this PC
==================================
[OK] Ready to test.

WSJT-X
  [OK] Sending decodes to 224.0.0.73:2237 — WIMS will see them.
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

## 6. Transmitting — answer a station  *(provisional: dummy load / low power first)*

WIMS never transmits on its own. There is a master switch that starts **DISARMED**.

1. On the Operate page, click **Enable TX**. The indicator turns to **TX ARMED** (loud).
2. Each roster row now shows a **Work** button. Click it to answer that station — WSJT-X
   starts the QSO (it "replies" to that decode exactly as if you'd double-clicked it in
   WSJT-X).
3. **Halt TX** is always available — it's the panic stop; click it to stop transmitting.
4. When done, click **Disable TX** to disarm.

> First time, run into a **dummy load or at low power** and confirm: (a) WSJT-X actually
> starts calling the station you clicked, and (b) Halt stops it. Report anything that
> doesn't match — this is the first real-radio test of the TX path.

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
| **Roster stays empty** | Re-check step 2 (UDP Server `224.0.0.73`, port `2237`). Re-run `Check-WimsSetup.cmd`. If it mentions the *outgoing interface*, set WSJT-X → Reporting → Outgoing interface to your main network adapter (or Loopback), OK, and restart WSJT-X. |
| **`[XX]` "not sending decodes over UDP"** | WSJT-X UDP Server box is empty — set it per step 2. |
| **Work button does nothing** | You must click **Enable TX** first; and WSJT-X → Reporting → "Accept UDP requests" must be checked. |
| **Everything shows as "new mult"** | Expected on a sparse or non-VHF log — WIMS counts grid×band mults. Not a problem for testing. |
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
Same WSJT-X settings (UDP Server `224.0.0.73:2237`, Accept UDP requests on).
