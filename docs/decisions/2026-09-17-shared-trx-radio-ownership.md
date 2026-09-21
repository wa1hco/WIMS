# Decision draft: Who owns the radio on shared-trx / home dual RX

**Status:** draft — problem framed; **no option adopted yet**  
**Date:** 2026-09-17  
**Priority:** ahead of message-bus cutover; gates home slice stage **H4**  
**Related:** `docs/plan/shared_trx_second_rx.md`, `docs/plan/wims_home_dual_rx_slice.md`

## Context

Home and many VHF seats use **one transceiver** with **dual RX** (or one TRX + SDR).

WIMS must support:

- SSB/CW on that TRX  
- FT8 (and kin) TX on the same TRX at other times  
- Continuous digi **decode** on the second RX while voice TX  

N1MM’s built-in FT8 integration is **not** viable for this. That is why WIMS exists.

Both **N1MM** and **WSJT-X** want CAT (and related) control. Radios differ. Dual-RX MAIN/SUB semantics differ. Quirks and bugs are common.

A tempting idea: **WIMS spoofs N1MM’s radio interface** so WIMS is always the real CAT master. That may be right later. It is **not proven** robust.

## Decision needed (later)

Pick one ownership model for SET commands (VFO, mode, split, PTT policy) in each phase:

| Phase | Digi TX | Voice TX | Second RX decode |
|-------|---------|----------|------------------|
| DIGITAL | allowed (gated) | no | yes |
| HANDOFF | held | not yet | yes |
| VOICE | held + muted | yes | yes |
| FAULT | held | front panel only | yes |

## Options (not chosen)

| ID | Model | Sketch | Pros | Cons |
|----|--------|--------|------|------|
| **A** | **WIMS proxy; N1MM radio-set OFF** | WSJT → WIMS Hamlib proxy → wfview. N1MM CI-V may see radio but must not SET during handoff (`shared_trx_second_rx.md` KD7). | Matches existing draft; smaller spoof surface | Voice op loses some N1MM radio UX; discipline on N1MM checkboxes |
| **B** | **WIMS spoofs N1MM radio** | N1MM talks only to WIMS fake rig; WIMS talks to real radio | N1MM “has a radio”; WIMS arbitrates | Large surface; protocol + quirk tax; high contest risk |
| **C** | **N1MM owns CAT in VOICE; WSJT in DIGITAL; WIMS switches lease** | Explicit master by phase | Clear story | Fight risk on bugs; timing holes |
| **D** | **N1MM has no CAT** | Log + Broadcast only; freq from WIMS/RadioInfo/UI | Simplest control plane | Weak SSB op comfort |
| **E** | **Manual mode** (H0–H3) | Human or existing app CAT; WIMS only inhibit (± mute) | Ships home tests now | Not footswitch-only shared-trx |

**Working stance until spike:** use **E** for home H0–H3. Design H4 toward **A** unless a spike shows **B** is tractable on one reference radio.

## What is decided now

1. **Do not block** standalone Operate + standalone Inhibit on solving CAT spoof.  
2. **Inhibit actuation** stays direct type-18 UDP.  
3. **H4** (CAT handoff) requires a lab spike on one reference stack before adopting A or B.  
4. Message-bus cutover stays **lower priority** than this home slice.

## Spike plan (before adopting A or B)

Reference stack (proposed): **IC-9700 + wfview RigCtld + one TX WSJT-X + N1MM Logger + WIMS**.

| Step | Observe |
|------|---------|
| S1 | Capture Hamlib traffic: WSJT-X alone vs N1MM alone vs both |
| S2 | MAIN vs SUB: which commands move which RX |
| S3 | Proxy PASS/COORD/BLOCK with WSJT pointed at proxy (option A) |
| S4 | KEY down sequence: inhibit → mute → voice profile → permit |
| S5 | Failure injection: CAT timeout, mute missing → FAULT holds digi |
| S6 | Only if A fails UX: time-box a **B** prototype (fake rig for N1MM) |

Pass for “A is viable”: footswitch-only voice with digi decode alive; no FT8 audio in SSB; digi restores dial after dwell; N1MM log still usable.

## Home slice stages (reminder)

| Stage | WIMS | Radio ownership |
|-------|------|-----------------|
| H0 Operate | roster / Work | E (unchanged) |
| H1 Inhibit | KEY → holds | E |
| H2 Dual decode config | TX-capable mark | E |
| H3 Mute on KEY | + mute | E |
| H4 CAT | handoff | A or B after spike |

## Consequences

- Docs and launcher should label home testers by **stage** (H0–H4).  
- Do not market “shared-trx complete” until H4 spike passes.  
- Fleet dual-radio default unchanged (inhibit without CAT).

## Open

- First spike radio: IC-9700 only, or second brand in parallel?  
- Home inhibit binary: `inhibit-agent` vs WIMS KEY home profile?  
- Is `wims.solo` enough for H0 Operate, or separate window/port now?  
