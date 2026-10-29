# WIMS antenna agent — implementation brief

**Status:** Step 1 is implemented: read-only rotator heading on an antenna.
Tuner and switch are named and not built. Step 1 sends no motion and no set.  
**Decided by:** Jeff, WA1HCO (rotctld 2026-10-28; antenna agent 2026-10-29).  
**Source of truth:** [wims_design.md](wims_design.md) §2.10 (and §1.4 for what to verify on the wire).  
**Not a fleet plane:** [wims_networking.md](wims_networking.md) §3.4.

This note is the build brief, the same role as [wims_key_agent.md](wims_key_agent.md).
The design doc holds the decision. This file holds the antenna model, the
rotator session, the firmware proposal, the report, and the four rotator steps.

## Antenna agent

The seat agent’s antenna side manages the antennas on that PC. An antenna
has a name and a list of devices. A device kind is one of:

| Kind | What it is | This step |
|------|------------|-----------|
| `rotator` | Azimuth / elevation, hamlib rotctld | Read heading only (`p`) |
| `tuner` | Frequency-tuned antenna. The station’s SteppIR controller connects to the PC by USB serial | Not built. The antenna agent on that PC would own the serial port directly. Later: read frequency and state, then follow the radio’s frequency |
| `switch` | Antenna selection | Not built |

Today the station has rotators and SteppIR. This step reads rotators only.
There is no SteppIR session and no switch session. No device kind sends a
motion command or a set command.

The rest of this file is the rotator device: the rotctld session, safety,
and the four rotator build steps. Tuner and switch do not add a second
program. They are further devices on the same antenna list.

## What WIMS talks to

WIMS turns antennas itself.

| Path | Role |
|------|------|
| WSJT-X | No rotator control. Left out of this path. |
| Flex / SmartSDR | Not a rotator interface. |
| **hamlib rotctld, TCP** | The only control session the agent opens. |
| GS-232A/B serial | The controller’s serial dialect. **rotctld** is the program that opens the serial device. |

One controller of record per rotor (design §4.3): the owning agent, through
one rotctld session. The site server checks the claim and forwards a turn.
It never opens rotctld, including when server and agent share a PC.

The owner’s controller,
[wa1hco/rotator_controller](https://github.com/wa1hco/rotator_controller),
will speak GS-232A/B and rotctld. Firmware is not written yet. The feature
to add is [below](#name-and-announce-on-the-controller). A stock GS-232
controller behind stock rotctld is the fallback. The operator then confirms
the antenna name once.

## Three placements, one architecture

Same pieces everywhere: the per-PC agent, rotctld (or the controller’s own
rotctld), the site server, the Operate page. Only the PC changes.

```
Home (one PC)
  WSJT-X + agent (Antennas checked) + rotctld + site server + browser

Two PCs
  PC A: WSJT-X + agent + rotctld
  PC B: site server + browser          (no serial device, no rotctld port)

Multi-multi
  Each rotor’s seat: agent + rotctld
  One site server on the LAN
  Browsers on the LAN or remote, same Operate row
```

A turn always travels console → site server (claim) → owning agent → rotctld.
A heading always travels rotctld → agent → site server → Operate.

## Launcher checkbox

**This seat will run** grows a fifth checkbox, **Antennas**, next to N1MM,
WSJT-X, SSB/CW KEY, and Site server.

| Piece | Where |
|-------|--------|
| Row label, blurb, tip | `src/wims/launcher/home_panel.py` (`_INTENT_ROWS`) |
| Intent id, remembered set | `src/wims/launcher/assets.py` |

Suggested copy:

| | |
|--|--|
| Label | **Antennas** |
| Blurb | → Antenna side of the agent |
| Tip | This PC has antennas. WIMS reads each rotator’s heading and shows it on the console. |

Intent id: `antennas`, beside `n1mm`, `wsjt`, `ssb_cw`, and `server`.
Remembered in the same seat-intent file. Checking it turns on the antenna
side of the **one** agent process on that PC. It does not start a second
program. Unchecking stops that side. A PC with antennas and no WSJT-X still
gets the agent, antenna side only. The window remembers each antenna’s name
and, for a rotator device, the rotctld host and port. Those stay on this PC.

The operator never types a port, a device path, a flag, or an environment
variable. Those stay in **Developer** below.

## What the agent does

When **Antennas** is checked:

1. Find each rotor on this PC (announce, or a serial GS-232 device).
2. If the controller already speaks rotctld, connect. Do not start another
   rotctld, and do not open the serial port.
3. Otherwise start one rotctld per serial controller, listening on
   `127.0.0.1` and a port that is not the radio (see Developer).
4. Read the name and the heading.
5. Announce them on the agent report the PC already sends
   (`POST /api/agents/report`), beside the WSJT-X instances.
6. Execute a turn the site server has already claim-checked. Enforce soft
   az limits first. Stop on the safety rules below.

Two PCs reporting the same rotor name is a fault. The agent setup says:
“Two PCs see 6m beam. Leave Antennas checked on one of them.”

## Name, proposal, confirm once

The name lives in the controller when the firmware stores one. The agent
proposes a link from that name and from the instances on the same PC (a
name that says 6 m, and a 6 m instance on this seat, proposes
`flexA-6M`). The operator confirms once on the agent’s local setup.

Until the confirm, Operate shows the heading and the proposal as a
proposal. After the confirm, the console line is:

`6m beam, 212 deg, linked to instance flexA-6M`

On a multi-multi the confirmed link is saved in the site profile: a
`rotators.json` in the site server’s config directory (the same directory
as `contest_rules.json` and `cluster.json`). Every console reads that file
through the live state. On one PC that directory is the profile. The
operator does not edit the file.

A fixed beam has no row. Roster **Az DX** still shows the bearing to the
other station.

## Operate readout

One compact row per rotor on Operate, in the same live update as the
instances, so a remote browser shows it with no extra channel:

| Field | Meaning |
|-------|---------|
| Name | From the controller, or the name confirmed once |
| Current | Heading now, degrees |
| Target | Last commanded heading; blank when none |
| Turning | Yes while the rotor is moving |
| Link | The confirmed instance, or blank |

Roster **Az ant** mirrors Current on a linked instance. While Turning is
yes, Az ant is a different font (italic until a later face is chosen).
The state field is `rotator_moving`. The page does not compute motion
itself. **Az DX** stays the bearing from the instance grid to the DX grid.

A turn is an action on the linked instance under the existing soft claim
(design §4.5). The console that holds the claim may turn. A turn takes the
claim the way a Work click does. A band subscription does not. Before the
link is confirmed, the claim is on the rotor, with the same takeover, so
two consoles do not move one mast.

## Spot step

Build step 4. A click on a DX cluster spot prepares the linked instance:

- The site server asks that WSJT-X to QSY to the spot frequency on the UDP
  control path it already uses. The ask is claim-gated. It does not enable
  transmit.
- The server asks the owning agent to rotate to the great-circle bearing
  from the station grid to the spot grid.
- The instance shows **Tuning** while the radio or the rotor is still
  moving, and **Ready** when the dial is on the spot and the rotor has
  settled (a fixed beam is Ready on the radio alone).
- The operator starts the QSO by clicking the roster line. That click is
  still the only start. The spot click does not send Reply.

A spot with no grid stays selectable and is not rotated. The row says the
grid is missing.

**Score.** Spot rank then uses estimated retune time instead of only the
flat QSY cost. Time is the shortest-arc turn divided by the profile slew
rate (when the rate is unknown, use 6°/s and say the rate is assumed),
plus an allowance when the radio must change band or mode. Already on
frequency and already in the beam means no retune penalty. The hover shows
the breakdown (`retune 20s (turn 90°)`). Weights:
[scoring.md](scoring.md) **Retune time**. Until step 4, the flat `qsy`
cost stays as scored today.

## Safety

| Rule | Behavior |
|------|----------|
| Stop on disconnect | Lost rotctld session → agent treats the link as down and the controller stops because its client is gone. Agent loses the site server during a turn → agent sends stop. A console closing does not leave the mast moving. |
| Heartbeat | Position poll about once a second. Three misses → stop, link down, readout says the heading is unknown. The last number is not left up as if it were live. |
| No rotation during TX | Default on, changed in the agent’s local setup. While the linked instance is transmitting, do not start a turn, and stop one that is already moving. The row says the instance is transmitting. |
| Soft limits | Instance-profile az limits, applied in the agent before the position command. Outside the limits: refuse, in plain words. |
| One master | The owning agent’s rotctld session is the only commander. A second program on the serial port is a reported fault. |

## Build order

| Step | Ships | Acceptance |
|------|--------|------------|
| 1. Read-only heading | Find rotor, read name and heading, Operate row | A remote browser shows `6m beam` and the heading. No turn control. A pulled Ethernet cable or a stopped rotctld becomes “heading unknown” within a few seconds. |
| 2. Manual turn | Bearing or grid, and Stop, on that row | Target and Turning update. A second console is held to the claim rule. Stop leaves the rotor stopped. Soft-limit bearings are refused in words. |
| 3. Auto-association | Propose, confirm once, save | After one confirm, the line includes `linked to instance flexA-6M`. A second console shows that link without asking again. Multi-multi reload keeps it (`rotators.json`). |
| 4. Point at a spot | Spot click prepares; roster click starts | Spot click QSYs and turns, shows Tuning then Ready, and does not transmit. The roster click is what starts the QSO. Spot order follows retune time. |

## Name and announce on the controller

Firmware for
[wa1hco/rotator_controller](https://github.com/wa1hco/rotator_controller)
is not written. Add this, and nothing larger.

**Stored name.** One nonvolatile label, up to 24 characters (letters,
digits, spaces, hyphen). Example: `6m beam`. Set from the controller’s own
setup. WIMS only reads it, so a client cannot rename the antenna during a
contest.

**rotctld dialect.** Speak the hamlib rotctld command lines the agent
uses (`p` / `get_pos`, `P` / `set_pos`, `S` / `stop`, `_` / `get_info`).
`get_info` returns the stored name and then the usual `RPRT 0`. Send no
banner on connect; a banner breaks a stock hamlib client. When the TCP
client drops, stop the motors. When a move is underway and `get_pos` stops
for about 3 seconds, stop the motors.

**GS-232A/B on the serial port.** Normal motion commands, so stock rotctld
can drive the board with its GS-232A or GS-232B model (whichever
`rotctld -l` lists and the board implements). Add one whole-line command,
`ID` followed by CR, answered `ID6m beam` and CR. The parser treats `ID`
as one command, the way `C2` is one command. A controller that does not
know `ID` answers `?>`, and the agent asks the operator for the name once.

**LAN announce, only if the board has Ethernet.** Every 2 seconds, one
ASCII line, IPv4 subnet broadcast, UDP port **4534**:

```
WIMS-ROT 1 name=6m beam az=212.0 moving=0 rotctld=4535
```

`moving` is `0` or `1`. `rotctld` is the TCP port of this board’s rotctld
listener. This packet is not plane A (2237) and not plane E (8788). A
USB-serial board sends nothing; the agent on that PC starts rotctld.

The agent that hears an announce connects to that host and port. It does
not start a second rotctld.

## Developer

Operator setup does not use this section.

**Radio port.** Hamlib’s rotctld default TCP port is **4533**. On the
preferred Icom seat, wfview RigCtld already listens on **4533**
([wims_networking.md](wims_networking.md) §3.3). The agent binds the
rotctld it starts to `127.0.0.1`, first **4535**, then 4537, and so on.
If the only port on offer is 4533 and the radio is there, the agent says
the port belongs to the radio and does not connect.

**Commands the agent sends** (one per line, hamlib rotctld):

| Command | Use |
|---------|-----|
| `p` | Heading (and elevation when the hardware has it) |
| `P <az> <el>` | Move. Elevation `0` when the rotor has no elevation axis |
| `S` | Stop |
| `_` | `get_info` — the stored name, when this rotctld is the controller’s own |
| `w ID` | Raw GS-232 identity, only for stock rotctld in front of a serial controller |

The agent does not send `q` to a rotctld it expects to keep. Turning means
the controller’s moving flag is set, or the reported heading is still
outside a small deadband of the target.

**GS-232 model.** Pass rotctld the GS-232A or GS-232B model from
`rotctld -l`, matching the controller. Degree formatting and `C` versus
`C2` are rotctld’s problem. The product path does not grow a second
GS-232 parser for motion.

**Report** (added to the agent report that already carries `instances`).
Step 1 sends this shape. `target_az`, `moving`, and `instance` stay empty
until a later step. The console does not receive host, port, or a serial path.

```json
"antennas": [
  {
    "id": "ant-6m",
    "name": "6m beam",
    "devices": [
      {
        "id": "dev-rot",
        "kind": "rotator",
        "az": 212.0,
        "el": 0.0,
        "link": "up",
        "connection": "connected",
        "moving": false
      }
    ]
  }
]
```

`kind` is `rotator`, `tuner`, or `switch`. Only `rotator` is read now.
A tuner or a switch in the list is `connection: stale` and `Not read yet`
— the agent does not open a serial port for them. `link` is `up` or `down`.
`az` is null when the heading is unknown. `moving` is false in step 1.
`instance` (the confirmed WSJT-X link) is a later step.

**Site profile** `rotators.json` (schema 1), written by the server when a
confirm arrives:

```json
{
  "schema": 1,
  "links": [
    {
      "name": "6m beam",
      "instance": "flexA-6M",
      "agent_id": "the seat that confirmed"
    }
  ]
}
```

**Lab stand-in, not the operator path.** The tree already has an in-process
GS-232 helper (`integrations/rotator/`), a sim, and `WIMS_ROTATOR_*` on the
agent report. Those stay available for the lab. They are not how an
operator turns an antenna, and the product path must not open the serial
port with that helper while rotctld owns it. Do not add operator
instructions that set those variables.

## Cross-links

| Doc | Role |
|-----|------|
| [wims_design.md](wims_design.md) §2.10 | Decision |
| [wims_design.md](wims_design.md) §1.4 | What to verify on a live controller |
| [wims_design.md](wims_design.md) §4.5 | Claim that gates a turn |
| [wims_networking.md](wims_networking.md) §3.4 | Seat-local; not a plane; stay off port 4533 |
| [scoring.md](scoring.md) | Flat QSY cost now; retune time at step 4 |
