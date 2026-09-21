# Home station slice: one TX + dual RX

**Status:** priority product slice (ahead of message-bus cutover)  
**Date:** 2026-09-17  
**Style:** STE Lite  
**Related:** `shared_trx_second_rx.md`, `inhibit_agent.md`, solo R0, bus harness (lower priority),  
`docs/decisions/2026-09-17-shared-trx-radio-ownership.md`

## 1. Why this is ahead of the bus

Home operators can test **chunks** of WIMS without a fleet LAN.

Target hardware: **one transceiver**, **dual RX** (IC-9700-style) or one TRX + SDR.  
Not the dual-radio mountain default.

Message-bus work stays designed/harnessed but **does not block** this slice.

## 2. Product cut (what “home WIMS” is)

### Minimum bar (ship this first in people’s heads)

| Piece | Role |
|-------|------|
| **Operate page** | One WSJT-X / one radio: **filter and rank decodes** + **click-to-Work**. |

No fleet. No Inhibit. No dual-RX story required. N1MM log optional (`--no-seed` OK).

### Small stack beyond the minimum

| Piece | Role |
|-------|------|
| **Standalone Operate** | Same window; add log seed / Work as the op wants |
| **Standalone Inhibit** | KEY → hold TX-capable digi (and later mute/CAT) |
| **Not much else** | No fleet Dashboard; no broker |

Optional later: seat Log into local N1MM; WSJT config check; dual RX.

## 3. The hard problem (name it)

N1MM and WSJT-X **both** want to drive the radio.

- N1MM: VFO / mode / PTT / CW for SSB-CW ops.  
- WSJT-X: dial, Fake It / split, often CAT PTT on Icom recipes.  
- Dual RX: one RX “belongs” to digi, one to voice — radios differ; APIs differ; quirks abound.

N1MM’s built-in FT8 path is **not** the answer. WIMS exists to avoid that.

**“WIMS spoofs N1MM’s radio interface”** is an idea, not a decision.  
Feasibility and robustness are **unknown**. Treat radio ownership as its own design beat (ADR), not as a silent assumption inside Operate.

Existing draft in `shared_trx_second_rx.md`: WIMS **Hamlib proxy** in front of wfview; WSJT-X talks to the proxy; N1MM CI-V may still talk to wfview directly with N1MM radio-set **OFF** during handoff. That is one candidate, not proven.

## 4. Staged delivery (so people can test early)

Do **not** wait for perfect CAT spoof before home testers run Operate + Inhibit.

| Stage | What ships | Radio control | Home tester gets |
|-------|------------|---------------|------------------|
| **H0** | Standalone Operate (local digi UDP → roster → Work) | Unchanged (op/N1MM/WSJT as today) | Click-to-work + scoring on one PC |
| **H1** | Standalone Inhibit (KEY → type-18 to TX digi) | Unchanged | Voice priority without fleet server |
| **H2** | Dual-RX / second-RX **decode** layout in docs + config check | Still manual / existing CAT | Two decode streams; one TX-capable marked |
| **H3** | KEY → inhibit + **TX-audio mute** (no CAT yet) | Mode change still human or N1MM | Blocks FT8-audio-in-SSB class of fault |
| **H4** | CAT handoff / proxy / ownership ADR implemented | WIMS coordinates voice vs digi profile | Footswitch-only shared-trx |

Inhibit **actuation** stays direct UDP at every stage.

## 5. Architecture work to schedule (before H4 code)

Short ADR: **Who may SET the radio, when?**

Cover at least:

1. DIGITAL phase — who sets VFO A / mode / split / PTT.  
2. VOICE phase — who sets VFO / mode; digi must not fight.  
3. Dual RX — MAIN vs SUB (or SDR): which app owns which.  
4. What N1MM must turn OFF (radio PTT, CW, set, WSJT bridge).  
5. Whether WIMS presents a **fake** radio to N1MM, or N1MM has **no CAT**, or N1MM talks to wfview with WIMS only parking WSJT.  
6. Failure: FAULT leaves digi held; human front panel still works.

Do not pick “spoof N1MM” until a spike shows one radio + N1MM + WSJT-X surviving handoff.

## 6. Relation to fleet / bus

| Concern | Home slice | Fleet / bus |
|---------|------------|-------------|
| Operate | Local window, local (or simple) ingest | Later: bus subscribe / multi Operate |
| Inhibit | Localhost or same-PC targets | Fleet same-band KEY; target list not band-only |
| Log | Optional local N1MM | Per-station logger policy |
| Broker | Not required | Later |

Home success does **not** require Tailscale or multi-PC.

## 7. Suggested near-term order

1. ~~**Write radio-ownership ADR**~~ → `docs/decisions/2026-09-17-shared-trx-radio-ownership.md`  
2. ~~**H0/H1 packaging**~~ → `docs/home_h0_h1.md`, `Start-Wims-Solo.*`, `Start-Wims-Inhibit-Home.*`, launcher Other tools  
3. **H2** config: mark TX-capable vs decode-only; dual RX wiring checklist.  
4. **H3** mute on KEY (Windows) before CAT.  
5. **H4** only after ADR + wfview/lab spike.

Bus harness P0 can proceed **in parallel at low priority**, or pause.

## 8. Success for “more people testing at home”

A home dual-RX op can:

1. Run Operate and see decodes / needed / Work.  
2. Run Inhibit and footswitch-hold digi without a site server.  
3. Follow a short checklist for IC-9700 (or one TRX + SDR) without joining a contest LAN.  
4. Know which stage they are on (H0–H4) and what is still manual.

## 9. Open questions

1. Is today’s `wims.solo` enough for H0, or must Operate be a separate window/port immediately?  
2. Home inhibit: ship **inhibit-agent** (wsjtx-inhibit) or **WIMS KEY** with a home profile?  
3. First radio for H4 spike: IC-9700 + wfview only, or also a second brand?  
