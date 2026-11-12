# WIMS wideband skimmer — design brief

**Status:** Designed, not built. Docs only. Nothing here transmits
on its own.  
**Decided by:** Jeff, WA1HCO (2026-11-09; whole-band decode, Flex
operating mode, and click-to-work limitation 2026-11-10).  
**Spotted list:** [wims_design.md](wims_design.md) §2.15.  
**Click-to-work for a skimmer spot:** this brief (pick a WSJT-X
instance, retune over CAT, Configure, then Reply only from that
instance’s own decode).  
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

A click on a skimmer spot can start work on a chosen WSJT-X
instance after that instance itself has the station in its decode
list. WIMS never presses Enable TX. The skimmer is never the
target of a claim or a Reply.

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

A click on a skimmer spot should be as simple and as fast as
possible. DX cluster spots still only select the station and
remember the grid, as they do today (§2.15).

Stock WSJT-X does not accept a Reply built from a skimmer-only
decode. In `replyToCQ` (`widgets/mainwindow.cpp`), WSJT-X rebuilds
the Band Activity line from the Reply fields and searches that
instance’s own decode document. If the line is not found, the
Reply is ignored (“process reply message ignored, decode not
found”). JTDX and MSHV do the same. This is a verified limitation,
not an open question. See
https://github.com/WSJTX/wsjtx/blob/master/widgets/mainwindow.cpp.

The comment in `NetworkMessage.hpp` that Reply is only for a prior
CQ or QRZ is stale. The code accepts any matching decode.
`m_bDoubleClicked` (the auto-reply / Enable Tx path) is set only
for CQ, CQDX, or QRZ, a message containing `73 `, or when Hold Tx
Freq is checked.

`Configure` (type 15) has Rx DF but no Tx DF. No FT8-family
program can set the dial frequency over UDP. JTDX has a
`SetTxDeltaFreq` message (type 50), but it still requires a local
decode for Reply.

On a click:

1. Pick the WSJT-X instance that will work the station. Block if
   that instance is transmitting, or if someone else holds the
   claim on it.
2. Retune the radio over CAT (Flex CAT, or the PC agent) so the
   spot lands near 1500 Hz audio offset. Send mode through
   `Configure` before changing frequency, because a mode change
   can snap the VFO to the default frequency.
3. Send `Configure` with mode, Rx DF, DX call, DX grid, and
   Generate Messages, so the station is loaded without
   transmitting.
4. If that same instance already decoded the station, send the
   UDP Reply (type 4) immediately, built from that instance’s
   own decode. Otherwise wait for the instance’s next decode of
   the station (about one period, roughly 30 s after a mid-period
   click) and then send Reply. If the station is not decoded
   within N periods, cancel and show a short status line. N is a
   GUI setting; the default is 2.
5. Enable TX and Auto Seq stay with the operator. WIMS never
   presses Enable TX.

Reply acts like a double-click. Warn the operator when Hold Tx
Freq is on, or when the message is CQ or contains `73 `, because
those cases may enable TX per the operator’s own WSJT-X settings.
That is the same project rule as everywhere else: no automated
transmit, and no blind transmit.

Three common cases:

1. The same radio jumps to a skimmer spot. Retune over CAT, send
   `Configure`, then Reply after that instance’s own decode.
2. Another radio takes the spot. Use the same flow, aimed at that
   instance. It probably does not already have the decode, so
   expect the wait.
3. All radios are listening and the operator pounces. Send the
   click to an instance that already has the decode, and Reply
   can go out at once. If no instance has it, treat this as case 2.

If the antenna setting is on, and antenna control exists on that PC,
the rotator and SteppIR may move as part of the same click. That
move is not required for Reply, and it does not bypass the limits
above.

Split modes “Rig” and “Fake It” are still to be tested on this
station after a CAT retune.

## Upstream ideas

WIMS cannot skip the wait today: stock WSJT-X ignores a Reply that
is not in that instance’s decode list, `Configure` has no TX
frequency field, and no FT8-family program can set the dial over
UDP.

A useful UDP addition would be either a Reply that skips the
decode-list check (and carries the message text) or a TX frequency
field in `Configure`. That is something to propose to upstream,
alongside the TX Inhibit work.

Alternatives considered, and not adopted:

- JTDX `SetTxDeltaFreq` (type 50) can set a TX audio offset, but
  JTDX still requires a local decode for Reply, and WIMS targets
  stock WSJT-X.
- JS8Call’s JSON API has `RIG.SET_FREQ`, but that is a different
  protocol and a different mode family.

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
| 5. Click-to-work | Pick a WSJT-X instance, retune over CAT so the spot is near 1500 Hz, Configure (mode, Rx DF, DX call, DX grid, Generate Messages), then Reply only from that instance’s own decode | Mode is set via Configure before the frequency change. If the instance already has the decode, Reply is sent at once; otherwise wait up to N periods (about 30 s after a mid-period click) and then Reply. Enable TX and Auto Seq stay with the operator; WIMS never presses Enable TX. Warn when Hold Tx Freq is on or the message is CQ or contains 73, because Reply may enable TX like a double-click. Blocked during TX or under a foreign claim. |
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
- What happens with split (“Rig” or “Fake It”) after a CAT retune.
  Test this on the station before the click-to-work path is treated
  as settled.
- Whether WSJT-X follows a CAT retune in time to decode the station
  in the next period.
- Reconcile §2.10 step 4’s “QSY over the WSJT-X UDP path” with this
  brief: UDP has no TX-frequency command, and stock WSJT-X ignores
  a Reply that is not in that instance’s decode list, so a skimmer
  click retunes over CAT, sends Configure, and Replies only from
  that instance’s own decode.

## Cross-links

| Doc | Role |
|-----|------|
| [wims_design.md](wims_design.md) §2.15 | Spotted list; cluster clicks still only select |
| [wims_design.md](wims_design.md) §2.10 step 4 | Earlier prepare-on-click sketch; this brief replaces it for skimmer spots |
| [wims_design.md](wims_design.md) §1.1 / §2.12 | UDP messages; Reply echoes a decode; `Configure` does not Enable Tx |
| [scoring.md](scoring.md) | Spot score, watering holes, workable distance |
| [wims_antenna.md](wims_antenna.md) | Rotator and later SteppIR, on the per-PC agent |
| [docs/design-principles.md](../design-principles.md) | Zero-knowledge UX; no operator flags or environment variables |
