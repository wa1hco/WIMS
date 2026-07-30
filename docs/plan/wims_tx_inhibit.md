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

---

## 1. Scenario and requirement

One band, two transmitters, one rule:

- A WSJT-X seat: its own radio, decoding continuously, making contacts that the WSJT-X
  operator enables (locally or via WIMS click-to-work). FT8/MSK144 cycles run on the mode's
  clock.
- An SSB/CW station on the **same band**, in run or S&P, whose transmissions have **priority**
  under the one-signal-per-band contest rule.

Requirement: when the SSB/CW operator keys, any WSJT-X emission on that band must stop — and
must not start — until the band is theirs again. The stop must be fast enough that the overlap
is negligible (target: ≤10 ms from key-down to RF gone, per §3.4.1). The mechanism must work:

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
3. **It is slow to take effect.** Traced through the source (§5.2): a UDP Halt rides the GUI
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

One boolean per WSJT-X instance: **INHIBIT**. Sources (§4) are OR-ed. Semantics:

| Situation | INHIBIT asserted | INHIBIT released |
|-----------|------------------|------------------|
| Idle / RX | TX may not start. Sequencer, decoder, operator UI all run normally; an operator click (local or Reply) queues normally but emission is suppressed until clear | No effect — release never initiates anything |
| TX pending / cycle boundary | The **intent gate** (§5.4a) holds the start. Not a cancellation: the start condition re-evaluates every 100 ms tick, and WSJT-X natively allows **late starts up to 75 % into the period** — so a release early enough in the period starts the transmission late *in the same period*, symbol-aligned (a leading puncture) | If released before the 75 % point: late start, same period. Later: next period |
| TX in progress | **Puncture mode (RTS-gate seats, default):** only the RTS line is masked (~1–2 ms); **the modulator keeps running** — WSJT-X's internal state doesn't change at all, and the waveform stays on the symbol clock. CAT-PTT fallback seats can't do this (audio is the kill lever, §5.4b), so there the cycle is lost. Either way QSO/sequencer state survives, unlike Halt Tx | **Puncture mode: RF resumes immediately, mid-waveform, same period** — the emitted signal has a gap exactly like the bench-tested punctures (§below). CAT-PTT seats: next period |

**Hang time (release hysteresis) — implemented in the Key agent, not in WSJT-X.** CW keying
is a stream of edges milliseconds apart; the inhibit must not chatter — and RF between an
SSB/CW operator's dits or syllables would still violate the one-signal rule in spirit. The
**Key agent** holds the band: it keeps sending `keyed` keepalives until its input has been
continuously clear for the hang time (default **0.5 s**, range 0.2–5 s, tuned per SSB/CW
operator style like a VOX delay), then sends `clear`. The WSJT-X gate needs **no hysteresis
of its own** — it obeys `keyed`/`clear` and expires by TTL, nothing more. This puts the
per-operator tuning knob at the SSB/CW seat where the operating style is, and keeps WSJT-X
state-free (per the strict-simplicity rule, §11). Assert is always immediate. The trade is
unchanged: hang time adds directly to resume latency in puncture mode, and every added
second of gap spends FT8's measured puncture margin (§2 item 1) — hence a short default.

**Fail-safe direction.** Wire/agent failure must not silently un-inhibit *or* permanently kill
the band; the two failure directions get different treatments per source (§4). The invariant:
**a failed inhibit source is loudly visible** (WSJT-X UI badge + WIMS status), never silent.

**What Inhibit is not:** it is not an operator-facing enable/disable (that remains Enable Tx /
Halt Tx in the WSJT-X UI), not a WIMS lease mechanism (§4.5 of the design), and not a
replacement for the preventive gate at TX-initiate time (Mechanism 1) — WIMS still declines to
*start* work on a claimed band. Inhibit is the last, fastest layer.

## 4. Inhibit sources and their latency

### 4.1 Local CTS input (SSB/CW PTT wired to a USB-serial control line)

The SSB/CW PTT line (or a relay contact across it) drives the **CTS** pin of a cheap
USB-serial dongle on the WSJT-X PC. WSJT-X (patched) watches CTS edges.

Latency facts to design around:

| Hop | Typical | Notes |
|-----|--------:|-------|
| PTT contact → CTS pin | ~0 | Wire |
| USB-serial reports modem-status change | **1–16 ms** | FTDI parts report status at the *latency timer* interval — **default 16 ms, set to 1 ms** (sysfs `latency_timer` on Linux, FTDI driver property page on Windows). CP210x/CH34x similar ballpark. This is the dominant term and it is configurable. |
| OS wakes the watcher | <1 ms | Linux: blocking `TIOCMIWAIT` ioctl (edge-triggered wait, no polling). Windows: `WaitCommEvent(EV_CTS)`. Both give an event-driven thread, not a poll loop. |

Design: a dedicated watcher thread per configured port; assert/release INHIBIT atomically;
thread death or port disappearance ⇒ **assert INHIBIT + alarm** (fail toward the contest rule;
a missing wire must be noticed, not operated through).

### 4.2 UDP inhibit datagram (agent on the SSB/CW radio's PC)

The §3.4.1 announcement path, consumed directly by the patched WSJT-X (or by the seat agent —
§6): a small datagram `{band, station_id, keyed|clear, seq, monotonic_ts}` multicast on the
LAN at every transition, **plus a keepalive repeat while keyed** (e.g. every 200 ms) and a
periodic idle heartbeat (e.g. every 2 s).

| Hop | Typical | Notes |
|-----|--------:|-------|
| CTS edge at SSB/CW PC | 1–16 ms | Same USB-serial physics as §4.1, at the far end |
| Agent → UDP → LAN → WSJT-X PC | ~1 ms | Wired L2; same class as plane A |
| Socket → INHIBIT flip in WSJT-X | <1 ms–tens of ms | Depends on where the receiver lives relative to the GUI event loop — §5 places it off the GUI thread precisely to keep this sub-ms |

Loss semantics (the deadman design): **keyed state expires** if neither a `clear` nor a
keepalive arrives within N × keepalive period (e.g. 3 × 200 ms = 600 ms) — so a crashed agent
cannot leave the band inhibited forever. The expiry is **logged and alarmed** (it means the
interlock briefly ran open-loop). Idle-heartbeat loss for >T seconds ⇒ source marked degraded:
WSJT-X keeps operating, WIMS status shows the interlock is unprotected on that band — the
station chooses policy (keep going vs. hold digital) rather than the code choosing silently.

Assert is edge-triggered by the first `keyed` datagram; the 200 ms keepalive only maintains
it. So the assert-path latency is the sum above (worst ~20 ms cross-host, dominated by the far
end's USB latency timer — set to 1 ms it is ~3 ms).

### 4.3 Sources compose

`INHIBIT = local_CTS ∨ any_unexpired_UDP_keyed(band)` — a seat may have both (co-located
SSB/CW wired directly *and* remote stations announcing over UDP). Each source is visible
separately in diagnostics.

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

## 5. WSJT-X transmit-enable path and patch points

Source review of the improved_PLUS 3.1.0 tree (paths relative to the extracted source;
`mainwindow.cpp` = `widgets/mainwindow.cpp`).

### 5.1 How a transmission starts

Everything is paced by a **100 ms GUI-thread timer** (`m_guiTimer`, mainwindow.cpp:1009 —
"Don't change the 100 ms!"). Each `guiUpdate()` tick computes `m_bTxTime` from the T/R clock
(:7720; `m_tune` overrides it, :7730) and reaches the **single point of no return** at
:7810–7860:

```cpp
if(g_iptt==0 and ((m_bTxTime and (fTR < 0.75) and (msgLength>0)) or m_tune)) {
  g_iptt = 1; ... m_config.transceiver_ptt (true); m_tx_when_ready = true;
```

This is the only place PTT is asserted for a normal cycle. Note `fTR < 0.75`: late starts are
allowed up to 75 % into the period, so a start can happen on *any* tick, not just at t=0.
"Enable Tx" is just `m_auto`; there is no separate TX-enable flag in this fork (JTDX's
`m_enableTx` was folded into `m_auto` — fork markers at :5539, :5602).

**Audio starts only after the rig confirms PTT**: the transceiver's update callback
(:12557–12566) starts `ptt1Timer` with the TxDelay (default **0.2 s**), which fires
`startTx2()` → the Modulator; the Modulator then pads with silence so FT8 tones begin
**500 ms** into the period (Modulator.cpp:75–105). Consequence: an inhibit landing in the
first ~0.5 s of a cycle can still prevent any RF even though PTT is already up — if it
cancels `ptt1Timer` / stops the modulator before tones start.

### 5.2 How a transmission stops (today)

- **Normal end:** `m_btxok` cleared at :7864 → next tick's edge check (:8226) calls
  `stopTx()` (:8571): audio stopped first, then `ptt0Timer.start(200)` drops PTT **200 ms
  later** (:8585, :8591). Sequencer state survives.
- **Halt Tx (UDP type 8 / Stop button):** the `auto_only` flag matters — `auto_only=true`
  only unchecks Enable Tx and **lets the current cycle finish**; `auto_only=false` clicks
  Stop (:680–688), which clears `m_btxok` and *waits for the next tick* to actually stop
  (:12408). It also destroys sequencer state: `m_auto`, `m_bCallingCQ`, `m_bAutoReply`, the
  wait/reply timers. Measured end-to-end for a UDP Halt: **~210–400 ms to PTT-down** (event
  loop + ≤100 ms tick + 200 ms ptt0Timer + CAT), worst case >700 ms if the rig-poll is in
  flight. This quantifies §2's "blunt and slow."
- **Watchdog:** `tx_watchdog(true)` (:14157) forces `m_bTxTime=false` and stops within the
  same tick + the 200 ms PTT delay.

### 5.3 The PTT plumbing and its latency traps

`transceiver_ptt()` (Configuration.cpp:5199) posts a queued command to a dedicated **rig
thread**. Three traps on that thread:

1. A **500 ms polling timer** (PollingTransceiver.cpp:57) does blocking serial CAT I/O on the
   same thread — a PTT command posted mid-poll waits for the poll to finish (10–100 ms).
2. `TransceiverBase::set()` sleeps **100 ms after** each PTT change (TransceiverBase.cpp:142,
   :186) — doesn't delay RF-off but blocks the next rig command.
3. All PTT methods funnel through one `rig_set_ptt()` (HamlibTransceiver.cpp:1282): hamlib
   dispatches CAT (~5–50 ms serial) vs DTR/RTS (~1 ms line flip) vs VOX (no-op — audio *is*
   the PTT).

The audio side is faster: Modulator and SoundOutput live on a `TimeCriticalPriority` audio
thread (mainwindow.cpp:592, :1077), and `Modulator::stop()` → `m_stream->reset()`
**discards the queued output buffer** (soundout.cpp:144) — residual RF is only what the
driver already owns (~10–50 ms with the default "let Qt decide" buffer; bounded by setting
`WSJT_TX_AUDIO_BUFFER_FRAMES`, mainwindow.cpp:313/599).

**Confirmed: WSJT-X reads no modem-status lines anywhere** (no CTS/DSR/DCD input exists;
QSerialPort is used only to enumerate port names). The CTS watcher is genuinely new code.

### 5.4 Patch points

**(a) Prevent a start — one-line gate at mainwindow.cpp:7810:** add `and !m_txInhibit` to the
point-of-no-return condition. Blocks PTT, audio, and QSO-state advance in one stroke with
nothing to unwind. This is the **intent gate**: a *hold*, not a cancellation — the condition
re-runs every 100 ms tick while `g_iptt==0`, and the native `fTR < 0.75` term means a release
up to 75 % into the period produces a **late start in the same period**, with the waveform
begun at the correct symbol offset (WSJT-X's normal late-start behavior — equivalent to a
leading puncture of the signal). Two side-doors need the same gate: **Tune** (bypasses `m_bTxTime`, :7730 —
inhibit must `stop_tuning()`) and the pending-audio window (**cancel `ptt1Timer`** if inhibit
asserts between PTT-up and audio start). Since starts only ever happen inside `guiUpdate()`,
prevention is race-free; the only exposure is a start already committed in the current tick,
which the abort path covers.

**(b) Abort in progress — a new `inhibitAbortTx()` that does NOT route through the existing
stop paths** (they cost ~300 ms of pure scheduling: ≤100 ms tick wait + 200 ms ptt0Timer).
In order:

1. Stop audio now: emit `endTransmitMessage` / `Modulator::stop()` — queued to the
   time-critical audio thread, buffer discarded. **RF gone in ~2–25 ms + driver residual.**
   On an SSB/data rig this alone silences the emission, faster than any PTT action; also the
   only lever that works on VOX seats.
2. Drop PTT now: call `m_config.transceiver_ptt(false)` directly, bypassing `ptt0Timer`.
   DTR/RTS ≈ 5–60 ms; CAT typically similar but can hide behind the 500 ms poll (worst
   100–600 ms) — which is why step 1 leads.
3. Minimal state cleanup only: `m_btxok=false; m_transmitting=false; g_iptt=0; monitor(true)`
   — **deliberately not** `on_stopTxButton_clicked()`, which would clear `m_auto` /
   `m_bCallingCQ` / `m_bAutoReply` and destroy the QSO context the gate exists to preserve
   (§3). The redundant edge at :8226 is harmless (edge-guarded).

**(c) Where the inhibit sources live:** a small watcher QObject on its **own**
`TimeCriticalPriority` thread (pattern already in the codebase: the audio thread and
`transceiver_thread_`), *not* on the GUI thread (MessageClient's socket lives there and
inherits waterfall/decode jitter — tens of ms) and *not* on the rig thread (blocks on CAT).
Linux: block in `ioctl(TIOCMIWAIT, TIOCM_CTS)` — sub-ms wake, zero polling. Windows:
`WaitCommEvent(EV_CTS)`. The UDP inhibit socket joins the same watcher thread. The watcher
emits a queued `inhibit_changed(bool)` into the GUI thread, which runs (a)/(b).

### 5.5 Preferred architecture: a dedicated PTT gate thread (RTS on its own serial port)

The (a)/(b) design above gates *decisions* in the GUI thread and still actuates PTT through
the existing plumbing. A stronger structure — adopted here as the preferred architecture —
moves **PTT actuation itself** into the fast thread and puts the AND-gate at the last
software point before the wire:

```
  WSJT-X main loop ── TX intent (assert/release) ──►  ┌─────────────────────────┐
                                                      │  PTT gate thread        │
  Agent on SSB/CW PC ── UDP keyed/clear/keepalive ──► │  (TimeCriticalPriority) │
                                                      │  RTS = intent ∧ ¬inhibit│
  Local CTS watcher (§4.1, optional) ───────────────► └───────────┬─────────────┘
                                                                  │ RTS line, dedicated
                                                                  ▼ USB-serial port
                                                          radio PTT input (hard-wired)
```

Seat wiring premise: WSJT-X keys the radio via **RTS on a USB-serial port dedicated to PTT**,
separate from the CAT port. CAT (direct or via wfview/rigctld) handles frequency/mode only.

Why this beats gating in the GUI thread:

- **The inhibit path never touches WSJT-X's slow machinery.** UDP datagram → gate thread
  wake → RTS flip: **~1–2 ms, deterministic**, independent of the 100 ms tick, the GUI event
  loop, and the rig thread entirely. All three latency traps of §5.3 (500 ms poll contention,
  the 100 ms post-PTT sleep, CAT serialization) simply exit the PTT path, for *normal*
  operation as well as for inhibit.
- **The RTS drop is the RF kill.** A hard-wired PTT release unkeys the radio in
  milliseconds regardless of what the audio buffer is doing — the two-tier abort of §5.4(b)
  collapses to one tier. Audio stop and sequencer bookkeeping become cleanup, off the
  critical path. (Rigs handle mid-audio unkey routinely — it is the same event as releasing
  a mic PTT mid-syllable; the rig's own sequencer drops drive before opening its relay.)
- **The gate is a level, computed continuously.** `RTS = intent ∧ ¬inhibit` re-evaluates on
  every input edge; there is no command ordering to get wrong and nothing to unwind.

Integration points inside WSJT-X (why this must be part of WSJT-X, not a sidecar): TX
*intent* exists only in-process — the only out-of-process equivalent is an analog gate in
the PTT cable (§6). Specifically:

1. **New PTT method** in Settings → Radio: "RTS, dedicated port, inhibit-gated." When
   selected, `transceiver_ptt()`'s intent routes to the gate thread instead of the hamlib
   rig thread (the rig object keeps `ptt_type=None`, as with VOX).
2. **PTT confirmation handshake preserved:** audio starts only after the rig confirms PTT
   (§5.1, mainwindow.cpp:12557). The gate thread reports its actual line state back
   (queued signal) as that confirmation — immediate when the gate is open; **withheld while
   inhibited**, which elegantly prevents the audio path from ever starting into a masked
   PTT at cycle start.
3. **The intent gate at mainwindow.cpp:7810 stays** (§5.4a). Without it, an inhibited cycle
   would run the whole modulator into a dead line with the UI showing TX. With it, cycles
   that begin during an inhibit are skipped cleanly; the RTS mask covers only the mid-cycle
   race. Both gates read the same INHIBIT state owned by the gate thread.
4. Deadman, keepalive, and hang-time (§3, §4.2) are timers on the gate thread itself; the
   thread emits state changes to the GUI thread for the UI badge and UDP status only —
   nothing on the fast path waits for the GUI.

**Design decision (2026-07-30): the gate thread *is* the serial-PTT path — not a second
one.** Rather than adding a new PTT method beside hamlib's DTR/RTS, the patch reroutes the
**existing DTR and RTS PTT methods** through the gate thread; hamlib keeps only CAT (and VOX
= None). One mechanism instead of two:

- Every DTR/RTS user exercises the gate code on every transmission, with the gate open —
  behavior identical to today, minus the rig-thread latency traps (§5.3), which is an
  improvement on its own merits.
- There is no configuration in which serial PTT bypasses the gate, so "inhibit didn't work
  because PTT was wired around it" cannot exist.
- The upstream story writes itself: "faster, cleaner serial PTT" carries the gate into the
  base fork where it gets tested and cannot be orphaned as a niche WIMS feature.

Cost, stated plainly: **one USB-serial dongle and one PTT wire per WSJT-X seat**, and a
departure from the fleet's current CAT-PTT convention (networking doc §3.3.3 sets
`PTT Method = CAT` via wfview; Flex seats key via SmartSDR CAT). That is a real wiring and
documentation change — but hard PTT lines are long-standing contest-station discipline, the
determinism benefits normal keying too, and the same RCA/phono PTT inputs exist on the
IC-9700 (SEND) and Flex (PTT in) back panels. Seats that cannot take the wire keep the §5.4
GUI-thread design as the fallback — the two share all the source/semantics code.

## 6. Actuator survey — where the RF actually stops

The gate can act at several depths; they are not exclusive. Layered view, fastest-certain
last:

| Layer | Mechanism | Kills RF in | Caveats |
|-------|-----------|-------------|---------|
| **PTT gate thread (§5.5, preferred)** | Dedicated-port RTS = intent ∧ ¬inhibit; UDP/CTS edge flips the line directly | **~1–2 ms to line drop + rig unkey (ms), deterministic** — no GUI tick, no rig thread, no audio buffer in the path | Requires the RTS-PTT seat wiring (dongle + PTT line per seat) and the WSJT-X patch |
| WSJT-X GUI-thread gate (§5.4, fallback for CAT-PTT seats) | Two-tier abort: audio buffer discarded, then PTT dropped bypassing the 200 ms timer | Audio tier ~2–25 ms + driver residual (bound with `WSJT_TX_AUDIO_BUFFER_FRAMES` ≈ 50 ms) — this is what silences an SSB/data rig; PTT tier ~5–60 ms, CAT worst 100–600 ms behind the rig poll | Prevention side race-free at the 100 ms `guiUpdate` quantum; on CAT seats the audio tier leads |
| §3.4.1 Layer-2 external audio mute | OS volume / VCA outside WSJT-X | 2–5 ms (analog) / 10–30 ms (software) | Keep as backstop — it works with *unpatched* WSJT-X and covers "patched gate failed" |
| Radio hardware TX-inhibit input | Rig's interlock pin wired to the SSB/CW PTT | µs–ms, deterministic, zero software | **Per-rig survey needed:** Flex 6000-series has TX REQ interlock inputs (polarity configurable); Icom/Yaesu seats vary and many rigs have no such input. Where it exists, this is the only path that needs no computer at all |

Recommendation: the **§5.5 gate thread is the primary** wherever the seat can take the RTS
wire — it is deterministic at ~1–2 ms, preserves QSO state, and blocks starts as well as
stops. CAT-PTT seats that can't be rewired use the §5.4 GUI-thread gate, where the **audio
tier is the real RF-off** (no audio = no RF on an SSB/data rig; plausibly ~10 ms with the
output buffer bounded — a §9.2 measurement, not an assumption). The **analog/audio backstop
stays** for defense-in-depth and for unpatched seats; **hardware inhibit inputs are wired
wherever the rig offers one**. The *block-a-start* case — the common case, per Mechanism 1 —
is exact at any depth, because nothing has to be un-done.

## 7. Release policy (the missing half of §3.4.1)

Explicit rules, replacing any implied "enable at key-up":

1. **Release restores the gate, never initiates TX.** No message, no re-arm, no Reply is sent
   because an inhibit ended.
2. **Hang time** (§3) absorbs CW keying trains and quick S&P bursts before the gate reopens.
3. **WSJT-X's sequencer owns resumption.** In puncture mode (§3) the current transmission
   resumes by itself the instant the gate reopens — nothing was ever stopped, only masked;
   a blocked cycle start resumes late within the same period if released before the 75 %
   point. Beyond that, if the auto-sequence schedules a retry in the next cycle, that is
   normal attended operation continuing — the operator armed it, the gate merely paused it.
   If the sequence expired during a long inhibit, resumption requires the normal human
   action (local UI or leased click-to-work).
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
| CTS dongle unplugged / watcher dies | INHIBIT asserted + loud alarm | A missing interlock wire must stop TX, not be ignored |
| UDP agent crashes while keyed | Keyed state expires after deadman (~600 ms) + alarm | Can't leave the band dead forever on a crash; expiry is visible |
| UDP agent silent (idle heartbeat lost) | Source marked degraded; TX continues; WIMS status red on that band | Choosing to hold digital is station policy, surfaced not defaulted |
| WSJT-X patch absent (stock binary on a seat) | §3.4.1 external mute + Halt path unchanged | The patch is an upgrade, not a new dependency |
| Both sources configured, one fails | OR semantics keep the surviving source authoritative | |
| Inhibit chatters (bad hang tuning) | FT8 impact bounded — puncture bench: ≤1.6 s total gap ≈ free | Protocol margin is the safety net, not the design target |

## 9. Test plan

1. **Unit (no radio):** gate semantics state machine — assert/release in each of the three
   situations of §3; hang-time behavior against scripted CW keying trains (dit-speed edge
   streams); deadman expiry and alarm paths. Same self-running style as `tests/unit/`.
2. **Latency bench (no RF):** loopback rig — GPIO/serial toggles CTS, patched WSJT-X (or the
   watcher module standalone) timestamps INHIBIT flip; measure distribution vs latency-timer
   setting (1 ms vs 16 ms) on Linux and Windows. Same for the UDP path with the agent on a
   second host. Publish the measured budget table into §6.
3. **RF-path verification (dummy load):** scope or SDR on the dummy load; key a function
   generator as "SSB PTT"; measure key-down → RF-gone for each actuator layer on each seat
   type (DTR/RTS, wfview CAT, Flex CAT, VOX). This replaces the estimates in §6 with numbers.
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
2. **WSJT-X patch** in the improved_PLUS build: the §5.5 PTT gate thread (new PTT method
   "RTS, dedicated port, inhibit-gated" + intent routing + confirmation handshake), the
   §5.4a intent gate at mainwindow.cpp:7810, settings (sources, ports, hang time), and a
   visible UI badge ("TX INHIBITED — 144 SSB"). The §5.4b GUI-thread abort ships as the
   fallback for seats still on CAT PTT.
   2a. **Seat wiring standard update** (networking doc §3.3): one USB-serial PTT dongle per
   WSJT-X seat, RTS → radio PTT input (IC-9700 SEND, Flex PTT-in); CAT becomes
   frequency/mode only.
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
            keyed datagram (any valid sender)
   OPEN  ───────────────────────────────────►  INHIBITED(deadline)
    ▲                                                │
    │  clear datagram (hang already applied          │ every keyed/keepalive datagram
    │  by the Key agent, §3),                        │ re-arms deadline = now + TTL
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
| UDP port | **Auto.** Bind 22372 if free, else an ephemeral port; the actual port is announced in InhibitStatus (§11.4), so nothing and nobody needs to know it in advance. Multi-instance hosts just work — second instance lands on an ephemeral port, announced the same way |
| Hang time | **Key agent** (§3) — the per-operator knob lives at the SSB/CW seat |

Trust model, stated: any LAN host can inhibit any WSJT-X. On a cooperative contest LAN this
is the same trust already extended to "Accept UDP requests," and the failure direction is
RX, alarmed and self-clearing. The complexity this deletes from every seat is the point —
if WIMS or the Key agent must carry more algorithm to keep WSJT-X state-free, that is the
right trade.

The PTT side (§5.5) adds no inhibit-specific settings either: the existing DTR/RTS PTT
method selection now routes through the gate thread — same screens, same fields as stock
WSJT-X.

### 11.3 Datagram format

Compact single-datagram JSON (debuggable with tcpdump/netcat; size is irrelevant at this
rate, and parsing cost is nanoseconds against a millisecond budget):

```json
{"wims_inhibit": 1, "state": "keyed", "ttl_ms": 600,
 "station": "ROY-222-SSB", "band": "222", "seq": 4711}
```

- `wims_inhibit: 1` — magic + version; anything else is ignored.
- `state`: `keyed` (assert, re-arm deadline to now + `ttl_ms`) or `clear` (start hang timer).
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
  instance in real time, and a `keyed` badge names the SSB/CW station holding the band.

### 11.5 Thread structure inside WSJT-X

One new class (`TxInhibitGate`), one new thread, following the existing worker-thread
patterns (`m_audioThread`, `transceiver_thread_`):

- Owns: the UDP socket (always bound — 22372 or ephemeral, §11.2), the deadman QTimer (no
  hang timer — §3), the INHIBIT atomic, and the serial PTT line: **all DTR/RTS PTT routes
  through this thread** (§5.5), so it owns the port stock WSJT-X would have handed to
  hamlib.
- Emits (queued, to GUI thread): `inhibitChanged(bool, QString source)` for the intent gate
  (§5.4a), the UI badge, and the InhibitStatus announcements. Nothing on the fast path waits
  for the GUI.
- Touches existing code in exactly three places: the one-line intent gate at
  mainwindow.cpp:7810, the PTT-method routing (existing DTR/RTS values redirected to the
  gate thread instead of hamlib — §5.5 decision), and the PTT-confirmation handshake (§5.5
  point 2). Everything else is additive.

### 11.6 Prototype sequence (test before integrate)

1. **Spike, no WSJT-X (days):** two small standalone programs in the WIMS repo —
   `key_agent_sim` (reads CTS or keyboard, emits §11.3 datagrams to a target list) and
   `inhibit_gate_sim` (binds 22372, drives RTS on a second dongle, implements §11.1 exactly).
   Scope on the two serial lines measures the full UDP path latency distribution and
   validates the deadman/hang logic against scripted CW keying. The gate logic is written as
   a pure, WSJT-X-independent module so the patch later transplants it, not reimplements it.
2. **Fork patch (the prototype for testing):** `TxInhibitGate` + settings + InhibitStatus +
   intent gate, built in the improved_PLUS tree (build infrastructure already present).
   Bench: WSJT-X transmitting into a dummy load / audio loopback, `key_agent_sim` firing
   bursts — verify puncture-and-resume on the air with an SDR, N1MM/GridTracker unaffected
   by message type 18, and the §9.2 latency numbers on the real thread.
3. **Real Key agent** (grows from `key_agent_sim` into a `wims.agent` role: CTS watcher +
   assignment list from the dashboard + persistence), then the WIMS assignment UI (#5 in the
   design-doc function table).

Order rationale: step 1 de-risks every design decision that does not require WSJT-X (format,
deadman, hang, latency) with an afternoon's hardware; step 2 is then a mechanical transplant
whose only new risks are Qt-threading and settings plumbing.
