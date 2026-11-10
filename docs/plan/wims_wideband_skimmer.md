# WIMS wideband skimmer — design brief

**Status:** Designed, not built. Docs only. Nothing here transmits
on its own.  
**Decided by:** Jeff, WA1HCO (2026-11-09; whole-band decode and Flex
operating mode 2026-11-10).  
**Spotted list:** [wims_design.md](wims_design.md) §2.15.  
**Click-to-work for a Flex skimmer spot:** this brief (tune the
slice, wait for a WSJT-X decode, then UDP Reply).  
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

Each skimmer appears as one instance id such as `SKIM-B210-2m`, or,
in Flex operating mode, as a receive-only follower tied to the
WSJT-X instance it is watching. WIMS marks the skimmer receive-only:
it is never claimed, never armed, and never transmits, and it does
not join a TX resource group.

A click on a Flex skimmer spot can start work on that tied WSJT-X
instance, but only after WSJT-X itself decodes the station. WIMS
never presses Enable TX. The skimmer is never the target of a claim
or a Reply.

## Flex operating mode

On the Flex, WSJT-X stays in charge. WSJT-X sets the band and the
mode and tunes its Flex slice, as it does today.

The skimmer follows that instance’s UDP Status messages: dial
frequency, mode, and Transmitting. It sets up a DAX IQ stream
centered on that dial frequency, decodes the rest of that stretch of
band with the whole-band decoder, and sends spots to WIMS tied to
that WSJT-X instance.

When WSJT-X changes band or mode, the skimmer moves its IQ window
to the new dial and drops its old spots. It does not retune the
slice or change WSJT-X’s mode on its own.

The B210 has no WSJT-X driving it, so it keeps its own GUI settings
for band and capture.

## UDP and the RF frequency

A WSJT-X Decode carries only an audio offset (`df`) from the dial
frequency in Status. The roster already computes RF as dial + `df`. A
48 kHz capture does not fit in one ordinary audio offset, so the
skimmer has to say what the true RF is.

**Recommend one instance per receiver, plus an extension.** One id
(`SKIM-B210-2m`), one Heartbeat and Status. In Flex operating mode
the spots are tied to the watched WSJT-X instance, and the same
absolute-RF field is still required. Each Decode keeps the standard
fields and then an optional extra field with the absolute RF in
hertz. WIMS uses that field for Freq. A listener that ignores the
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
environment variables: choose which band to skim (B210), cap
cancellation passes or candidate count, and show whether the clock
is in sync. CPU should still stay inside the period on a modern PC;
that estimate is checked on the station, not assumed.

## Feeding WIMS

Decodes go to the Operate **Spotted** list with Source **skimmer**,
on the same path as DX cluster spots. Columns and need-reason badges
match the roster and the cluster list where the spot has that fact:
**DX · Country · Band · Mode · Grid · Freq · Az DX · km · Age ·
Score**. The DX badge is the same single word as the roster, judged
on that spot’s band and mode. A Flex-mode spot is tied to the
WSJT-X instance the skimmer is following.

Only a standard message that carries a valid callsign becomes a spot
or a roster station. Free text, malformed text, and a decode with no
callsign may appear in a decode log, and they never create a station.

The skimmer can still be visible as a receive-only instance so
heartbeat and status are honest. Subscribing to it must not make
WIMS try to Work, claim, or transmit on the skimmer itself.

## Click-to-work from a skimmer spot

A click on a Flex skimmer spot should be as simple and as fast as
possible. DX cluster spots still only select the station and
remember the grid, as they do today (§2.15).

UDP cannot set the TX frequency. `Configure` has no TX-frequency
field, and for a station outside the current WSJT-X audio channel
the operator has not picked a TX frequency yet. The way through is
to move the station into that channel, wait until WSJT-X itself
decodes it, and then send the same Reply WSJT-X already knows how
to honor.

Limits, all of which must be true or nothing moves:

- The spot is inside the current DAX IQ window.
- It is on the same band and mode as the tied WSJT-X instance.
- That instance is not transmitting, and no one else holds the
  claim on it.

On a click that passes those limits:

1. Retune the Flex slice through CAT so the spot lands at a fixed
   audio offset, about 1500 Hz. WSJT-X follows the rig.
2. Wait for that WSJT-X instance to decode the station in the next
   period. WIMS matches the decode by call and frequency. If a
   matching decode is already in hand, skip the wait.
3. Automatically send the UDP Reply message (type 4) built from
   that WSJT-X decode. This acts like the operator double-clicking
   the line: with Hold Tx Freq off, TX moves to the DX station’s
   frequency and the DX call and grid are loaded.

The cost of the wait is one period: about 15 s for FT8, 7.5 s for
FT4.

WIMS never transmits blind, and it never presses Enable TX. Whether
TX turns on follows the operator’s own WSJT-X double-click setting.
That is the same project rule as everywhere else: no automated
transmit.

If the station is not decoded within N periods, cancel and show a
short status line. N is a GUI setting; the default is 2.

A B210 spot that is not inside the current DAX IQ window cannot use
this path. The click then only selects the station, the same way a
cluster spot does.

If the antenna setting is on, and antenna control exists on that PC,
the rotator and SteppIR may move as part of the same click. That
move is not required for Reply, and it does not bypass the limits
above.

Open question, to be tested on this station: does Reply move TX when
Hold Tx Freq is on, and what happens with split (“Rig” or “Fake
It”)?

## Settings and launcher

Every setting lives in the GUI (Setup and the skimmer’s own window).
There is no command-line flag and no environment variable for the
operator. The skimmer gets a double-click launcher under
`scripts/`, like the other seat programs. Typed commands, if any,
belong only in a **Developer** section.

Settings include: which radio (Flex DAX IQ or B210), Flex operating
mode (follow a WSJT-X instance’s Status), the B210’s own band and
capture, cancellation-pass or candidate limits, a visible clock-sync
status, the instance id, the UDP destination WIMS already uses, the
click-to-work timeout in periods (default 2), and **Spot click moves
antenna**.

## Build order

| Step | Ships | Acceptance |
|------|--------|------------|
| 1. One period | Capture 48 kHz IQ on the UTC slot for one radio, Costas search, LDPC on candidates, emit Heartbeat, Status, and Decode | A stock UDP listener, and WIMS, see decodes. Nothing transmits. |
| 2. Spot source | WIMS shows those decodes as a receive-only **skimmer** source on the Spotted list | Source is skimmer. The skimmer instance cannot be claimed or used to Work. Free text does not create a station. |
| 3. Cancellation and both modes | Subtract and search again, FT8 and FT4 in the same pass, absolute RF, **off-freq** marker | A station off the usual dial is listed, with its true frequency and the marker. A weaker station under a strong one can be decoded. |
| 4. Flex operating mode | Follow WSJT-X Status; DAX IQ is centered on that dial; spots are tied to that instance | A band or mode change in WSJT-X moves the IQ window and drops the old spots. The B210 still uses its own GUI settings. |
| 5. Click-to-work | Retune the slice so the spot is at about 1500 Hz, wait for a WSJT-X decode, send Reply | The next period’s decode is matched by call and frequency, then Reply is sent. TX turns on only if the operator’s WSJT-X double-click setting would. Enable TX is never sent. A miss after N periods cancels with a short status line. Blocked outside the DAX IQ window, on a different band or mode, during TX, or under a foreign claim. |
| 6. Antenna | Rotator heading and SteppIR band, through the per-PC antenna agent | Moves only when the antenna checkbox is on and antenna control exists. Still no Enable TX from WIMS. |

Each step is a small job. None of this is built yet.

## Open questions

- How MAP144 should host or wrap this pipeline.
- How much to take from MAP65, QMAP, ka9q-radio’s `ft8-decoded`, and
  `ft8_lib`, and how those pieces are licensed and bundled without
  asking the operator for a path.
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
- Does Reply move TX when Hold Tx Freq is on, and what happens with
  split (“Rig” or “Fake It”)? Test this on the station before the
  click-to-work path is treated as settled.
- Whether WSJT-X reliably follows a CAT retune of its Flex slice in
  time for the next period.
- Reconcile §2.10 step 4’s “QSY over the WSJT-X UDP path” with this
  brief: UDP has no TX-frequency command, so a Flex skimmer click
  retunes the slice through CAT, waits for a WSJT-X decode, and
  then sends Reply.

## Cross-links

| Doc | Role |
|-----|------|
| [wims_design.md](wims_design.md) §2.15 | Spotted list; cluster clicks still only select |
| [wims_design.md](wims_design.md) §2.10 step 4 | Earlier prepare-on-click sketch; this brief replaces it for Flex skimmer spots |
| [wims_design.md](wims_design.md) §1.1 / §2.12 | UDP messages; Reply echoes a decode; `Configure` does not Enable Tx |
| [scoring.md](scoring.md) | Spot score, watering holes, workable distance |
| [wims_antenna.md](wims_antenna.md) | Rotator and later SteppIR, on the per-PC agent |
| [docs/design-principles.md](../design-principles.md) | Zero-knowledge UX; no operator flags or environment variables |
