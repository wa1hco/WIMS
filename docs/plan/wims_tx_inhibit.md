# TX Inhibit — low-latency transmit gating for WSJT-X seats

**Status: analysis & design for review — nothing here is built.** Companion to
[wims_design.md](wims_design.md) §3.4.1 (SSB/CW priority interlock) and the
[Switchboard concept](wims_switchboard_concept.md) (F7). This document analyzes the WSJT-X
transmit-enable path and designs an **Inhibit TX** function that gates the **PTT signal to the
radio** with the lowest achievable latency — a finer instrument than the UDP Halt Tx / Enable
round-trip.

Because this station builds and runs its own WSJT-X (the *improved_PLUS* fork), **patching
WSJT-X itself is in scope** — that is the main new degree of freedom relative to §3.4.1, which
was designed around an unmodified WSJT-X.

**WSJT-X working trees (separate GitHub projects):**

- **Mainline + gate (primary for the patch):**
  [wa1hco/wsjtx-wims](https://github.com/wa1hco/wsjtx-wims) — baseline tag `baseline-v3.0.2`
  (official WSJT-X v3.0.2), then the TX Inhibit gate on `main`. CI builds Linux/Windows/macOS;
  test binaries via GitHub Releases (`build/v*` tags). See that repo’s `docs/SUPERBUILD.md`
  and `docs/WIMS_TX_INHIBIT.md`.
- **Improved drop (tracking / rebase source):**
  [wa1hco/wsjtx-improved-wims](https://github.com/wa1hco/wsjtx-improved-wims) — baseline tag
  `base-3.1.0-improved-AL-PLUS-260522`. Use when rebasing the gate onto Improved for seats
  that run DG2YCB builds until (if) either lineage accepts an equivalent gate.

WIMS keeps the Key agent, assignment UI, and pure-logic tests
(`src/wims/interlock/inhibit.py`).

**Inhibit generators** (same protocol; three programs):

| Program | Project | Doc |
|---------|---------|-----|
| **inhibit-test** | wsjtx-inhibit | Existing lab tool |
| **inhibit-agent** | wsjtx-inhibit | **[inhibit_agent.md](inhibit_agent.md)** — CTS → localhost gate (doc has no WIMS dependency; copy into wsjtx-inhibit) |
| **WIMS Key agent** | WIMS | **[wims_key_agent.md](wims_key_agent.md)** — multi-target list from WIMS |

Gate/protocol detail stays in **this** file. Datagrams are never routed through a WIMS server.

---

## 1. Scenario and requirement

One band, two transmitters, one rule (**one radiated signal per band**):

- A WSJT-X seat: its own radio, decoding continuously, making contacts that the WSJT-X
  operator enables (locally or via WIMS click-to-work). FT8/MSK144 cycles run on the mode's
  clock.
- An SSB/CW station on the **same band**, in run or S&P, whose transmissions have **priority**
  under the contest rule **when the band is in interlock policy**.

**WIMS band-sharing policy** ([wims_design.md](wims_design.md) **§2.14**):

| Policy | This document (TX Inhibit) |
|--------|----------------------------|
| **`interlock`** | **In force** — KEY/UDP hold stops WSJT-X RF as designed below |
| **`coordinated`** | **Not actuated** — operators hand off manually; WIMS shows mutual TX/QSO status only. KEY agents may still report telemetry; they must **not** send holds that gate RF solely for priority |

This document specifies the **interlock** path (original WIMS mission). Coordinated mode is
not a weaker inhibit — it is **no inhibit for priority**, with information UX in the main design.

**Requirement (interlock policy):** when the SSB/CW operator keys, any WSJT-X emission on that
band must stop — and must not start — until the band is theirs again. The stop must be fast
enough that the overlap is negligible (target: ≤10 ms from key-down to RF gone, per §3.4.1).
The mechanism must work:

- **standalone at the seat** (no WIMS server involved — the interlock must survive a server
  restart, §3.4.1 "trigger path never via the server"), and
- from **two kinds of trigger**: a locally wired USB-serial **CTS** input carrying the SSB/CW
  PTT state, or a **UDP inhibit datagram** from an agent on the PC connected to the SSB/CW
  radio.

## 2. Why Halt Tx / Enable is the wrong instrument

The current design (§3.4.1 Layer 1) uses the WSJT-X UDP **Halt Tx** message as cleanup behind
the fast audio mute. As the *primary* mechanism it is blunt in four distinct ways:

1. **It destroys sequencer state.** Halt Tx aborts the QSO auto-sequence, not just the current
   emission. A 0.8 s SSB burst mid-cycle costs the whole QSO in progress, which then needs a
   human to re-initiate. (The puncture bench, `testbed/tx_interrupt_bench.py`, showed the RF
   interruption itself is nearly free — gaps ≤1.6 s did not measurably hurt FT8 decode
   probability at any workable SNR. The protocol tolerates brief interruption; only the
   Halt-based *control path* turns it into a lost QSO.)
2. **There is no "Enable" to send.** The WSJT-X UDP API has Reply (4) and Halt Tx (8); it has
   **no un-halt / enable-TX message**. Resumption after a Halt requires a human at the seat or
   a fresh Reply — so "Halt at key-down, Enable at key-up" is not actually implementable as
   stated, and the design text needs correcting on this point (§8).
3. **It is slow to take effect.** Traced through the source (Appendix A): a UDP Halt rides the GUI
   event loop, waits up to a 100 ms tick for the stop edge, then a fixed 200 ms timer before
   PTT drops — **~210–400 ms to PTT-down typical, >700 ms worst case**; audio dies earlier
   (~50–120 ms). That is why §3.4.1 needed the external audio-gain mute (Layer 2) at all.
4. **Re-enable policy is undefined.** §3.4.1 specifies key-down behavior thoroughly and says
   nothing about key-up. Blindly re-arming TX at every key-up is wrong (CW is a *train* of
   key-down/up transitions; S&P SSB is bursts) and violates the spirit of "no unattended TX."
   §7 defines the release policy explicitly.

**The reframe:** what the interlock needs is not a command pair (halt…enable) but a **gate** —
a level, not an edge. While asserted, no RF. When released, nothing happens except that the
gate is open; WSJT-X's own sequencer resumes its own schedule if and only if it was already
going to transmit. A gate has no "blindly enable" failure mode by construction.

## 3. Proposed function: TX Inhibit (gate semantics)

One boolean per WSJT-X instance: **INHIBIT**. Sources (§4) are OR-ed.

**The principle that governs everything else: inhibit gates the *radio*, not WSJT-X.**
"Transmit" means two different things, and this design must never confuse them:

| | Meaning | Inhibit's effect |
|--|---------|------------------|
| *WSJT-X transmitting* | The program's activity: sequencer scheduling, modulator generating audio, UI showing TX | **None. Ever.** |
| *The radio radiating* | PTT line high, RF out | **Suppressed while INHIBIT is asserted** |

WSJT-X's main function does not know inhibit exists. It decides to transmit, starts and ends
its cycles, plays its audio, advances its QSO auto-sequence, and lights its UI exactly as it
always has — while the gate thread (§5) decides at the line whether the radio radiates:
`RTS = intent ∧ ¬inhibit`. The scenarios then fall out with no special cases:

- **Brief burst mid-cycle:** the RF has a hole in it (mask interval + agent hang, §below).
  The modulator never stopped, so the waveform stays on the symbol clock and RF resumes
  mid-waveform the instant the gate opens — exactly the punctured signal measured in
  `testbed/tx_interrupt_bench.py` (gaps ≤1.6 s: no measurable decode cost).
- **Inhibit spanning a cycle start:** WSJT-X "transmits" normally; nothing radiates until the
  gate opens, then the remainder radiates, correctly aligned — a leading puncture. No
  late-start logic, no cancelled timers, no skipped cycles.
- **Fully masked cycle:** nothing radiates. To WSJT-X — and, crucially, to the QSO — this is
  indistinguishable from a transmission the other station failed to copy, a case FT8's
  auto-sequence already handles by repeating. As far as the protocol is concerned, inhibit
  and QSB are the same event.
- **Release:** initiates nothing. The line can rise only because WSJT-X is *currently*
  asserting intent — the gate is an AND, not a command.

The one visible trace is presentation, kept outside the TX logic: a status-bar badge
("TX INHIBITED — held by ROY-222-SSB") plus the InhibitStatus telemetry (§11.4), both fed by
the gate thread. Without the badge an operator would see "Transmitting" with no RF and no
explanation — the badge is display only, never behavior.

**Hang time (release hysteresis) — implemented in the Key agent, not in WSJT-X.** The
**Key agent** holds the band: it keeps sending hold keepalives (`ttl_ms` > 0) until its input has been
continuously clear for the hang time, then sends the release (`ttl_ms: 0`, §11.3). The
WSJT-X gate needs **no
hysteresis of its own** — it obeys each datagram's TTL (release = `ttl_ms: 0`) and expires by deadman, nothing more. This
puts the per-operator tuning at the SSB/CW seat where the operating style is, and keeps
WSJT-X state-free (per the strict-simplicity rule, §11). Assert is always immediate.

**What hang is for — one problem only (sharpened 2026-08-02, per WA1HCO):** keeping the
WSJT-X radio's PTT from **following dits and dahs when the CW station runs break-in**.
Puncture mode drives the radio's PTT, so without hang every inter-element and inter-word
gap would cycle the WSJT-X seat's own T/R and amp relays at keying rate — the §4.1.0
relay-wear problem, self-inflicted. Nothing else needs hang: unkey bounce and the
ms-scale dual-signal blip at a reopen are covered by a standing station requirement
(PTT-to-radio and KEY-to-amp wiring must be safe under *any* pattern of assert/release),
and reopening between a phone operator's overs is *correct* one-signal-at-a-time
operation that preserves puncture margin. **Sizing for the CW case:** hang must exceed
the longest silence inside one transmission — the 7-dit inter-word gap (1200/WPM ms per
dit): 420 ms at 20 WPM, 336 at 25, 280 at 30, 210 at 40 — hence 8 dit-times, matched to
the measured sending speed.

**Adaptive hang (adopted direction for the agent):** the agent sees every KEY edge, so the
line self-classifies from closure statistics — no mode input needed, keeping the agent
standalone. Full-QSK CW is a dense train of short closures (30–200 ms elements); SSB-PTT is
one closure held for seconds with no internal edges; VOX SSB and semi break-in CW also show
long closures (the rig's VOX delay / break-in hang pre-bridges the short gaps). Rule:

- **CW-like closures:** hang = **8 × measured dit-time**, clamped 0.2–1.0 s — exactly what
  the sending speed requires (300 ms at 30 WPM, 640 ms at 15 WPM). **CW mode requires dit
  evidence** (a closure ≤ 0.2 s — a dit at ≥ 6 WPM — in the recent window; the estimate is
  the shortest such closure). A **mid-length closure (0.2–0.75 s) alone is neither** a dit
  nor a rig-hung over and gets the debounce — keyboard-bench find, 2026-08-02: a ~0.4 s
  press otherwise reads as a "3 WPM dit" and produces a clamped 1 s hang.
- **Long closures (SSB-PTT / VOX / semi break-in): 20 ms — debounce only** (revised
  2026-08-02 from an earlier 0.5 s, per WA1HCO). These lines carry no CW elements — the
  rig's PTT/VOX/break-in hang already bridged them — so the one problem hang exists for
  is absent, and the hang collapses to a debounce. The earlier 0.5 s was solving
  non-problems: hardware safety under arbitrary keying patterns is a station requirement,
  not the agent's job, and a gate reopen between overs costs only a ms-scale blip at the
  next key-down while keeping the full ~1.6 s puncture margin available.

The hang knob then disappears entirely; the 0.2–5 s manual setting remains only as an
override for pathological cases.

**Fail-safe direction.** Wire/agent failure must not silently un-inhibit *or* permanently kill
the band; the two failure directions get different treatments per source (§4). The invariant:
**a failed inhibit source is loudly visible** (WSJT-X UI badge + WIMS status), never silent.

**What Inhibit is not:** it is not an operator-facing enable/disable (that remains Enable Tx /
Halt Tx in the WSJT-X UI), not a WIMS lease mechanism (§4.5 of the design), and not a
replacement for the preventive gate at TX-initiate time (Mechanism 1) — WIMS still declines to
*start* work on a claimed band. Inhibit is the last, fastest layer.

**Prior art — this is the radio's own TX Inhibit pin, relocated (adopted 2026-08-02).**
Contest radios already ship exactly this function as a rear-panel level input, and the
design deliberately speaks that language so anyone who has wired an SO2R lockout
recognizes it on sight:

| Radio | Input | Configuration | Semantics |
|---|---|---|---|
| **Elecraft K3/K3S** (K4 carries it forward) | ACC **pin 7** | `CONFIG:TX INH` = **OFF / LO=Inh / HI=Inh** — one menu item, nothing else. Display flashes the TX badge while inhibited (annunciator precedent for §11.4) | Assert is a level: while asserted, no RF regardless of keying source. **Release is not** — measured by K2TR (2026-08, not in the manual): inhibit asserted mid-key **latches**; releasing it does not resume RF until PTT itself is dropped and reasserted |
| **Kenwood** TS-890 | **None.** The menu item named "TX Inhibit" (6-03) is a *receive-only configuration* (split-transfer / remote-control use), and PKS on ACC 2 is a data-PTT **input to key** the rig, not an inhibit. "TX Inhibit While Busy" is squelch logic | n/a | No fast external inhibit line exists on this model (manual §16-11/16-12, verified 2026-08-02; earlier "menu-assignable input" claim corrected) |
| **FlexRadio** 6000-series | **TX REQ** RCA interlock inputs | Polarity configurable in SmartSDR | **Initiation gate only:** the pin is sampled when TX starts (~300 ms around PTT) and **ignored during transmission** — it cannot stop RF mid-over. Community-documented and acknowledged; recovery from a blocked start is unkey + rekey |

**Documentation survey (2026-08-02): mid-key behavior is undocumented industry-wide.**
The K4 manual's entire TX Inhibit description is two sentences (use case + polarity);
Elecraft nowhere documents the mid-key latch K2TR measured. Kenwood's manual documents
"TX Inhibit" thoroughly — but it is a different feature (receive-only mode). Flex's
initiation-only sampling surfaces only in community threads, as a complaint. The pattern
underneath: **rig "inhibit" inputs are TX-initiation gates in event-driven firmware, not
continuous gates on the keying line.** Once a transmission event is running, the pin is
either consulted enough to *abort but latch* (Elecraft — the good case) or not consulted
at all (Flex). None of the surveyed rigs implements level-true resume, and none documents
what it does implement — so K2TR's finding is not an Elecraft quirk, it is the industry
norm, and per-rig bench measurement (§9.3) is the only source of truth.

The ecosystem that drives these pins — SO2R controllers, multi-radio lockouts (EA4TX
Interlock; this station's own SO4R_Interlock_V2, which the Keyline board descends from),
amplifier hot-switch protection — all assumes a dumb, fast, level-true inhibit input.

**The arbitration model is what is actually new here (stated 2026-08-02).** Radio inhibit
and the multi-op lockouts built on it serve **symmetric arbitration between two humans:
first to press PTT wins**, the other is blocked from *starting*. Under that rule the
survey's findings are not defects — an initiation gate is the complete requirement, and
the Elecraft latch is invisible because a blocked human re-keys naturally, resetting it
without ever knowing it exists. This design serves a different rule: **one human, several
WSJT-X machines, and the human always wins** — asymmetric priority, applied *mid-over*,
against a machine that holds PTT for a 12+ second cycle and will not re-key until its next
sequence. That rule is what forces every semantic the radios don't have: interrupt during
transmission, true level release, puncture-and-resume. We borrow the radios' vocabulary
(a dumb level input, one config concept, a front-panel annunciator) because it is the
right *interface*; the *semantics* had to be built new because the arbitration model has
no precedent on any rear panel.

The mapping, stated as familiarity requirements on the implementation:

- The WSJT-X gate **is that pin for a modem that lives in software**: a level input that
  suppresses RF while asserted and does nothing else. The §3 semantics are not novel —
  they are the industry's, and the patch should be explainable in one sentence to a K3
  owner: *"it's CONFIG:TX INH, fed over the LAN or the PTT port's CTS pin."*
- The **badge is the front-panel annunciator**; the read-only Settings → Network line is
  the menu page that names the input (§11.2/§11.4).
- **Naming follows the radios** (§11.7.4): the feature is "TX Inhibit", the badge says
  "TX INHIBIT", prose says "inhibit input" — never gate/mute/WIMS-anything in user-facing
  text. (`PttGate` remains the internal class name; operators never see it.)
  **Name re-examined and kept (2026-08-02)** after the arbitration-model insight above:
  alternatives (TX Gate, Hold, Mute, Blank, Yield) all lose to the fact that the plain
  meaning of *inhibit* — no RF while asserted, normal when released — is exactly what this
  implements. The surveyed rigs are the ones that deviate from the word (latch, or ignore
  it mid-over); our function is the name's naive reading, which is why the K2TR latch
  surprised everyone. The familiar name sets exactly the right expectation here.
- **Deliberate deviations, stated:** radios offer a polarity menu because they face
  arbitrary shack wiring; the local CTS input instead fixes polarity by convention
  (§4.1 — the Keyline pull-up makes the safe direction automatic, and zero settings
  outranks matching the menu count). And the UDP source has no radio precedent — radios
  don't have LANs; the TTL deadman (§4.2) is precisely the addition that makes a
  *message* behave as safely as a *wire*.
- **Where our release semantics are deliberately *better* than the K3's:** per the K2TR
  finding above, the K3 latches a mid-key inhibit until PTT cycles. Our gate is a true
  level (`RTS = intent ∧ ¬inhibit`, §5) — and it can afford to be, **because it sits
  upstream of the radio's PTT input**: every gate reopen presents the radio a fresh PTT
  assertion, so puncture-and-resume works even into a latching rig. The latch matters
  only when a rig's own inhibit pin is used as the *actuator* (§6 layer 3) — noted there.

## 4. Inhibit sources and their latency

### 4.1 Local CTS input (SSB/CW KEY wired to the PTT port's CTS pin)

The SSB/CW station's KEY/PTT line (via a relay contact or isolated sense — §4.1.2) drives the
**CTS** pin of a USB-serial port on the WSJT-X PC, and the gate thread watches CTS edges.

**Configuration: none — the inhibit input is the PTT port's own CTS pin.** The gate thread
already owns a serial port (it drives PTT on RTS or DTR, §5); a serial port's modem lines
come in pairs, and the input directions are otherwise unused. So the rule is a convention,
not a setting: **whenever a DTR/RTS PTT port is configured, that same port's CTS is the
local KEY-inhibit input.** One cable, one port, one `open()`. Consequences:

- **Zero added settings** (§11.2 stands) and zero discovery: the port is already known.
- **Fail-safe is automatic and total:** if the dongle is unplugged or dies, the PTT output
  goes with it — the seat *cannot* transmit, rather than transmitting unprotected. The
  earlier "watcher death must assert INHIBIT" rule became unnecessary; physics enforces it.
- **The shared-radio seat (222/432) gets an inherent interlock:** one dongle carries
  RTS→PTT out and KEY→CTS in, and the radio's own keying line locks WSJT-X out whenever the
  operator is on SSB/CW — no agent process, no network, no configuration.
- **What this doesn't cover is the Key agent's job, deliberately.** KEY arriving on a
  different PC, a seat with CAT PTT (no serial PTT port exists — nothing to pair with),
  polarity oddities, multiple KEY sources: all of that flexibility lives in the standalone
  Key agent (§4.2, any port, loopback UDP for the co-located case) — never as WSJT-X
  settings. Same-port CTS is the zero-config common case, not the universal mechanism.

**Polarity and the floating-pin trap (the one sharp edge):** the convention is **CTS
asserted = KEY closed = inhibit**. An unwired CTS behind a proper RS-232 transceiver idles
deasserted (safe); a bare TTL-level breakout may float either way. A wrong-floating pin
produces a *permanently visible* "TX INHIBITED — local KEY line" badge, never silent loss —
the failure direction is RX and loud, which is why this stays convention-per-§4.1.2 rather
than an invert checkbox.

**Hang for a raw KEY line:** unlike §4.2 datagrams (hang already applied by the Key agent),
CTS carries raw dit-by-dit keying, and re-radiating FT8 between a CW operator's elements
would violate the one-signal rule in spirit. The gate thread therefore runs the local CTS
edges through the *same* scheduler logic the Key agent uses (`KeyAgentScheduler`, already
written and tested), with **fixed, compiled-in defaults** (the §3 adaptive hang rule) —
behavior without configuration, per the strict-simplicity rule.

**No deadman on the local source — deliberately.** The UDP source needs a TTL because a
*message stream* is the only evidence of state and can die silently; "the band is held," learned from a
datagram, is a claim about the past that must expire unless refreshed. CTS is a **level**:
the gate thread can read the actual pin at any instant (`TIOCMGET` after every `TIOCMIWAIT`
wake, plus a reconciliation read on the slow tick it already runs for the UDP timers), so
its knowledge is never stale and there is nothing to expire. The §4.3 compose rule is thus
asymmetric by design: `INHIBIT = (CTS level, held through hang) ∨ any unexpired UDP hold` —
the timing machinery (keepalives, TTL, expiry alarms) belongs to the message source only;
the level source carries only the release hysteresis. The failures TTL guards against are
covered for CTS by wiring physics instead (§8): losing the dongle loses the PTT output with
the sense pin, and a stuck line is a permanently visible badge, not a silent state.

#### 4.1.0 What the KEY line actually looks like (vendor survey)

The Key agent senses the SSB/CW rig's amp-keying output, and its *shape* depends on the
rig's break-in configuration — which is also how the industry answers "won't full break-in
beat a relay amp to death?" (verified per vendor, 2026-07):

| Rig | Output | Relay-amp protection | QSK behavior |
|-----|--------|----------------------|--------------|
| **Icom** (SEND, RCA) | Solid-state switch to GND — modern rigs ~16 V / 0.5 A max (7300-class); Icom's own app note says use an external buffer relay for legacy high-voltage/AC keying loops | **TX Delay menu** (HF/50M, ~10–25 ms): SEND asserts early, RF delayed so slow relays close first | Full BK-IN follows CW elements. Measured quirk: 7300 SEND can drop **2–3 ms before RF ends** |
| **Kenwood** (REMOTE DIN, LKY) | +12 V or GND-closure logic, selectable | Per-band **Linear Amplifier Control menu** with added-delay options — the manual names the TL-922 as the "not designed for full break-in, add delay" case | Element-by-element only if configured. (An earlier draft claimed a menu-assignable TX Inhibit *input* — corrected 2026-08-02: on the TS-890 the "TX Inhibit" menu is a receive-only mode, not an external line; §3 survey) |
| **Elecraft** (KEY OUT) | Solid-state | **TX DLY menu** (KEY Out → RF Out per band) | The QSK reference: KPA500 fast quiet relay, **KPA1500 PIN-diode T/R** — silent full break-in by design |
| **Flex** (TX1/2/3 RCA) | Configurable outputs, per-output delay + global TX DELAY | Practice: output delay 0, **TX DELAY 10–20+ ms** against hot-switching | **Full QSK requires the delays set to zero** — QSK and relay-amp protection are explicitly mutually exclusive settings |

The pattern across all four: **the rig holds KEY per its break-in mode** (PTT/SSB and semi
break-in produce one closure per over, with the rig's own hang), **TX-delay menus protect
each closure from hot-switching**, and per-element keying is only ever sent to amps built
for it (PIN diodes or QSK-rated relays). Consequences for this design:

- In SSB/PTT and semi break-in, the sensed line arrives *pre-hung* by the rig — the Key
  agent's hang just adds margin (the two compose additively; harmless).
- In full QSK with a PIN-switched amp, the line is dit-by-dit — **this is the case that
  makes the agent-side hang time (§3) mandatory**, since WIMS must treat the whole CW
  stream as one band occupancy.
- The Icom early-SEND-drop quirk is absorbed by the same hang (even the 20 ms
  long-closure debounce ≫ 3 ms).
- Electrically, the Keyline J1 sense (§4.1.2: ~3.3 V / 2 kΩ wetting through the FTDI
  pull-up, 4.7 V zener clamp) parallels safely across modern solid-state/relay KEY outputs
  — consistent with the SO4R interface spec (open collector, low true, 5–15 V). Connect it
  on the **rig side** of any buffer relay; never across a legacy amp's grid-block keying
  loop (high/negative/AC voltages — the same reason Icom mandates the buffer).

#### 4.1.1 Latency facts to design around

| Hop | Typical | Notes |
|-----|--------:|-------|
| KEY contact → CTS pin | ~0 | Wire |
| USB-serial reports modem-status change | **1–16 ms** | FTDI parts report status at the *latency timer* interval — **default 16 ms, set to 1 ms** (sysfs `latency_timer` on Linux, FTDI driver property page on Windows). CP210x/CH34x similar ballpark. This is the dominant term and it is configurable. |
| OS wakes the watcher | <1 ms | Linux: blocking `ioctl(TIOCMIWAIT)` (edge-triggered wait, no polling). Windows: `WaitCommEvent(EV_CTS)`. Event-driven, not a poll loop — and it is the gate thread itself waiting, no extra thread. **Measured 2026-07-31: the Linux `cp210x` driver returns `ENOTTY` for `TIOCMIWAIT`** — edge-wait is FTDI-only among parts on hand, so non-FTDI dongles use a 1 ms `TIOCMGET` poll fallback (implemented in the spike). Keyline boards (FT230X) are unaffected. This matters beyond the lab: the common **Digirig** PTT dongle is a CP2102N *and does not bring CTS out to its connectors* — so a Digirig seat gets no local KEY input at all (the §4.1 same-port convention is physically inapplicable there); such seats rely on the UDP source, or take a Keyline board. |

#### 4.1.2 The dongle: **Keyline_Interface** (a build item, not a purchase)

Market reality: RTS→PTT keying cables are commercial commodities, but **KEY→CTS sensing is
generally unavailable**. The fleet reference design is the station's own
**Keyline_Interface** board (KiCad project committed at
[`hardware/keyline_interface/`](../../hardware/keyline_interface/), schematic + PCB + SVG;
canonical source lives in the SO4R_Interlock_V2 project). As built — netlist-verified:

- **USB-C → FT230XS** (U1, SSOP-16), used purely as a modem-line device: TXD/RXD/CBUS all
  unconnected. Proper USB-C device signaling (5.1 k CC pulldowns), VBUS through ferrite +
  Schottky, 3.6 V zeners + 27 Ω + 47 p on the data pair. FTDI part ⇒ the 1 ms latency-timer
  setting (§4.1.1) applies on both OSes.
- **Key input (J1, 3.5 mm jack) — protected, ground-referenced:** tip → 0.1 µ shunt (RF /
  contact bounce) → 1 k series → 4.7 V zener clamp → 1 k series → CTS̄. No external pull-up
  needed: the FT-X's internal pull-up holds CTS̄ deasserted when open, so key-closed-to-
  sleeve asserts — the §4.1 polarity convention implemented by the chip itself, and an
  unplugged cable reads open, not floating.
- **Inhibit output (J3, 3.5 mm jack) — opto-isolated and floating:** RTS̄ sinks the LED of
  U3 (marked AT3H4X — PC817-class phototransistor opto, SSOP-4) through 1 k from 5 V, so
  the output contact closes when the host asserts RTS. Collector → tip, emitter → ring: a
  floating switch, DC-isolated from USB ground (Schottky across the pair for reverse
  protection, 0.1 µ bypasses to ground for RF). Tip-to-ring keying stays fully floating;
  tip-to-sleeve gives a conventional ground-referenced PTT.
- 0402 passives with LCSC part numbers throughout — designed for board-house assembly, so
  "replicate the fleet standard" means *order more*, not *solder more*. **First production
  run: 10 boards on order (2026-07)** — hardware for the §9.2 latency bench and the fleet.
- **The dongle self-identifies over USB:** the FT230X EEPROM is reprogrammed (FT_PROG) with
  manufacturer **"FTDI WA1HCO"**, so software can find the Keyline board among a seat's
  serial ports by descriptor instead of asking a human to pick a COM port. WSJT-X's port
  picker can highlight it, the Key agent can auto-select its CTS source, and the setup
  agent's readiness check can verify "Keyline dongle present" — the §11.2 zero-config
  posture extended to *which port*, the one serial question that was still left to a human.
- BOM identity resolved: U3 (schematic value "AT3H4X", from the chip marking) is an
  **Everlight EL3H4** — SSOP-4 phototransistor optocoupler, marking "3H4"; 3.75 kV
  isolation, 80 V output, CTR 20–300 %, 6–8 µs switching (microseconds against the 1 ms
  USB budget). Datasheet filed in the SO4R_Interlock_V2 `Hardware/Documents/` folder.

Note the isolation philosophy (deliberate, and the reverse of an earlier guess in this doc):
the **output** is isolated because it crosses into the radio's PTT/keying domain; the
**input** is protection-only (series R + zener + RC) because the KEY sense is a local
contact closure. One board serves both seat roles: at a WSJT-X seat, J3 keys the radio
(RTS→PTT) and J1 senses a co-located KEY line; at an SSB/CW seat, J1 feeds the Key agent's
CTS watch and J3 is available to drive a radio's hardware inhibit input.

### 4.2 UDP inhibit datagram (agent on the SSB/CW radio's PC)

The §3.4.1 announcement path, consumed directly by the patched WSJT-X (or by the seat agent —
§6): a small datagram `{band, station, ttl_ms, seq}` (§11.3 — one message type; release
is `ttl_ms: 0`) sent on the
LAN at every transition, **plus a keepalive repeat while keyed** (e.g. every 200 ms) and a
periodic idle heartbeat (e.g. every 2 s).

| Hop | Typical | Notes |
|-----|--------:|-------|
| CTS edge at SSB/CW PC | 1–16 ms | Same USB-serial physics as §4.1, at the far end |
| Agent → UDP → LAN → WSJT-X PC | ~1 ms | Wired L2; same class as plane A |
| Socket → INHIBIT flip in WSJT-X | <1 ms–tens of ms | Depends on where the receiver lives relative to the GUI event loop — §5 places it off the GUI thread precisely to keep this sub-ms |

Loss semantics (the deadman design): **keyed state expires** if neither a release (`ttl_ms: 0`) nor a
keepalive arrives within N × keepalive period (e.g. 3 × 200 ms = 600 ms) — so a crashed agent
cannot leave the band inhibited forever. The expiry is **logged and alarmed** (it means the
interlock briefly ran open-loop). Idle-heartbeat loss for >T seconds ⇒ source marked degraded:
WSJT-X keeps operating, WIMS status shows the interlock is unprotected on that band — the
station chooses policy (keep going vs. hold digital) rather than the code choosing silently.

Assert is edge-triggered by the first hold datagram (`ttl_ms` > 0); the 200 ms keepalive only maintains
it. So the assert-path latency is the sum above (worst ~20 ms cross-host, dominated by the far
end's USB latency timer — set to 1 ms it is ~3 ms).

### 4.3 Sources compose — two kinds, not N stations

`INHIBIT = local_CTS ∨ UDP_hold` — a seat may have both inputs (co-located SSB/CW wired
directly *and* a station announcing over UDP), and each is visible separately in
diagnostics. But **the UDP side is a single hold, not a per-station table** (decision
2026-08-02, per WA1HCO — simplified from an earlier per-station compose rule): every hold
datagram re-arms the one deadline and names the holder (last datagram wins); any valid
release opens the gate. **Multi-station arbitration is out of scope for the WSJT-X
thread.** A site that genuinely has more than one SSB/CW station feeding one seat solves
it on the SSB/CW side — OR the KEY lines in hardware (the SO4R interlock family exists
for exactly this) or run one Key agent sensing the combined line — so WSJT-X always sees
one logical inhibit source. Keeps the in-WSJT-X state to a single deadline and holder,
per the strict-simplicity rule (§11).

### 4.4 Fan-out: one Key agent, several WSJT-X inhibit inputs

One SSB/CW Key agent must control the inhibit inputs of every WSJT-X instance on its band
(three 6 m beam instances, FT8 + MSK pairs, a remote same-band site). Two candidate
transports:

**Unicast to an assigned list (recommended).** The Key agent holds a list of
`instance → ip:port` targets and sends each transition (and keepalive) to all of them. The
list is **assigned on the WIMS operations dashboard** ("assign WSJT-X inhibit inputs to
SSB/CW Key outputs") and pushed to the agent; the agent persists its last assignment so the
interlock survives a WIMS outage.

- Keeps the WSJT-X thread maximally dumb: *"obey any valid inhibit datagram arriving on my
  socket"* — no band logic, no station filtering, no assignment knowledge inside WSJT-X. That
  directly serves the minimal-states / minimal-misconfiguration requirement: the only way to
  mis-wire the interlock is in one visible place (the WIMS assignment screen), not in N
  per-seat configs.
- Unicast is robust on Windows and immune to IGMP-snooping pruning — the same reasoning that
  drove the Switchboard's unicast legs.
- Fan-out cost is nil at this scale (a handful of targets × a few datagrams per second).

**Multicast group (analyzed, not chosen).** All Key agents announce to one group; every
inhibit thread joins and must then decide which announcements concern it — which forces a
**band (or key-station) filter into every WSJT-X config**. That is exactly the distributed,
per-seat, silently-wrong-able configuration this design is trying to eliminate (a 144 SSB
key-down must not inhibit 50 MHz FT8, so an unfiltered dumb receiver is not an option on a
multicast transport). Multicast also reintroduces the §4.1-class Windows/IGMP folklore on the
most safety-critical packet in the system. Revisit only if assignment lists prove unwieldy.

Co-located special case: when the SSB/CW radio and a WSJT-X instance share one PC, the agent
still sends UDP to 127.0.0.1 — one mechanism, no special path (the loopback hop is
microseconds).

## 5. The gate thread — the only WSJT-X change

Inhibit does not care how WSJT-X works inside, and after §3 neither does this section: the
entire WSJT-X change is that a small **PTT gate thread** owns the serial PTT line. WSJT-X's
TX machinery — decision tick, sequencer, modulator, UI — is untouched and unaware.

```
  WSJT-X main loop ── TX intent (assert/release) ──►  ┌─────────────────────────┐
                                                      │  PTT gate thread        │
  Agent on SSB/CW PC ── UDP hold(ttl)/release(0) ───► │  (TimeCriticalPriority) │
                                                      │  RTS = intent ∧ ¬inhibit│
  Local KEY on CTS (§4.1, same port) ───────────────► └───────────┬─────────────┘
                                                                  │ RTS line, dedicated
                                                                  ▼ USB-serial port
                                                          radio PTT input (hard-wired)
```

Seat wiring premise: WSJT-X keys the radio via **RTS on a USB-serial port dedicated to PTT**
(the Keyline_Interface board, §4.1.2), separate from the CAT port; CAT handles frequency and
mode only.

**Design decision (2026-07-30): the gate thread *is* the serial-PTT path — not a second
one.** The patch reroutes the **existing DTR and RTS PTT methods** through the gate thread;
hamlib keeps only CAT (and VOX = None). One mechanism instead of two: every DTR/RTS user
exercises the gate code on every transmission with the gate open (behavior identical to
stock, minus the rig-thread latency traps — an improvement on its own merits, Appendix A);
no configuration exists in which serial PTT bypasses the gate; and the upstream story writes
itself — "faster, cleaner serial PTT" carries the gate into the base fork where it gets
tested and cannot be orphaned as a niche WIMS feature.

Properties of the gate:

- **Deterministic and fast:** UDP datagram (or local CTS edge) → gate thread wake → RTS
  flip: **~1–2 ms**, independent of everything else in the process. The RTS drop is the RF
  kill — a hard-wired PTT release unkeys the radio in milliseconds regardless of what the
  audio buffer is doing (the same event as releasing a mic PTT mid-syllable; the rig's own
  sequencer drops drive before opening its relay).
- **A level, computed continuously:** `RTS = intent ∧ ¬inhibit` re-evaluates on every input
  edge; no command ordering to get wrong, nothing to unwind.

Integration, in full (why this must be part of WSJT-X, not a sidecar: TX *intent* exists
only in-process — the only out-of-process equivalent is an analog gate in the PTT cable,
§6):

1. **PTT routing:** with PTT method DTR/RTS, `transceiver_ptt()`'s intent goes to the gate
   thread instead of the hamlib rig thread (the rig object keeps `ptt_type=None`, as with
   VOX). This is the **only** touch on existing code.
2. **PTT confirmation = intent accepted, not line state.** WSJT-X starts audio only after
   PTT is confirmed; the gate thread acknowledges *immediately and unconditionally* —
   inhibited or not — so cycles, audio, and sequencing proceed identically in every case.
   The physical line is the only thing inhibit ever changes (§3).
3. **Nothing else.** No checks in the TX decision path, no abort routine, no timer
   cancellations, no Tune special case (a Tune while inhibited simply doesn't radiate, and
   the badge says why).
4. Deadman and telemetry are timers on the gate thread itself (hang lives in the Key agent,
   §3); state changes go to the GUI thread for the badge and InhibitStatus only — nothing on
   the fast path waits for the GUI.

An earlier iteration gated WSJT-X's *decisions* instead — an intent check in the TX start
condition, a fast abort routine, timer cancellations, a withheld PTT confirmation. All
rejected on the §3 principle: each touch point teaches WSJT-X about inhibit and turns "the
radio didn't radiate" into "the program behaved differently." The supporting source
analysis (where TX starts and stops, why asking WSJT-X to stop costs 100–600 ms of jitter,
and confirmation that stock WSJT-X reads no modem-status lines) is preserved in
**Appendix A** — the design depends on none of it beyond two conclusions: WSJT-X's own stop
paths are too slow and jittery to be the interlock, and the serial line is the one place a
deterministic gate can live.

Cost, stated plainly: **one USB-serial dongle and one PTT wire per WSJT-X seat**, and a
departure from the fleet's current CAT-PTT convention (networking doc §3.3.3 sets
`PTT Method = CAT` via wfview; Flex seats key via SmartSDR CAT). That is a real wiring and
documentation change — but hard PTT lines are long-standing contest-station discipline, the
determinism benefits normal keying too, and the same RCA/phono PTT inputs exist on the
IC-9700 (SEND) and Flex (PTT in) back panels. Seats that cannot take the wire are covered by
the §3.4.1 external audio mute until they can.

## 6. Actuator survey — where the RF actually stops

The gate can act at several depths; they are not exclusive. Layered view, fastest-certain
last:

| Layer | Mechanism | Kills RF in | Caveats |
|-------|-----------|-------------|---------|
| **PTT gate thread (§5, preferred)** | Dedicated-port RTS = intent ∧ ¬inhibit; UDP/CTS edge flips the line directly | **~1–2 ms to line drop + rig unkey (ms), deterministic** — no GUI tick, no rig thread, no audio buffer in the path; WSJT-X unaware (§3) | Requires the RTS-PTT seat wiring (dongle + PTT line per seat) and the WSJT-X patch |
| §3.4.1 Layer-2 external audio mute | OS volume / VCA outside WSJT-X | 2–5 ms (analog) / 10–30 ms (software) | The fallback for **CAT-PTT seats** (no line to own) and for unpatched WSJT-X; also defense-in-depth behind the gate. Equally invisible to WSJT-X |
| Radio hardware TX-inhibit input | Rig's interlock pin wired to the SSB/CW PTT | Assert mid-over: **rig-dependent, µs–ms where it acts at all** | Fewer real candidates than assumed (§3 survey, 2026-08-02): **Elecraft** works but **latches mid-key** (K2TR — release does not resume RF until PTT cycles, so a brief burst kills the rest of that WSJT-X cycle; recovery at the next cycle's fresh PTT); **Flex TX REQ is an initiation gate only** — sampled at TX start, ignored during transmission, so it **cannot stop an in-progress over** and is unsuitable as the fast-stop layer; **Kenwood TS-890 has no such input** (its "TX Inhibit" menu is a receive-only mode); Icom/Yaesu seats vary and many rigs have none. Where a real one exists it needs no computer at all — but **bench-verify assert-mid-key and latch-vs-level per rig (§9.3) before assigning this layer any role** |

Recommendation: the **§5 gate thread is the primary** wherever the seat can take the RTS
wire; **CAT-PTT seats use the external audio mute** until rewired; the **analog backstop
stays** for defense-in-depth; **hardware inhibit inputs are wired wherever the rig offers
one**. Note what all four layers share: they act on the emission path — PTT line, TX audio,
or the rig's own interlock — and none of them touches WSJT-X's transmit logic. That is the
§3 principle expressed as an architecture rule: *inhibit lives between WSJT-X and the
antenna, never inside WSJT-X's decisions.*

## 7. Release policy (the missing half of §3.4.1)

Explicit rules, replacing any implied "enable at key-up":

1. **Release restores the gate, never initiates TX.** No message, no re-arm, no Reply is sent
   because an inhibit ended.
2. **Hang time** (§3) absorbs CW keying trains and quick S&P bursts before the gate reopens.
3. **WSJT-X's sequencer owns resumption — because it never stopped.** RF reappears the
   instant the gate reopens while WSJT-X is asserting intent (§3): mid-cycle, that is the
   punctured waveform resuming; across cycles, it is the auto-sequence's own retry — normal
   attended operation continuing, since the operator armed it and the gate merely masked
   the radio. If the sequence expired during a long inhibit, resumption requires the normal
   human action (local UI or leased click-to-work).
4. **WIMS's preventive gate stays closed until clear.** Mechanism 1 keeps declining new
   click-to-work on the band while any inhibit source is asserted or in hang time; the
   operations dashboard shows band-claimed state and the reason.
5. **Long-occupancy bands** (SSB/CW run mode): after INHIBIT has been continuously asserted
   for T_run (e.g. 60 s), WIMS should *suggest* the digital operator subscribe elsewhere —
   policy/UX, not mechanism.

Action item carried out of this doc: amend design §3.4.1 to state rule 1–3 (it currently
specifies key-down only), and correct the "Halt … then re-enable" implication anywhere it
appears — there is no UDP enable.

## 8. Failure modes

| Failure | Behavior | Rationale |
|---------|----------|-----------|
| PTT/KEY dongle unplugged | **PTT output disappears with the KEY input** (same port, §4.1) — the seat physically cannot transmit; alarm raised | Fail-safe by wiring, not by code: a missing interlock also means a missing PTT |
| UDP agent crashes while keyed | Keyed state expires after deadman (~600 ms) + alarm | Can't leave the band dead forever on a crash; expiry is visible |
| UDP agent silent (idle heartbeat lost) | Source marked degraded; TX continues; WIMS status red on that band | Choosing to hold digital is station policy, surfaced not defaulted |
| WSJT-X patch absent (stock binary on a seat) | §3.4.1 external mute + Halt path unchanged | The patch is an upgrade, not a new dependency |
| Both sources configured, one fails | OR semantics keep the surviving source authoritative | |
| Inhibit chatters (bad hang tuning) | FT8 impact bounded — puncture bench: ≤1.6 s total gap ≈ free | Protocol margin is the safety net, not the design target |

## 9. Test plan

1. **Unit (no radio):** gate and Key-agent state machines — assert/release through each §3
   scenario; agent-side hang against scripted CW keying trains (dit-speed edge streams);
   deadman expiry and alarm paths. Same self-running style as `tests/unit/`.
   *(Done — `tests/unit/test_inhibit.py`, 15 tests, plus the `inhibit_spike.py` selftest.)*
2. **Latency bench (no RF):** loopback rig — GPIO/serial toggles CTS, patched WSJT-X (or the
   watcher module standalone) timestamps INHIBIT flip; measure distribution vs latency-timer
   setting (1 ms vs 16 ms) on Linux and Windows. Same for the UDP path with the agent on a
   second host. Publish the measured budget table into §6.
3. **RF-path verification (dummy load):** scope or SDR on the dummy load; key a function
   generator as "SSB PTT"; measure key-down → RF-gone for each actuator layer on each seat
   type (DTR/RTS, wfview CAT, Flex CAT, VOX). This replaces the estimates in §6 with numbers.
   **Include release semantics per rig** (K2TR's K3 finding, §3): assert inhibit mid-key,
   release it with PTT still held — does RF resume (level) or stay off until PTT cycles
   (latch)? Record latch-vs-level in the §6 table per rig; the fleet's hardware-inhibit
   wiring (§6 layer 3) depends on the answer.
4. **Decode-impact regression:** already done in principle — `testbed/tx_interrupt_bench.py`
   (gaps ≤1.6 s free; middle-Costas loss matters only ≥2.4 s near the floor). Re-run with the
   actual inhibit envelope (PTT drop, no audio ramp) if the RF envelope differs materially
   from the audio-puncture model.
5. **Live interlock drill:** two stations on a quiet band segment, scripted SSB bursts against
   a running FT8 QSO; verify QSO survival for sub-second bursts and correct non-resumption
   for long occupancy.

## 10. Build plan (proposed)

1. Standalone **inhibit watcher module** (CTS + UDP deadman + hang time, pure logic separated
   from I/O) — testable without WSJT-X; lives in the WIMS repo; the seat agent can host it
   immediately to drive the §3.4.1 external mute (value before any WSJT-X patch ships).
2. **WSJT-X patch** in the improved_PLUS build
   ([wsjtx-improved-wims](https://github.com/wa1hco/wsjtx-improved-wims) `feature/tx-inhibit`):
   the §5 PTT gate thread — existing DTR/RTS PTT methods rerouted through it, immediate
   intent-acknowledge handshake, zero new settings (§11.2) — plus the InhibitStatus
   announcement and the status-bar badge ("TX INHIBITED — 144 SSB"). Nothing in WSJT-X's
   TX decision code changes (§3, §5). Seats still on CAT PTT are covered by the §3.4.1
   external audio mute.
   2a. **Seat wiring standard update** (networking doc §3.3): one USB-serial PTT dongle per
   WSJT-X seat, RTS → radio PTT input (IC-9700 SEND, Flex PTT-in); CAT becomes
   frequency/mode only.
   2b. **Prebuilt executables in the fork repo — a requirement, not a nicety.** Each tagged
   release of [wsjtx-improved-wims](https://github.com/wa1hco/wsjtx-improved-wims) ships a
   **Windows installer** and an **Ubuntu/Debian `.deb`** as GitHub release artifacts, built
   by CI (GitHub Actions) so a rebase onto a new upstream improved_PLUS drop re-produces
   both without hand work. The tree already carries upstream's packaging plumbing — the
   Inno Setup `.iss` scripts for Windows and CMake/CPack for the `.deb` — so this is CI
   wiring, not new packaging. Why required: fleet seats and testers install a patched
   WSJT-X **without a Qt/Fortran toolchain** (a Windows source build is a JTSDK project in
   itself); the §11.7 five-minute netcat demo only works if trying the build is also five
   minutes; and the same artifacts are what the upstream offer (§10.5) points reviewers at.
3. **WIMS integration:** inhibit state onto the state contract (per instance: which source,
   since when, hang remaining) → operations dashboard band state + Mechanism-1 gate input.
4. **Design-doc amendments:** §3.4.1 release policy (per §7), Halt/enable correction.
5. Offer the patch upstream to the improved fork (same channel as the port-2333 letter — it
   is the same story: contest-grade multi-station operation needs a gate, not a message).

## 11. Inhibit-thread implementation plan (for review before coding)

The concrete plan for the in-WSJT-X piece (function #8 of the design-doc partition table).
Guiding requirement, verbatim: *as basic and simple as possible, minimal states, minimal
possibility of misconfiguration, no effect on familiar WSJT-X operation if not used —
regardless of whether it is Enabled.*

### 11.1 States — exactly two

```
            datagram, ttl > 0 (any valid sender)
   OPEN  ───────────────────────────────────►  INHIBITED(deadline)
    ▲                                                │
    │  datagram, ttl = 0 (hang already applied       │ every ttl>0 datagram
    │  by the Key agent, §3),                        │ re-arms deadline = now + ttl
    │  OR deadline expires (deadman, alarmed)        │
    └────────────────────────────────────────────────┘
```

No persistent state, nothing survives a restart, no hysteresis (that is the Key agent's
job, §3), no configuration of *who* may inhibit — the gate defaults **OPEN**, asserts only
on receipt of valid datagrams, and self-clears. A gate that never receives a datagram
changes nothing about WSJT-X behavior; that is the "no effect if unused" guarantee, held by
construction rather than by testing.

### 11.2 Settings — none (a deliberate zero)

Strict-simplicity rule (adopted 2026-07-30): **anything in WSJT-X beyond an enable checkbox
is suspect — and even the checkbox proved unnecessary.** Everything that looked like a
setting moved out:

| Was going to be a setting | Where it went |
|---|---|
| Enable checkbox | **Always on.** The listener binds at startup, costs nothing when silent, and fail direction is safe (inhibit only ever *stops* TX and self-clears by TTL). The only control is a **Hold "TX inhibit test" menu item** that ignores datagrams until restart — for bench testing, never a config state |
| UDP port | **Auto.** Bind 22372 if free, else an ephemeral port; the actual port is announced in InhibitStatus (§11.4), so nothing and nobody needs to know it in advance. Multi-instance hosts just work — second instance lands on an ephemeral port, announced the same way. **Shown read-only in Settings → Network** ("TX inhibit input: listening on UDP 22372") so the operator sees what is going on without memorizing ports — information, not a control |
| Hang time | **Key agent** (§3) — the per-operator knob lives at the SSB/CW seat. The local CTS input uses the same logic with compiled-in defaults (§4.1) |
| Local KEY input port | **None — it is the PTT port's own CTS pin, by convention** (§4.1). No port to pick, no polarity switch; a seat needing anything fancier runs the Key agent |

Trust model, stated: any LAN host can inhibit any WSJT-X. On a cooperative contest LAN this
is the same trust already extended to "Accept UDP requests," and the failure direction is
RX, alarmed and self-clearing. The complexity this deletes from every seat is the point —
if WIMS or the Key agent must carry more algorithm to keep WSJT-X state-free, that is the
right trade.

The PTT side (§5) adds no inhibit-specific settings either: the existing DTR/RTS PTT
method selection now routes through the gate thread — same screens, same fields as stock
WSJT-X.

### 11.3 Datagram format

Compact single-datagram JSON (debuggable with tcpdump/netcat; size is irrelevant at this
rate, and parsing cost is nanoseconds against a millisecond budget):

```json
{"tx_inhibit": 1, "ttl_ms": 600,
 "station": "ROY-222-SSB", "band": "222", "seq": 4711}
```

- `tx_inhibit: 1` — magic + version; anything else is ignored.
- `ttl_ms` — **the entire protocol is this one field** (decision 2026-08-02, per WA1HCO —
  eliminates the clear code path in WSJT-X). Every message means *"inhibit this band for
  ttl_ms"*: a fresh hold or keepalive re-arms `deadline = now + ttl_ms`; **release is
  `ttl_ms: 0`** — the same message meaning "inhibit for zero more milliseconds," which
  drops the hold at receipt. There is no `state` field, no message-type dispatch: the
  gate's handler is one deadline assignment. (An earlier draft had `state: keyed|clear`;
  releases are counted separately from deadman expiries because a release never enters
  the deadline, so a lapsed *nonzero* deadline remains a pure keepalive-loss alarm. The
  gate holds exactly one deadline and one holder name — no per-station table, §4.3.)
- `station`/`band`: diagnostics and UI badge text only — **the thread makes no routing
  decision on them** (§4.4: routing lives in the Key agent's assignment list).
- `seq`: duplicate/reorder tolerance in diagnostics; not used for gating (gating is a level).

### 11.4 Discovery ("somehow", resolved)

The thread announces itself in-band on plane A: a new WSJT-X UDP message type
**InhibitStatus** (proposed type 18, above the current highest = 12–17 range check at build
time), emitted at heartbeat cadence, carrying
`{inhibit_port, gate_state, source_station (when inhibited), counters}`. Properties:

- WIMS learns *instance → (host, inhibit port)* passively, the same way it learns everything
  else about the fleet — no probing, no per-seat registration step. The assignment screen
  (§4.4) simply lists discovered inhibit inputs.
- **The announcement is what makes the zero-config port (§11.2) workable — and the Key agent
  consumes it directly.** Assignments are by stable **instance id** ("ROY-222-FT8"), not by
  address; the Key agent listens to plane A itself and resolves its assigned ids to live
  `ip:port` from each instance's own InhibitStatus. A WSJT-X restart onto a new ephemeral
  port heals within one announcement interval, with WIMS not in the loop — the interlock
  keeps working through a WIMS outage (only *changing* assignments needs the dashboard).
- Existing consumers are safe: WSJT-X-protocol servers skip unknown message types (verify on
  N1MM + GridTracker in the §11.6 bench — regression risk is low but must be shown, not
  assumed).
- The same message doubles as live telemetry: the ops dashboard shows gate state per
  instance in real time, and while a hold is active the badge names the SSB/CW station holding the band.

**Display philosophy (revised 2026-07-31): the seat answers "why is the radio not
transmitting"; WIMS answers "what is wrong with the plumbing."** In WSJT-X itself the
inhibit UI is the **badge and nothing else** — large, unmissable, one line: "TX INHIBITED —
held by ROY-222-SSB". A mechanism this small must be bullet-proof enough to need no local
debugging surface; a diagnostics popup at the seat would advertise expected failure. The
counters and per-source ages (`hold_rx / release_rx / expiries / invalid`) therefore live
**only in the InhibitStatus datagram**, where the WIMS setup/status pages do integration
triage (counters flat = firewall/wrong target; `expiries` climbing = keepalive loss;
`invalid` climbing = version mismatch; permanent local-KEY badge = stuck line). One
addition at the seat, information not control: a **read-only line in Settings → Network**
— "TX inhibit input: listening on UDP 22372" — so the operator never has to remember the
port (§11.2's zero-settings posture is unchanged: there is nothing to click).

### 11.5 Thread structure inside WSJT-X

One new class (**`PttGate`** — it is the gate on the PTT line; an earlier draft's
`TxInhibitGate` said the same thing twice, since gating *is* the inhibit), one new thread,
following the existing worker-thread
patterns (`m_audioThread`, `transceiver_thread_`):

- Owns: the UDP socket (always bound — 22372 or ephemeral, §11.2), the deadman QTimer, the
  INHIBIT atomic, and the serial PTT port — **all DTR/RTS PTT routes through this thread**
  (§5), so it owns the port stock WSJT-X would have handed to hamlib, including that
  port's **CTS pin as the local KEY input** (§4.1, fixed-default scheduler logic in-thread).
- Emits (queued, to GUI thread): `inhibitChanged(bool, QString source)` for the UI badge
  and the InhibitStatus announcements — presentation only, never behavior (§3). Nothing on
  the fast path waits for the GUI.
- Touches existing code in exactly **one** place: the PTT-method routing (existing DTR/RTS
  values redirected to the gate thread instead of hamlib, with immediate intent-acknowledge
  as the confirmation — §5). No changes to `guiUpdate()`, the sequencer, the modulator,
  or any TX decision code. Everything else is additive.

### 11.6 Prototype sequence (test before integrate)

1. **Spike, no WSJT-X (days):** two small standalone programs in the WIMS repo —
   `key_agent_sim` (reads CTS or keyboard, emits §11.3 datagrams to a target list) and
   `inhibit_gate_sim` (binds 22372, drives RTS on a second dongle, implements §11.1 exactly).
   Scope on the two serial lines measures the full UDP path latency distribution and
   validates the deadman/hang logic against scripted CW keying. The gate logic is written as
   a pure, WSJT-X-independent module so the patch later transplants it, not reimplements it.
2. **Fork patch (the prototype for testing):** `PttGate` + PTT rerouting +
   InhibitStatus + badge, built in the improved_PLUS tree (build infrastructure present).
   **Native code, native tools:** this is a rewrite in WSJT-X's own idiom — C++17/Qt6 in
   the fork's CMake tree, its worker-thread and UDP-message patterns (§11.5) — with the
   WIMS Python serving as executable specification only (its 23 unit tests define the
   semantics; no Python ships in or near WSJT-X). Platform modem-line code (`TIOCMIWAIT`
   / `WaitCommEvent`) is the one part Qt does not cover (§4.1.1).
   Bench: WSJT-X transmitting into a dummy load / audio loopback, `key_agent_sim` firing
   bursts — verify puncture-and-resume on the air with an SDR, N1MM/GridTracker unaffected
   by message type 18, and the §9.2 latency numbers on the real thread.
3. **Real Key agent** (grows from `key_agent_sim` into a `wims.agent` role: CTS watcher +
   assignment list from the dashboard + persistence), then the WIMS assignment UI (#5 in the
   design-doc function table).

Order rationale: step 1 de-risks every design decision that does not require WSJT-X (format,
deadman, hang, latency) with an afternoon's hardware; step 2 is then a mechanical transplant
whose only new risks are Qt-threading and settings plumbing.

### 11.7 Upstream developer story — least effort for the maintainers, least risk to stock operation

For the improved-fork maintainers the patch must be verifiable **with no WIMS, no Key agent,
and no extra hardware** — and its regression surface must be small enough to reason about in
one sitting. Both are design properties, stated here so the upstream offer (§10.5) can lead
with them:

1. **Test with two shell one-liners.** The §11.3 datagram is plain JSON on UDP, so any
   developer can exercise the whole feature from a terminal against a WSJT-X transmitting
   into a dummy load / audio loopback:

   ```
   echo '{"tx_inhibit":1,"ttl_ms":5000,"station":"BENCH","band":"144","seq":1}' | nc -u -w0 127.0.0.1 22372
   echo '{"tx_inhibit":1,"ttl_ms":0,"station":"BENCH","band":"144","seq":2}' | nc -u -w0 127.0.0.1 22372
   ```

   Expected: badge on, RF stops within ms, WSJT-X UI carries on "transmitting"; the `ttl_ms: 0` release (or
   just waiting out the TTL — which also proves the deadman + its alarm) → badge off, RF
   resumes mid-waveform. That is the complete acceptance demo, plus `tcpdump`/`nc -lu` to
   watch InhibitStatus. The richer harness (scripted CW keying trains, latency selftest,
   deadman scenarios) is `testbed/inhibit_spike.py` in the WIMS repo — also the **reference
   implementation**: its unit-tested Python `InhibitGate` defines the semantics the C++
   transplant must match, test case by test case.

2. **Risk surface is one path, and it is the most-exercised path.** Everything in the patch
   is additive (new thread, new message type, badge) except the single reroute: DTR/RTS PTT
   goes through the gate thread instead of hamlib. There is no configuration in which the
   gate is half-engaged: seats using CAT/VOX PTT are untouched; seats using DTR/RTS exercise
   the gate code **on every transmission with the gate open** — so any regression in the
   reroute shows up immediately in ordinary use, not in a rare interlock corner. The
   "no effect if unused" guarantee is §11.1 by construction (default OPEN, no persistence,
   nothing to configure), not a promise that needs a test matrix.

3. **Bench isolation without settings:** the Hold "TX inhibit test" menu item (§11.2) ignores
   datagrams until restart, for benching a seat on a hostile LAN; the InhibitStatus counters
   (§11.4) give a maintainer the same triage data WIMS uses — on the wire, not on the screen.

4. **House style, neutral naming.** The patch must read as if the fork's own maintainers
   wrote it: match the conventions of each file touched (Qt naming, member style, the
   Network/ pimpl idiom, GPL headers), no reformatting of untouched lines, no new
   dependencies. And the feature is a **generic fast TX Inhibit — no WIMS reference
   anywhere**: not in code, class names, settings text, message names, or the wire protocol
   (the datagram magic is `tx_inhibit`; an earlier draft's `wims_inhibit` was renamed for
   exactly this reason). WIMS is one client of an open datagram interface that any station
   automation — N1MM, a foot switch on an Arduino, another logger — can drive equally.

The pitch to the list writes itself from 1–2 and the §3 prior art: *the TX Inhibit input
contest radios already have on the rear panel (K3 `CONFIG:TX INH`, Kenwood TX Inhibit,
Flex TX REQ), provided for the radio that lives in software — plus a faster, cleaner
serial-PTT path; testable in five minutes with netcat; inert unless someone sends it a
datagram.*


---

## Appendix A — WSJT-X 3.1.0 TX-path notes (patch-review anchors)

File:line anchors and measured numbers backing the §5 patch and the §2 latency claims.
improved_PLUS tree; `mainwindow.cpp` = `widgets/mainwindow.cpp`.

- **TX start:** single point of no return mainwindow.cpp:7810–7860 (`g_iptt` 0→1 +
  `transceiver_ptt(true)`), evaluated on the 100 ms `m_guiTimer` tick (:1009); `fTR < 0.75`
  permits late starts. JTDX's `m_enableTx` is folded into `m_auto` in this fork (:5539,
  :5602).
- **Audio start:** rig PTT confirmation (:12557–12566) → `ptt1Timer` = TxDelay (default
  0.2 s) → `startTx2()`; modulator pads 500 ms silence for FT8 (Modulator.cpp:75–105).
  Patch behavior: the gate thread acknowledges the PTT command immediately; no timer
  touched.
- **TX stop:** `m_btxok` cleared (:7864) → edge check next tick (:8226) → `stopTx()`
  (:8571): audio first, then `ptt0Timer` 200 ms → PTT down (:8585, :8591). UDP Halt with
  `auto_only=false`: **~210–400 ms to PTT-down measured**, >700 ms worst behind a rig poll;
  clears `m_auto`, `m_bCallingCQ`, `m_bAutoReply`. `auto_only=true` only unchecks Enable Tx
  and lets the cycle finish. Watchdog (:14157) stops same-tick + 200 ms.
- **Rig-thread traps removed from serial PTT by the gate:** 500 ms blocking CAT poll on the
  same thread (PollingTransceiver.cpp:57); `TransceiverBase::set()` sleeps 100 ms after
  each PTT change (TransceiverBase.cpp:142, :186); all PTT methods funnel through
  `rig_set_ptt()` (HamlibTransceiver.cpp:1282).
- **Audio stop:** `Modulator::stop()` → `m_stream->reset()` discards the queued buffer
  (soundout.cpp:144); driver residual ~10–50 ms, bounded by `WSJT_TX_AUDIO_BUFFER_FRAMES`
  (mainwindow.cpp:313, :599). Relevant only to the §3.4.1 external-mute backstop — the gate
  never touches audio.
- **No modem-status input exists in stock code** (no CTS/DSR/DCD read anywhere; QSerialPort
  used only to enumerate port names) — the gate thread's CTS input (§4.1) is new code, not
  a modification.
