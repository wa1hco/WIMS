# WIMS wideband skimmer — design brief

**Status:** Designed, not built. Docs only. Nothing here transmits.  
**Decided by:** Jeff, WA1HCO (2026-11-09).  
**Spotted list and prepare-on-click:** [wims_design.md](wims_design.md)
§2.15 and §2.10 step 4.  
**Watering holes and spot score:** [scoring.md](scoring.md).  
**Antenna moves:** [wims_antenna.md](wims_antenna.md).

A receive-only wideband skimmer for the station’s FlexRadio Flex 8600
(DAX IQ) and Ettus B210 (SoapySDR / UHD). It decodes FT8 and FT4
across the receiver passband — including DX on nonstandard frequencies
— by running `jt9`-style decoders on many slices, and it emits
standard WSJT-X UDP messages (Heartbeat, Status, Decode) so WIMS can
treat it as a spotting source with little new code. Other WSJT modes
can be added later.

## MAP144

[MAP144](https://github.com/wa1hco/map144) is the planned starting
framework. It is a separate project, not in this tree, and this brief
does not assume its internals. How much of its wideband input and
decoder pipeline to reuse is an open question.

## Receive-only

Each skimmer appears as one instance id such as `SKIM-B210-2m` or
`SKIM-FLEX-6m`. WIMS marks it receive-only: it is never claimed, never
armed, and never transmits, and it does not join a TX resource group.
A QSO still starts from a live roster decode, the same way a DX
cluster spot works today (§2.15).

## UDP and the RF frequency

A WSJT-X Decode carries only an audio offset (`df`) from the dial
frequency in Status. The roster already computes RF as dial + `df`. A
wide passband does not fit in one ordinary audio offset, so the
skimmer has to say what the true RF is.

| Option | How | Trade-off |
|--------|-----|-----------|
| **A. One Status per slice** | Each ~3 kHz slice is a logical instance with its own dial. RF = dial + `df`, as today. Stock listeners get the right frequency with no new fields. | A 192 kHz IQ stream could mean dozens of instance ids, heartbeats, and Operate rows unless WIMS collapses them. The id would no longer be the single name `SKIM-B210-2m`. |
| **B. One instance per receiver, plus an extension** | One id, one Heartbeat and Status. Each Decode keeps the standard fields and then an optional extra field with the absolute RF in hertz. WIMS uses that field for Freq. A listener that ignores the trailing field still parses the standard prefix. | Stock listeners that use only dial + `df` will not show the true RF until they learn the field. WIMS must understand it. |

**Recommend B.** The operator already named the instance as one
receive-only id per receiver, and WIMS is the primary consumer.
Operate stays uncluttered. Step 1 can ship a single slice with
ordinary dial + `df`, and add the extension when full-passband
slicing lands. Option A stays a fallback if the extension proves
awkward; WIMS would then group those slices under one skimmer row.

## Nonstandard frequencies

DX often runs off the usual FT8 and FT4 dials. The skimmer decodes
the **full receiver passband**, not only the watering holes in
[scoring.md](scoring.md).

- Slice the passband into overlapping windows (about 3 kHz wide, with
  enough overlap that a signal on a slice edge is not lost).
- Dedupe the same station heard on two overlapping slices in the same
  period, by call + time + frequency (within a small hertz window).
  Keep the stronger decode.
- Report each decode’s absolute RF on the spot row.
- WIMS flags a spot whose RF is outside the usual watering-hole
  window for that mode (the same ±2.5 kHz FT8 / narrower FT4 windows
  already used to infer cluster mode). The Spotted list shows an
  **off-freq** marker. The frequency itself stays in the Freq column.

CPU cost is slices × decoder runs per period, on every cycle. Limit
it from Setup, with no flags and no environment variables: choose
which sub-bands to skim, run a decoder only on slices that have
signal (energy detection), and offer a shallower decoder depth when
the machine is busy.

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

Settings include: which radio (Flex DAX IQ or B210), which band and
sub-bands, slice width and overlap, energy detection, decoder depth,
the instance id, the UDP destination WIMS already uses, and the two
spot-click checkboxes above.

## Build order

| Step | Ships | Acceptance |
|------|--------|------------|
| 1. One slice set | The skimmer emits Heartbeat, Status, and Decode for one slice on one radio | A stock UDP listener, and WIMS, see decodes. Nothing transmits. |
| 2. Spot source | WIMS shows those decodes as a receive-only **skimmer** source on the Spotted list | Source is skimmer. The instance cannot be claimed or used to Work. Free text does not create a station. |
| 3. Full passband | Overlapping slices, dedupe, absolute RF, **off-freq** marker | A station off the usual dial is listed, with its true frequency and the marker. CPU can be limited from Setup. |
| 4. Click fills WSJT-X | Mode, DX call, and grid over `Configure` | The operating instance shows the call and mode. No Reply. |
| 5. Rig frequency | After mode, set the radio through CAT | The operating WSJT-X follows the rig onto the spot’s dial. Blocked during TX or a foreign claim. |
| 6. Antenna | Rotator heading and SteppIR band, through the per-PC antenna agent | Moves only when the antenna checkbox is on and antenna control exists. Still no transmit. |

Each step is a small job. None of this is built yet.

## Open questions

- How MAP144’s input and decoder pipeline should be reused, and what
  it already does for IQ, slicing, and `jt9`.
- Whether a UDP `Configure` mode change jumps the radio to the
  default frequency the same way a screen mode change does. Test
  this before relying on the retune order.
- The exact layout of the optional Decode RF field, and whether any
  stock listener is broken by a trailing field.
- How the Flex DAX IQ stream and the B210 SoapySDR / UHD stream are
  opened on the seat PC (sample rate, center frequency, which PC
  runs the skimmer).
- The off-freq threshold: keep the watering-hole windows in
  [scoring.md](scoring.md), or a Setup value.
- Whether a valid skimmer decode should also appear as a heard
  station on a subscribed roster, or only on the Spotted list.
- Bundling or locating the `jt9` decoder, in the launcher, without
  asking the operator for a path.
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
