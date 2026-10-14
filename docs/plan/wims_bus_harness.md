# WIMS message-bus migration — harness plan

**Status:** active plan (no production cutover)  
**Date:** 2026-09-17  
**Related:** session architecture notes; `wims_design.md` §5; unit tests under `tests/unit/`; `testbed/simulators/`

## 1. Goal

Prove a pub/sub fabric for WIMS **before** any contest path depends on it.

- Keep current plane-A / HTTP / seat paths as the **default live drivers**.
- Build contracts + Linux-first automated stress.
- Windows / Proxmox / full N1MM lab are **gates**, not the daily loop.
- Those Windows gates use the named lab VMs in §7.1 (`W10VM-50`, `W10VM-144`).
- Inhibit **actuation** (type-18) stays direct UDP in all phases.

## 2. Non-goals (this document)

- Choosing MQTT vs NATS as a final product lock (harness should allow a thin bus adapter interface).
- Big-bang rewrite of Operate / seat.
- Replacing RDP remote-op workflows.
- Three-node broker clusters.

## 3. Principles

1. **Harness first, cutover last.**
2. **One vertical at a time** (see phases). Feature flag off by default.
3. **Same invariants as today:** ≤1 TX per resource; KEY holds without Operate; one digi writer into each chosen N1MM.
4. **Fail the bus on purpose** in tests; inhibit and local seat Log must still meet their bar.
5. Prefer **in-process and multi-process on one Linux host** over VM bridges for CI-style runs.

## 4. Bus adapter contract (test double first)

Define a narrow interface early (names illustrative):

| Method | Purpose |
|--------|---------|
| `publish(topic, payload, retain=False)` | Edges and Operate commands |
| `subscribe(topic_filter, handler)` | Operate, Inhibit, Dashboard |
| `request(topic, payload, timeout)` | Optional later (Work ack) |
| `connect(url)` / `close()` | Lifecycle |

**Implementations to support in harness:**

| Impl | Role |
|------|------|
| `MemoryBus` | In-process unit/integration (no broker) |
| `ProcessBus` | Multi-process on localhost (real broker or loopback bridge) |
| Later: `MqttBus` / `NatsBus` | One chosen product behind the same interface |

All scenario tests run against `MemoryBus` first. A subset runs against `ProcessBus`.

## 5. Topic sketch (v0 — stable enough to test)

Use string topics; payloads JSON (or msgpack later). Instance ids = WSJT `--rig-name`.

| Topic | Publisher | Subscribers | Notes |
|-------|-----------|-------------|-------|
| `digi/{id}/decode` | WSJT agent | Operate | High rate |
| `digi/{id}/status` | WSJT agent | Operate, Inhibit, Dashboard | Retained if bus supports it |
| `digi/{id}/logged` | WSJT agent | N1MM agent / audit | |
| `digi/{id}/inhibit_cap` | WSJT agent | Inhibit | From type-17 / caps |
| `log/{logger_id}/contact` | N1MM agent | Operate | |
| `log/{logger_id}/snapshot` | N1MM agent | Operate | Occasional |
| `n1mm/{logger_id}/radioinfo` | N1MM agent | Inhibit, Dashboard | Live band, etc. |
| `inhibit/{key_id}/targets` | Policy or Inhibit | Inhibit | **Who to hold** — not band-only |
| `inhibit/{key_id}/state` | Inhibit | Dashboard, Operate | KEY up/down |
| `operate/{env_id}/work` | Operate | WSJT agent | Command |
| `operate/{env_id}/halt` | Operate | WSJT agent | Command |
| `presence/{host_id}` | Every WIMS | All | Broker URL, roles, health |
| `broker/advertise` | Broker host | All | URL + epoch |

Type-18 datagrams are **not** bus payloads.

## 6. Simulator pieces (extend existing)

| Piece | Exists today | Harness need |
|-------|--------------|--------------|
| WSJT emulator | `testbed/simulators/emulator.py` | Publish via bus adapter; multi-id; Reply/Halt reaction |
| N1MM stub | Partial / design | Emit contacts + accept TCP log; publish `log/...` |
| Type-18 sink | Unit tests around KEY | Record holds; assert target set + timing |
| Operate headless | Server state / roster tests | Subscribe filters; score cache; Work emit |
| Broker controller | None | Start/stop/move for `ProcessBus` tests |
| Presence faker | `test_presence.py` | Election / prefer-move scenarios |

## 7. Scenario matrix × pass criteria

### A. Correctness (MemoryBus)

| ID | Scenario | Pass |
|----|----------|------|
| A1 | N digi ids publish decodes; Operate env filters one band/station set | Only subscribed ids appear in roster input |
| A2 | Two Operate envs, disjoint TX resources; both Work | Each command reaches only its resource; no cross-talk |
| A3 | Two Operates claim same TX resource | Exactly one Work owner (v1 reject or lock); never two Reply |
| A4 | Log snapshot + contacts → Operate score cache | Needed/dupe matches golden fixture |
| A5 | Inhibit sub to explicit station list (multi-band mix) | Type-18 sink sees only listed TX-capable ids |
| A6 | FT8 specialist: three Operate envs, three resources | Independent subscriptions; three Work paths isolated |
| A7 | FD-style: two logger ids on same band | Contacts tagged by `logger_id`; caches do not merge writers |

### B. Failure / autonomy (MemoryBus + ProcessBus)

| ID | Scenario | Pass |
|----|----------|------|
| B1 | Bus stopped; KEY footswitch sim | Holds still applied from last target set or local discovery path under test |
| B2 | Broker restart mid-flood | Clients reconnect; no duplicate Work storm; roster recovers |
| B3 | First-up broker election race (two starters) | One advertise wins; loser connects; single URL |
| B4 | Prefer-move broker to second host | New advertise epoch; all reconnect; old quiet |
| B5 | WSJT agent crash/restart | Status retained/recovered; Operate resyncs without manual clear |
| B6 | Dropped contact events | Snapshot rebuild restores score cache within bound |

### C. Stress (ProcessBus, Linux one host)

| ID | Scenario | Pass |
|----|----------|------|
| C1 | Decode flood (configurable Hz × N ids) for T seconds | No crash; lag bound documented; drop policy explicit |
| C2 | M Operate subscribers with different filters | CPU/RAM bound documented; filters correct under load |
| C3 | Inhibit target churn while KEY toggling | No stuck hold; clear-all on KEY down still works |
| C4 | Sustained Work/Halt churn on one resource | Arbiter invariant; emulator TX edges coherent |

### D. Shadow (optional, after A–C green)

| ID | Scenario | Pass |
|----|----------|------|
| D1 | Emulator → plane A **and** bus; compare decode streams | Set equality (id, msg, time bucket) within tolerance |
| D2 | Live lab capture replay into both paths | Same |

Shadow never drives Work until explicitly enabled.

### E. Windows / field gates (manual or semi-auto)

**Lab seats (required for E):** Proxmox guests **`W10VM-50`** and **`W10VM-144`**.  
Do not treat a single Windows box as enough for multi-seat bus gates.

| ID | Scenario | Pass |
|----|----------|------|
| E1 | **`W10VM-50`**: WSJT agent + Memory/Process bus client | Install + smoke on that guest |
| E1b | **`W10VM-144`**: same as E1 on the second guest | Install + smoke; both seats healthy |
| E2 | Two-seat bus path: agents on **50** and **144**; Operate (Linux or one guest) | Decodes / Work / Halt reach the correct seat only |
| E3 | Tailscale remote Operate → on-site agent on either VM | Commands work; inhibit remains on-site |
| E4 | Dummy-load single instance (either VM) | Go/no-go before multi-TX |

### 7.1 Standard Windows bus lab

| Host | Role in bus tests | Notes |
|------|-------------------|-------|
| **W10VM-50** | Digi / N1MM seat (50 MHz class) | Existing clone pack: `flex50`; station name / `--rig-name` often `W10VM-50` |
| **W10VM-144** | Digi / N1MM seat (144 MHz class) | Existing clone pack: `ic9700-144`; station name / `--rig-name` often `W10VM-144` |
| Linux contest NIC / host | Broker stress, Operate head, harness runner | Daily A–C stay here; VMs are gates |

Both VMs must be **up and on the contest LAN** for E2 (and for any go/no-go that claims multi-seat bus readiness).  
Seat personalization: `scripts/windows/Set-SeatAfterClone.cmd`.  
Historical N1MM bind notes on these guests: `wims_networking.md` §4.9.1.

## 8. Phased delivery

| Phase | Deliverable | Exit criteria |
|-------|-------------|---------------|
| **P0** | This plan + `Bus` protocol + `MemoryBus` | Unit tests for pub/sub/retain semantics |
| **P1** | Emulator → MemoryBus → headless Operate filter | A1–A3 green |
| **P2** | Log stub → score cache | A4, A7 green |
| **P3** | Inhibit targets topic → type-18 sink | A5, B1 green |
| **P4** | `ProcessBus` + broker start/stop | B2–B4, C1–C2 green on Linux CI/dev |
| **P5** | Feature flag: optional bus **publish** beside live path | D1 on lab emulator |
| **P6** | Feature flag: Operate **read** from bus (one env) | Shadow equal; flag default off |
| **P7** | Field gate E1–E4 on **W10VM-50** + **W10VM-144** | Written go/no-go |

No phase removes plane-A listeners until P6+ and a named contest rehearsal.

## 9. What runs where (daily vs rare)

| Loop | Environment | Frequency |
|------|-------------|-----------|
| `MemoryBus` scenarios A/B | Linux, `tests/` | Every change |
| `ProcessBus` stress C | Linux one host | Nightly or pre-merge |
| Shadow D | Lab | When touching ingest |
| Windows E1 / E1b | **W10VM-50**, then **W10VM-144** | Milestone |
| Two-seat E2 | Both VMs + Linux Operate/broker as needed | Milestone (required for multi-seat claim) |
| VPN E3 | When remote-op work is in scope | Milestone |
| On-air E4 | Mountain/trailer | Before trusting bus Work |

## 10. Bug classes to watch (explicit)

| New class | Detection |
|-----------|-----------|
| Duplicate decodes (mcast + bus) | Shadow diff; single-path flag |
| Split Work owners | A3 assert |
| Stale inhibit targets after move | B4 + C3 |
| Score cache drift vs N1MM | B6 + audit counters |
| Broker flap → command replay | B2 idempotent Work/Halt |
| VPN sees roster, KEY on wrong side | E3 placement checks |
| Cross-seat Work on wrong VM | E2 (50 vs 144) |

## 11. Success definition for “ready to trust”

1. A1–A7, B1–B6 green on `MemoryBus`.  
2. C1–C2 green on `ProcessBus` with published limits.  
3. D1 clean on emulator for one contest profile.  
4. E1 + E1b smoke on **W10VM-50** and **W10VM-144**.  
5. E2 two-seat path green with both VMs up.  
6. Inhibit B1 proven with bus killed.  
7. Default install still uses **pre-bus** Operate path until an explicit release note flips a flag.

## 12. Immediate next implementation steps (when coding starts)

1. Add `src/wims/bus/` with protocol + `MemoryBus` + tests.  
2. Thin harness runner script under `testbed/bus/` (scenarios A1–A3).  
3. Do **not** wire server ingest to the bus yet.  
4. Keep packaging stdlib-only until P4 chooses a broker wheel/bundle strategy.

## 13. Open choices

| Choice | Recommendation |
|--------|----------------|
| **Product bus** | **MQTT** (Mosquitto broker + Paho client) — see §13.1 |
| Operate port split | Orthogonal; can proceed in parallel docs |
| Shared-trx mute/CAT | Under Inhibit role unless radio discovery forces N1MM agent |

### 13.1 Which message bus (recommendation)

| Candidate | Verdict for WIMS contest LAN |
|-----------|------------------------------|
| **MQTT (Mosquitto + Paho)** | **Choose for ProcessBus / production fabric** |
| NATS | Strong alternate if Work request-reply becomes the pain point |
| ZeroMQ | Brokerless; weaker fit now that election + remotes + retained Status matter |
| Kafka / RabbitMQ | Too heavy |

**Why MQTT**

- Highest mindshare; easy to explain and debug (`mosquitto_sub`).
- **Retained** messages fit digi Status / presence / broker advertise.
- Topic wildcards match `digi/+/decode`, `log/+/contact`.
- **Unicast** — works over Tailscale/VPN where multicast often fails.
- One broker on preferred PC matches “min setup, max reliability.”
- Python: `paho-mqtt` is mature.
- Windows: ship or start `mosquitto.exe` with the site/broker host.

**Why not NATS first:** slightly better req/reply and raw speed; less universal tooling for tired ops; MQTT retained + topics cover Operate/Inhibit needs.

**Approach (unchanged):**

1. **P0–P1:** `Bus` protocol + **`MemoryBus`** only (no Mosquitto in the daily loop).  
2. **P4:** `MqttBus` + local Mosquitto for `ProcessBus` stress.  
3. Production path stays off the bus until shadow/flags say go.  
4. Revisit NATS only if MQTT ack/command patterns prove awkward.

## 14. Related Operate feature (backlog — not bus-blocking)

**Even/odd dual WSJT (K1EP):** two isolated digi instances work opposite FT8 even/odd periods.

- Roster: add **even/odd** column.  
- UI: show stations **eligible for the alternate interval** (other instance’s slot).  
- Inhibit: unchanged.  
- Arbiter: may later allow an even/odd **pair** without treating simultaneous Work as a conflict if TX slots cannot overlap; track as separate design beat.

Harness add when built: two slot-filtered Operates; assert non-overlapping TX windows; KEY still holds both.
