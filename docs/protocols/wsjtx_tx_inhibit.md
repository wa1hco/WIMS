# WSJT-X TX Inhibit wire protocol — WIMS implementation brief

**Status:** design transfer for implementation (2026-09-02).  
**Authority (wire + gate):** sister repo
[`wsjtx-inhibit`](https://github.com/wa1hco/wsjtx-inhibit)
[`docs/TX_INHIBIT.md`](https://github.com/wa1hco/wsjtx-inhibit/blob/main/docs/TX_INHIBIT.md).  
**This file:** what WIMS must change so `wims-key-agent` and lab spike code speak
the **shipped** protocol. Do not treat older WIMS JSON examples as current.

WIMS still owns: target-list assignment, InhibitStatus discovery, band policy
(`interlock` vs `coordinated`), and fleet UX. The datagram on UDP **22372** is
defined by wsjtx-inhibit.

---

## 1. Why this transfer

Early WIMS / spike design used a compact **JSON** hold on `:22372`:

```json
{"tx_inhibit":1,"ttl_ms":600,"station":"ROY-222-SSB","band":"222","seq":4711}
```

That is **obsolete**. Shipped wsjtx-inhibit (PR #61 direction) accepts only
`NetworkMessage::TxInhibit` **type 18** (QDataStream schema 3). Legacy JSON is
**ignored**. A WIMS KEY agent that still emits JSON will not hold any patched
WSJT-X station.

Two algorithmic changes came with the new wire:

| Old WIMS spike / `wims_tx_inhibit.md` §11.3 | Current (wsjtx-inhibit) |
|---------------------------------------------|-------------------------|
| JSON UTF-8 object | Binary `NetworkMessage` type **18** |
| One global hold; any release clears | **Per-Controller ID leases**, OR’d |
| Release clears whoever’s hold | Release clears **only that** Controller ID |
| Fields: `station`, `band`, `seq` | Fields: target Id, **Controller ID**, TTL ms, Station |
| InhibitStatus “proposed type 18” | **InhibitStatus = 17** (telemetry); **TxInhibit = 18** (hold) |

Semantics that **did not** change: TTL-only message (`ttl_ms > 0` = hold/keepalive,
`ttl_ms = 0` = release); hang lives in the KEY agent only; direct UDP agent → gate
(never through the WIMS server); fail-open via lease expiry (deadman).

---

## 2. Core equation (unchanged product meaning)

```text
assert PTT  ⇔  want_tx  and  not hold
hold        ⇔  any live per-controller lease
```

| Term | Meaning for WIMS implementers |
|------|-------------------------------|
| **hold** | Station must not assert RTS/DTR PTT |
| **lease** | One row keyed by **Controller ID**, with an expiry time |
| **Controller ID** | Stable machine id of the KEY agent / sender (required, non-empty) |
| **Station** | Human badge text (`held by …`); not a lease key |
| **release hold** | Type-18 with `ttl_ms = 0` for **this** Controller ID |
| **hang** | Agent-only anti-chatter after KEY open (break-in CW). Not on the wire |
| **lease TTL** | Safety window on the station (~500–600 ms); keepalives ~200 ms |

---

## 3. Wire format (type 18)

**Transport:** UDP unicast to the WSJT-X station inhibit port (default **22372**;
may be ephemeral — discover via InhibitStatus type 17 on plane A).  
**Framing:** WSJT-X `NetworkMessage` / `QDataStream` schema **3**, max **512** bytes.  
**Magic:** `0xADBCCBDA`.

Common header (all NetworkMessage types):

| Field | Type |
|-------|------|
| magic | quint32 `0xADBCCBDA` |
| schema | quint32 `3` |
| type | quint32 `18` (`TxInhibit`) |
| Id (target) | utf8 (QByteArray) |

Type-18 body after Id:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| **Controller ID** | utf8 | **yes, non-empty** | Lease key. Sender may only refresh/release its own row |
| **TTL ms** | quint32 | yes | `>0`: upsert lease to `now + TTL` (range 100…30000). `0`: release this controller |
| **Station** | utf8 | recommended | Badge text |

On dedicated port 22372 the target **Id is parsed but not used for matching** —
addressing is by unicast `host:port` (WIMS target list / discovery).

### Hold / keepalive

Same packet. Nonzero TTL upserts that Controller ID’s lease.

### Release

`ttl_ms = 0` deletes **only that** Controller ID’s lease. Normal end after agent
hang finishes (or on clean quit). Do not rely on station timeout as the happy path.

### Deadman

If a lease is not refreshed before its TTL, that row expires. Hold ends when **no**
leases remain.

### Invalid packets

Bad magic/schema, wrong type, empty Controller ID, bad TTL, short/oversize, stream
error: **ignored** (counted `invalid`). JSON is invalid.

### Trust

No authentication. Any host that can reach `:22372` can suppress TX. Effect decays
when packets stop (TTL). No packet can force TX. Firewall 22372 on untrusted nets.

Reference encoder (copy semantics, not the file path):  
`wsjtx-inhibit/tools/send_inhibit_hold.py` → `encode(controller_id, ttl_ms, station, target_id)`.

Python shape (stdlib only):

```python
import struct

NM_MAGIC = 0xADBCCBDA
NM_SCHEMA = 3
NM_TX_INHIBIT = 18

def _qbytearray(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data

def encode_tx_inhibit(controller_id: str, ttl_ms: int,
                      station: str = "", target_id: str = "") -> bytes:
    if not controller_id:
        raise ValueError("controller_id must be non-empty")
    body = struct.pack(">III", NM_MAGIC, NM_SCHEMA, NM_TX_INHIBIT)
    body += _qbytearray(target_id.encode("utf-8"))
    body += _qbytearray(controller_id.encode("utf-8"))
    body += struct.pack(">I", int(ttl_ms) & 0xFFFFFFFF)
    body += _qbytearray(station.encode("utf-8"))
    return body
```

---

## 4. Multi-op / multi-KEY implications (why leases)

Fleet pattern WIMS cares about:

- Several WSJT-X seats on one band (separate antennas).
- Separate SSB and CW priority stations on that band.
- Either SSB or CW KEY agent may hold **all** digi seats on the band.
- Digi-vs-digi “only one WSJT-X TX” remains a **WIMS arbiter** concern (Halt/Reply
  claim), not this wire.

**Receiver-side OR of leases** is required so two KEY agents do not clobber each
other. Example:

1. SSB agent (`controller_id=ROY-SSB`) holds → lease A live.  
2. CW agent (`controller_id=ROY-CW`) holds → lease B live; station still held.  
3. SSB releases (`ttl_ms=0`) → only A cleared; B still holds digi seats.  
4. CW releases → hold ends.

Old global-hold + “any release clears” is **unsafe** for that topology. Do not
reintroduce it in WIMS lab gate code.

WIMS still ORs KEY *sources* into destination lists as needed; the station gate
must also OR leases so two independent agents remain correct without a single
merged KEY line.

---

## 5. InhibitStatus (type 17) — discovery / telemetry

Outbound on the normal WSJT-X UDP Server path (plane A, typically `224.0.0.73:2237`),
not on 22372:

| Field | Type | Use |
|-------|------|-----|
| Id | utf8 | Instance key (`--rig-name`) |
| Inhibit port | quint16 | Where to send type-18 (22372 or ephemeral) |
| Inhibited | bool | Any lease live |
| Source station | utf8 | Badge (may list holders) |
| Hold rx / Release rx / Expiries / Invalid | quint32 ×4 | Plumbing triage |

WIMS Key agent should resolve assignment targets by **instance id → live host:inhibit_port**
from InhibitStatus, then send type-18 there. Survives WIMS server outage for *actuation*
once the target list (or last list) is known.

---

## 6. What WIMS must implement

### 6.1 Code

**Lab path done (2026-09-02):** `inhibit.py` + unit tests + spike speak type 18
with per-controller leases. Key **daemon** product fan-out and InhibitStatus
discovery remain later.

| Area | Was (stale) | Now / remaining |
|------|-------------|-----------------|
| `src/wims/interlock/inhibit.py` encode/parse | JSON `tx_inhibit` | **Done** — type-18 QDataStream |
| `InhibitGate` | Single global hold; any release clears | **Done** — per-`controller_id` leases OR’d |
| `KeyAgentScheduler` emit path | JSON + `band`/`seq` | **Done** — `controller_id` + `station`; band off-wire |
| `testbed/inhibit_spike.py` | Speaks JSON | **Done** — type-18; `--controller-id` |
| `tests/unit/test_inhibit.py` | JSON / single-hold cases | **Done** — type-18; multi-OR; deadman |
| `python -m wims.key` daemon | Config stub only | **Remaining** — emit type-18 on CTS; stable controller id |

Suggested `controller_id` defaults: hostname + role (`{host}-ssb`, `{host}-cw`) or an
explicit config field. Must be stable across keepalives for the same physical KEY seat.

### 6.2 Hang policy (agent-local — align with authority)

Authority hang (wsjtx-inhibit §3.4): break-in CW hang = **1.5 × word gap**
(= **10.5 × dit**) at measured WPM, clamped; non-break-in / SSB hang **0**.
**Lab scheduler aligned (2026-09-02):** `ADAPTIVE_DITS = 10.5`, clamp
0.315–1.260 s. Older 8×dit values are historical only.

### 6.3 Docs to treat as superseded on wire claims

| Doc | Action |
|-----|--------|
| [wims_tx_inhibit.md](../plan/wims_tx_inhibit.md) §11.3 JSON | Historical; banner points here |
| [wims_key_agent.md](../plan/wims_key_agent.md) | Protocol → this file |
| [inhibit_agent.md](../plan/inhibit_agent.md) | wsjtx-inhibit copy; wire is type 18 there now |
| Lab comments in `inhibit.py` | Update when code lands |

Product / scenario text in `wims_tx_inhibit.md` (latency goals, KEY sense, badge
philosophy, band policy) remains useful — only the **datagram** and **single global
hold** claims are wrong.

### 6.4 Explicit non-goals for this transfer

- Do not route holds through the WIMS server.
- Do not dual-accept JSON on the WSJT-X gate (already decided upstream: type 18 only).
- Do not put hang on the wire.
- Digi-vs-digi single-TX arbitration stays in WIMS arbiter / Halt path.

---

## 7. Multi-multi checklist (acceptance)

1. **One KEY agent → N digi seats on a band:** unicast type-18 to each inhibit port;
   all show hold; release clears all.  
2. **Two KEY agents → same digi seat:** different Controller IDs; hold while either
   live; one release does not clear the other.  
3. **Deadman:** kill agent without release → seat opens after TTL.  
4. **Old JSON agent:** seat does **not** inhibit (invalid counter may climb).  
5. **Plane A:** InhibitStatus still visible to WIMS; type-18 never on 2237.  
6. **Coordinated band policy:** WIMS must not send holds (sense/report only).

---

## 8. Suggested implementation order

1. Replace encode/parse + `InhibitGate` leases in `inhibit.py`; fix unit tests.  
2. Update spike / `wims.key` selftest to type-18.  
3. Wire `wims.key` daemon / Key agent UI to emit type-18 with required Controller ID.  
4. Consume InhibitStatus port in target resolution (if not already).  
5. Align hang constants with TX_INHIBIT.md.  
6. One live bench: patched WSJT-X + WIMS Key agent (or spike) on LAN.

Reference packets / tools in wsjtx-inhibit: `tools/send_inhibit_hold.py`,
`tools/Send-InhibitHold.ps1`, `inhibit-agent`, unit tests under `tests/test_tx_inhibit_*`.

---

## 9. Cross-links

| Doc | Role |
|-----|------|
| wsjtx-inhibit `docs/TX_INHIBIT.md` | **Authority** — wire, leases, hang, glossary |
| wsjtx-inhibit `docs/INHIBIT_AGENT.md` | Standalone KEY agent |
| [wims_tx_inhibit.md](../plan/wims_tx_inhibit.md) | WIMS product / latency / KEY design (wire § superseded) |
| [wims_key_agent.md](../plan/wims_key_agent.md) | WIMS Key agent differences (target list, discovery) |
| [wims_design.md](../plan/wims_design.md) §2.14, §3.4.1 | Band policy + interlock |
| [wims_networking.md](../plan/wims_networking.md) | Plane A (2237) vs inhibit plane (22372) |
