# WIMS wideband skimmer — design brief

**Status:** Designed, not built. Docs only. Nothing here transmits.  
**Decided by:** Jeff, WA1HCO (2026-11-09; whole-band decode 2026-11-10).  
**Spotted list and prepare-on-click:** [wims_design.md](wims_design.md)
§2.15 and §2.10 step 4.  
**Watering holes and spot score:** [scoring.md](scoring.md).  
**Antenna moves:** [wims_antenna.md](wims_antenna.md).

A receive-only wideband skimmer for the station’s FlexRadio Flex 8600
(DAX IQ) and Ettus B210 (SoapySDR / UHD). It decodes FT8 and FT4
across the receiver passband — including DX on nonstandard frequencies
— by a whole-band search, not by slicing the band into `jt9` windows,
and it emits standard WSJT-X UDP messages (Heartbeat, Status, Decode)
so WIMS can treat it as a spotting source with little new code. Other
WSJT modes can be added later.

## MAP144

[MAP144](https://github.com/wa1hco/map144) is the planned starting
framework. It is a separate project, not in this tree, and this brief
does not assume its internals. How it should host or wrap the
whole-band decoder is an open question.

## Whole-band decode

The skimmer does not cut the band into 3 kHz slices and run `jt9` on
each one. It searches the whole capture at once.

For each period, capture the full 48 kHz IQ, lined up with the UTC
slot boundaries: 15 s for FT8, 7.5 s for FT4. Time sync matters. A
clock that is off will miss or weaken the Costas peaks.

Then, in one pass:

1. Make one spectrogram of the whole band (3.125 Hz bins for FT8) and
   correlate the Costas sync pattern at every frequency bin and time
   offset. That gives a candidate list with no fixed sub-band slots.
2. For each candidate: mix it down, filter and decimate to about
   200 Hz, then run the LDPC decode.
3. Subtract each decoded signal and search again so weaker stations
   under strong ones are caught.
4. Search for FT4 in the same pass, with its own sync pattern,
   timing, and bin size.

There are no losses at slice edges and no duplicate decodes from
overlapping windows. CPU only goes where there are signals: the
Costas search finds the candidates, and the LDPC decoder runs on
those, not on empty spectrum. FT8 plus FT4 over 48 kHz should fit
within each period on a modern PC. That is an estimate, to be
checked on the station PC.

Code to start from: MAP65 and QMAP in the WSJT-X source tree,
ka9q-radio’s `ft8-decoded`, and `ft8_lib` in C. MAP144 stays the
planned framework around that work.

## Receive-only

Each skimmer appears as one instance id such as `SKIM-B210-2m` or
`SKIM-FLEX-6m`. WIMS marks it receive-only: it is never claimed, never
armed, and never transmits, and it does not join a TX resource group.
A QSO still starts from a live roster decode, the same way a DX
cluster spot works today (§2.15).

## UDP and the RF frequency

A WSJT-X Decode carries only an audio offset (`df`) from the dial
frequency in Status. The roster already computes RF as dial + `df`. A
48 kHz capture does not fit in one ordinary audio offset, so the
skimmer has to say what the true RF is.

**Recommend one instance per receiver, plus an extension.** One id
(`SKIM-B210-2m`), one Heartbeat and Status. Each Decode keeps the
standard fields and then an optional extra field with the absolute RF
in hertz. WIMS uses that field for Freq. A listener that ignores the
trailing field still parses the standard prefix, but will not show
the true RF until it learns the field.

A 48 kHz capture needs that extension from the first decode step.
Splitting the band into many logical Status instances, one per 3 kHz
window, is not part of this plan: the decoder has no slices to hang
them on, and Operate would fill with instance rows.

## Nonstandard frequencies

DX often runs off the usual FT8 and FT4 dials. The whole-band Costas
search already looks at every frequency bin in the 48 kHz capture, so
those stations fall out of the same pass as everyone else. There is
no separate off-frequency hunt, and no slice-edge loss.

WIMS still flags a spot whose RF is outside the usual watering-hole
window for that mode (the same ±2.5 kHz FT8 / narrower FT4 windows
already used to infer cluster mode in [scoring.md](scoring.md)). The
Spotted list shows an **off-freq** marker. The frequency itself stays
in the Freq column.

If the machine is busy, Setup can limit the work without flags or
environment variables: choose which band to skim, cap cancellation
passes or candidate count, and show whether the clock is in sync.
CPU should still stay inside the period on a modern PC; that estimate
is checked on the station, not assumed.

## Feeding WIMS

Decodes go to the Operate **Spotted** list with Source **skimmer**,
on the same path as DX cluster spots. Columns and need-reason badges
match the roster and the cluster list where the spot has that fact:
**DX · Country · Band · Mode · Grid · Freq · Az DX · km · Age ·
Score**. The DX badge is the same single word as the roster, judged
on that spot’s band and mode.

Only a standard message that carries a valid callsign becomes a spot
or a roster station. Free text, malformed text, and a decode with no
callsign may appear in a decode log, and they never create a station.

The skimmer can still be visible as a receive-only instance so
heartbeat and status are honest. Subscribing to it must not make
WIMS try to Work, claim, or transmit on it.

## Spot click

Today a Spotted click only selects the station and remembers the
grid (§2.15). It does not retune and it does not transmit. This
brief is the prepare path that §2.10 step 4 already named, with one
correction: UDP `Configure` can set mode, DX call, and grid, but the
protocol has no command that sets the dial frequency. Frequency goes
to the radio through the seat’s rig control (the Flex’s CAT).
WSJT-X follows the rig.

On a click, when the matching setting is on:

1. Pick the PC and the live WSJT-X instance that cover that band, or
   that will after a QSY. If none can, nothing moves, and the row
   says so.
2. Set WSJT-X’s mode, and fill the DX call and grid, over UDP
   `Configure`.
3. Then set the rig to the spot’s dial frequency through CAT.
4. If the antenna setting is on, and antenna control exists on that
   PC, turn the rotator to the station’s heading and set the SteppIR
   for that band.

Mode is first because changing mode in WSJT-X can jump the radio to
that mode’s default frequency. It is **not yet verified** whether a
mode change sent over UDP does the same thing as a mode change on
the WSJT-X screen. That must be tested on this station before the
order is treated as settled. If UDP jumps the rig, setting frequency
after mode puts the radio back on the spot.

The click never sends Reply, never enables transmit, and never
starts a QSO. Work still starts from a live roster decode.

**Blocked** while that operating instance is transmitting, or while
someone else holds the claim on it. A skimmer instance is never the
target of a retune.

Two Setup checkboxes, both off until the operator turns them on:

- **Spot click retunes radio**
- **Spot click moves antenna**

## Settings and launcher

Every setting lives in the GUI (Setup and the skimmer’s own window).
There is no command-line flag and no environment variable for the
operator. The skimmer gets a double-click launcher under
`scripts/`, like the other seat programs. Typed commands, if any,
belong only in a **Developer** section.

Settings include: which radio (Flex DAX IQ or B210), which band, the
48 kHz capture, cancellation-pass or candidate limits, a visible
clock-sync status, the instance id, the UDP destination WIMS already
uses, and the two spot-click checkboxes above.

## Build order

| Step | Ships | Acceptance |
|------|--------|------------|
| 1. One period | Capture 48 kHz IQ on the UTC slot for one radio, Costas search, LDPC on candidates, emit Heartbeat, Status, and Decode | A stock UDP listener, and WIMS, see decodes. Nothing transmits. |
| 2. Spot source | WIMS shows those decodes as a receive-only **skimmer** source on the Spotted list | Source is skimmer. The instance cannot be claimed or used to Work. Free text does not create a station. |
| 3. Cancellation and both modes | Subtract and search again, FT8 and FT4 in the same pass, absolute RF, **off-freq** marker | A station off the usual dial is listed, with its true frequency and the marker. A weaker station under a strong one can be decoded. |
| 4. Click fills WSJT-X | Mode, DX call, and grid over `Configure` | The operating instance shows the call and mode. No Reply. |
| 5. Rig frequency | After mode, set the radio through CAT | The operating WSJT-X follows the rig onto the spot’s dial. Blocked during TX or a foreign claim. |
| 6. Antenna | Rotator heading and SteppIR band, through the per-PC antenna agent | Moves only when the antenna checkbox is on and antenna control exists. Still no transmit. |

Each step is a small job. None of this is built yet.

## Open questions

- How MAP144 should host or wrap this pipeline.
- How much to take from MAP65, QMAP, ka9q-radio’s `ft8-decoded`, and
  `ft8_lib`, and how those pieces are licensed and bundled without
  asking the operator for a path.
- Whether a UDP `Configure` mode change jumps the radio to the
  default frequency the same way a screen mode change does. Test
  this before relying on the retune order.
- The exact layout of the optional Decode RF field, and whether any
  stock listener is broken by a trailing field.
- How the Flex DAX IQ stream and the B210 SoapySDR / UHD stream are
  opened on the seat PC (sample rate, center frequency, which PC
  runs the skimmer), and whether a capture wider than 48 kHz is
  useful later.
- How the skimmer PC stays in UTC sync, and how Setup shows a clock
  that is off.
- Whether FT8 plus FT4 over 48 kHz finishes inside the period on
  this station’s PC, as estimated.
- The off-freq threshold: keep the watering-hole windows in
  [scoring.md](scoring.md), or a Setup value.
- Whether a valid skimmer decode should also appear as a heard
  station on a subscribed roster, or only on the Spotted list.
- When to add MSK144, Q65, and other modes.
- Reconcile §2.10 step 4’s “QSY over the WSJT-X UDP path” with the
  fact that UDP has no dial-frequency command. This brief is the
  correction: mode over UDP, frequency through CAT.

## Cross-links

| Doc | Role |
|-----|------|
| [wims_design.md](wims_design.md) §2.15 | Spotted list, cluster source, click selects only today |
| [wims_design.md](wims_design.md) §2.10 step 4 | Prepare-on-click; this brief fills in frequency and mode order |
| [wims_design.md](wims_design.md) §1.1 / §2.12 | UDP messages; `Configure` does not Enable Tx |
| [scoring.md](scoring.md) | Spot score, watering holes, workable distance |
| [wims_antenna.md](wims_antenna.md) | Rotator and later SteppIR, on the per-PC agent |
| [docs/design-principles.md](../design-principles.md) | Zero-knowledge UX; no operator flags or environment variables |
