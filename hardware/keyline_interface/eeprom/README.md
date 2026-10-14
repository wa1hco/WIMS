# Keyline FT230X identity (MTP / EEPROM)

Factory FT230X chips enumerate as `FTDI` / `FT230X Basic UART` with a unique
FT-serial (`DU0FDKHO`, …). That is enough for `/dev/ttyUSB*` uniqueness, but
**not** enough for software to recognise a Keyline among other FTDI ports.

`inhibit-agent` auto-picks a port whose USB strings contain **WA1HCO** or
**Keyline**. The udev rule matches the same strings.

## Identity we program

| Field | Value | Why |
|---|---|---|
| VID:PID | `0403:6015` | stock FT230X — do **not** change (drivers) |
| Manufacturer | `FTDI WA1HCO` | [wims_tx_inhibit.md](../../../docs/plan/wims_tx_inhibit.md) §4.1.2 |
| Product | `FT230X Keyline` | same pattern as SO4R `FT230X SO4R Port n`; udev `*Keyline*` |
| Serial | `KL0001` … | unique, labeled on the enclosure |
| CTS/RTS invert | factory (off) | Keyline J1 polarity |
| CBUS | factory | pins unused on this board |

MTP is rated 2,000 write cycles. A bad checksum falls back to FTDI defaults
(not a brick). Still: **one board at a time**, dry-run first, `--write` to
commit.

## Procedure (10-board run)

Plug **one** board at a time. Program the serial that matches the unit in
your hand — do not use `next` for a numbered pile.

```bash
cd /home/jeff/ham/wims/hardware/keyline_interface/eeprom

python3 flash_keyline.py list
python3 flash_keyline.py read

# board #1 in hand:
python3 flash_keyline.py program KL0001          # dry-run
python3 flash_keyline.py program KL0001 --write  # commit
```

Then unplug, plug board #2, `program KL0002 --write`, and so on.

`fleet.csv` logs `KLnnnn` ↔ factory serial. Factory images land in
`backups/<factory-serial>.bin`.

After a reset the tty udev name becomes:

```text
/dev/serial/by-id/usb-FTDI_WA1HCO_FT230X_Keyline_KL0001-if00-port0
```

Install the udev rule so ModemManager does not open the port (and so
`/dev/keyline-KL0001` exists):

```bash
sudo cp ../99-keyline.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Windows equivalent is FT_PROG with the same four string fields; keep VID:PID.
