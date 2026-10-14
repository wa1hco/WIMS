# Decision: IF→RF mapping is per seat, off by default

**Status:** adopted 2026-10-14
**Supersedes:** the default-on rule in
[2026-09-12](2026-09-12-transverter-if-and-n1mm-khz.md) (microwave kHz / 10 Hz
unit rules in that decision are unchanged).

## Context

WIMS mapped every 28.000–29.700 MHz dial to 432 and every 21.000–24.000 MHz
dial to 222 (`WIMS_TRANSVERTER` defaulted on). That matches Roy’s 222 radio
(CAT at 21 MHz) and 432 transverter (CAT at 28 MHz). It does **not** match a
Flex / SmartSDR seat: an XVTR slice already reports RF, so a real 10 m dial
at 28.074 MHz was labeled 70 cm.

The owner ran 2 m and 10 m WSJT-X on one Flex. WIMS showed the 10 m decodes
as 70 cm. No environment variable should be required to get the common case
right.

## Rule

1. **Default is RF.** A dial is labeled as heard. 28.074 MHz → **10m**.
   21.174 MHz → **15m**. Already-RF VHF/UHF/microwave is unchanged.
2. **Opt in per id**, not a global switch. `if_seats.json` lists WSJT-X
   UDP ids (`--rig-name`, with or without a `WSJT-X - ` prefix) and N1MM
   StationName / NetBIOS values that report IF:
   - 21.000–24.000 MHz → +201 MHz (**222** / 1.25m)
   - 28.000–29.700 MHz → +404 MHz (**432** / 70cm)
   Match is case-insensitive. `ROY-432` and `WSJT-X - ROY-432` are the same
   seat. An unmarked neighbor on the same server is not mapped.
3. **Where it applies.** WSJT-X Status (the band on decodes) and N1MM
   RadioInfo / ADIF `BAND`+`FREQ` both consult the list. N1MM’s Band
   *column* (MHz: 28, 10000, …) is still not an IF dial.
4. **File location** (same pattern as `last_log.json`):
   - Linux/macOS: `$XDG_CONFIG_HOME/wims/if_seats.json` or `~/.config/wims/…`
   - Windows: `%APPDATA%\wims\if_seats.json`
   - Tests: `WIMS_IF_SEATS_FILE`
   The site server’s file labels fleet decodes. The log agent on a seat
   reads **that PC’s** file for live band and ADIF rewrite. One host running
   both shares one file.
5. **Edit it on Setup** (`/setup`): checkbox per heard WSJT-X id and N1MM
   station, plus a box to add an id that is not on the wire yet. The seat
   agent page (`http://127.0.0.1:8790/`) edits the file on that PC.
6. **`WIMS_TRANSVERTER` stays as an override, not a requirement.** Unset →
   the file (default off). `1` / `on` forces mapping for every seat (old
   behavior). `0` / `off` forces mapping off even for listed ids.

## Not this

Do not infer IF from the dial alone. 28 MHz is a real band. Do not require
the operator to remember an environment variable for Flex, Icom+wfview, or
any other radio that already reports RF.
