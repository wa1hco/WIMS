#!/usr/bin/env python3
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Program FT230X internal MTP so a Keyline board self-identifies over USB.

Factory FT230X strings are generic (FTDI / FT230X Basic UART / unique
FT-serial). inhibit-agent and the udev rules look for WA1HCO / Keyline, so
each board needs:

  manufacturer  FTDI WA1HCO
  product       FT230X Keyline
  serial        KL0001 .. KL00xx   (unique, labeled on the enclosure)

VID:PID stays 0403:6015 so the stock ftdi_sio / FTDI VCP driver binds.
CTS/RTS invert and CBUS are left at factory defaults.

Ubuntu's pyftdi 0.54 cannot *write* FT230X string descriptors (upstream
issue #365: unconditional EEPROM mirroring). This tool applies that
one-method fix, then writes only the 16-bit words that actually changed.

Plug **one** board at a time.

  python3 flash_keyline.py list
  python3 flash_keyline.py read
  python3 flash_keyline.py program KL0001          # dry-run
  python3 flash_keyline.py program KL0001 --write  # commit to MTP
  python3 flash_keyline.py next --write            # next free KLxxxx
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import os
import re
import sys
import time
from pathlib import Path

from pyftdi.eeprom import FtdiEeprom, FtdiEepromError
from pyftdi.ftdi import Ftdi
from pyftdi.usbtools import UsbTools

# Data stays next to the boards (fleet.csv, backups). This file lives in tools/dev.
_EEPROM_DIR = Path(__file__).resolve().parents[2] / "hardware" / "keyline_interface" / "eeprom"
BACKUP_DIR = _EEPROM_DIR / "backups"
FLEET_CSV = _EEPROM_DIR / "fleet.csv"

VID = 0x0403
PID = 0x6015
MANUFACTURER = "FTDI WA1HCO"
PRODUCT = "FT230X Keyline"
SERIAL_RE = re.compile(r"^KL\d{4}$")
RESERVED_BYTES = range(0x80, 0x9E)  # FT230X non-writable config (word 0x40-0x4E)


# ---------------------------------------------------------------------------
# pyftdi 0.54 FT230X workaround (https://github.com/eblot/pyftdi/issues/365)
# ---------------------------------------------------------------------------

def _generate_var_strings(self, fill=True) -> None:
    """Upstream fix: do not touch mirror_sector unless mirroring is on."""
    stream = bytearray()
    dynpos = self._PROPERTIES[self.device_version].dynoff
    if dynpos > self._size:
        dynpos = 0x40
    data_pos = dynpos
    tbl_pos = 0x0e
    if self.is_mirroring_enabled:
        s1_vstr_start = data_pos - self.mirror_sector
        tbl_sector2_pos = self.mirror_sector + tbl_pos
    for name in self.VAR_STRINGS:
        try:
            ustr = self._config[name].encode("utf-16le")
        except KeyError:
            ustr = b""
        length = len(ustr) + 2
        stream.append(length)
        stream.append(0x03)
        stream.extend(ustr)
        self._eeprom[tbl_pos] = data_pos | 0x80
        tbl_pos += 1
        if self.is_mirroring_enabled:
            self._eeprom[tbl_sector2_pos] = data_pos
            tbl_sector2_pos += 1
        self._eeprom[tbl_pos] = length
        tbl_pos += 1
        if self.is_mirroring_enabled:
            self._eeprom[tbl_sector2_pos] = length
            tbl_sector2_pos += 1
        data_pos += length
    if self.is_mirroring_enabled:
        self._eeprom[s1_vstr_start : s1_vstr_start + len(stream)] = stream
    self._eeprom[dynpos : dynpos + len(stream)] = stream
    mtp = self._ftdi.device_version == 0x1000
    crc_pos = 0x100 if mtp else self._size
    rem = crc_pos - (dynpos + len(stream))
    if rem < 0:
        oversize = (-rem + 2) // 2
        raise FtdiEepromError(
            f"Cannot fit strings into EEPROM, {oversize} oversize characters"
        )
    if fill:
        self._eeprom[dynpos + len(stream) : crc_pos] = bytes(rem)
        if self.is_mirroring_enabled:
            crc_s1_pos = self.mirror_sector
            self._eeprom[s1_vstr_start + len(stream) : crc_s1_pos] = bytes(rem)


FtdiEeprom._generate_var_strings = _generate_var_strings


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def list_ft230() -> list:
    return Ftdi.list_devices("ftdi://ftdi:230x/")


def require_one(url: str | None):
    found = list_ft230()
    if url:
        return url, found
    if not found:
        sys.exit("no FT230X on the bus — plug one Keyline board")
    if len(found) > 1:
        print("multiple FT230X devices; unplug extras or pass --url:", file=sys.stderr)
        for desc, _iface in found:
            print(f"  ftdi://ftdi:230x:{desc.sn}/1  ({desc.description})",
                  file=sys.stderr)
        sys.exit(2)
    desc, _iface = found[0]
    return f"ftdi://ftdi:230x:{desc.sn}/1", found


def print_list() -> int:
    found = list_ft230()
    if not found:
        print("no FT230X on the bus")
        return 1
    for desc, _iface in found:
        tag = ""
        blob = f"{desc.description or ''} {desc.sn or ''}".upper()
        if "KEYLINE" in blob or "WA1HCO" in blob:
            tag = "  [Keyline]"
        print(f"ftdi://ftdi:230x:{desc.sn}/1  {desc.description}  SN={desc.sn}{tag}")
    return 0


# ---------------------------------------------------------------------------
# EEPROM helpers
# ---------------------------------------------------------------------------

def open_eeprom(url: str) -> FtdiEeprom:
    ee = FtdiEeprom()
    ee.open(url)
    if ee.device_version != 0x1000:
        ee.close()
        sys.exit(f"{url} is not an FT230X/FT-X (ver {ee.device_version:#06x})")
    if int(ee.vendor_id) != VID or int(ee.product_id) != PID:
        ee.close()
        sys.exit(
            f"{url} VID:PID {ee.vendor_id}:{ee.product_id} "
            f"is not {VID:#06x}:{PID:#06x} — refusing"
        )
    return ee


def snapshot(ee: FtdiEeprom) -> dict:
    return {
        "manufacturer": ee.manufacturer,
        "product": ee.product,
        "serial": ee.serial,
        "vendor_id": int(ee.vendor_id),
        "product_id": int(ee.product_id),
        "invert_CTS": bool(ee.invert_CTS),
        "invert_RTS": bool(ee.invert_RTS),
        "channel_a_driver": str(ee.channel_a_driver),
        "power_max": int(ee.power_max),
    }


def dump_read(url: str) -> int:
    ee = open_eeprom(url)
    try:
        print(f"url            {url}")
        print(f"manufacturer   {ee.manufacturer}")
        print(f"product        {ee.product}")
        print(f"serial         {ee.serial}")
        print(f"vid:pid        {int(ee.vendor_id):#06x}:{int(ee.product_id):#06x}")
        print(f"invert CTS/RTS {ee.invert_CTS}/{ee.invert_RTS}")
        print(f"VCP            {ee.channel_a_driver}")
        print(f"power_max      {ee.power_max} mA")
        print(f"eeprom bytes   {ee.size}  crc_ok={ee._valid}")
    finally:
        ee.close()
    return 0


def save_backup(raw: bytes, factory_serial: str) -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    path = BACKUP_DIR / f"{factory_serial}.bin"
    if not path.exists():
        path.write_bytes(raw)
        print(f"backup {path}")
    else:
        print(f"backup already present {path}")
    return path


def changed_words(before: bytes, after: bytes) -> list[tuple[int, bytes]]:
    if len(before) != len(after):
        raise RuntimeError("eeprom size changed in memory")
    words = []
    i = 0
    n = len(after)
    while i < n:
        addr = i & ~1
        old = before[addr : addr + 2]
        new = after[addr : addr + 2]
        if old != new:
            if addr in RESERVED_BYTES or addr + 1 in RESERVED_BYTES:
                raise RuntimeError(
                    f"refusing to write reserved MTP byte 0x{addr:02x}"
                )
            words.append((addr, bytes(new)))
            i = addr + 2
        else:
            i += 1
    return words


def write_words(ee: FtdiEeprom, words: list[tuple[int, bytes]], dry_run: bool) -> None:
    for addr, data in words:
        ee._ftdi._write_eeprom_raw(addr, data, dry_run=dry_run)


def wait_sysfs(serial: str, timeout_s: float = 8.0) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for info in iter_sysfs():
            if (
                info.get("serial") == serial
                and info.get("manufacturer") == MANUFACTURER
                and info.get("product") == PRODUCT
            ):
                return info
        time.sleep(0.2)
    return None


def iter_sysfs() -> list[dict]:
    root = Path("/sys/bus/usb/devices")
    out = []
    if not root.exists():
        return out
    for dev in root.iterdir():
        vid = _sysfs_text(dev / "idVendor")
        pid = _sysfs_text(dev / "idProduct")
        if vid == f"{VID:04x}" and pid == f"{PID:04x}":
            out.append(
                {
                    "path": str(dev),
                    "manufacturer": _sysfs_text(dev / "manufacturer"),
                    "product": _sysfs_text(dev / "product"),
                    "serial": _sysfs_text(dev / "serial"),
                }
            )
    return out


def _sysfs_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# linux/usbdevice_fs.h _IO('U', 22/23) — drops the kernel's cached
# iManufacturer/iProduct/iSerial so lsusb re-reads them from the chip.
USBDEVFS_DISCONNECT = 0x5516
USBDEVFS_CONNECT = 0x5517


def usbfs_reconnect(bus: int, addr: int) -> None:
    path = f"/dev/bus/usb/{bus:03d}/{addr:03d}"
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.ioctl(fd, USBDEVFS_DISCONNECT, 0)
        fcntl.ioctl(fd, USBDEVFS_CONNECT, 0)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Fleet log / serial allocation
# ---------------------------------------------------------------------------

def load_fleet() -> list[dict]:
    if not FLEET_CSV.exists():
        return []
    with FLEET_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


def used_serials(rows: list[dict]) -> set[str]:
    return {r["serial"] for r in rows if r.get("serial")}


def next_serial(rows: list[dict]) -> str:
    used = used_serials(rows)
    for n in range(1, 10000):
        s = f"KL{n:04d}"
        if s not in used:
            return s
    raise RuntimeError("KL0001-KL9999 exhausted")


def append_fleet(row: dict) -> None:
    fields = [
        "serial",
        "factory_serial",
        "manufacturer",
        "product",
        "programmed_utc",
    ]
    rows = load_fleet()
    replaced = False
    for i, existing in enumerate(rows):
        if existing.get("serial") == row["serial"]:
            if not existing.get("factory_serial") or existing["factory_serial"] == row["serial"]:
                row["factory_serial"] = existing.get("factory_serial") or row["factory_serial"]
            else:
                row["factory_serial"] = existing["factory_serial"]
            rows[i] = row
            replaced = True
            break
    if not replaced:
        rows.append(row)
    with FLEET_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def valid_serial(serial: str) -> str:
    if not SERIAL_RE.match(serial):
        sys.exit(f"serial must match KL + 4 digits (got {serial!r})")
    return serial


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------

def program(url: str, serial: str, write: bool, force: bool) -> int:
    serial = valid_serial(serial)
    bus = addr = None
    factory_serial = ""
    ee = open_eeprom(url)
    try:
        before_cfg = snapshot(ee)
        before = bytes(ee._eeprom)
        factory_serial = before_cfg["serial"]
        print(
            f"current  {before_cfg['manufacturer']!r}  "
            f"{before_cfg['product']!r}  SN={factory_serial}"
        )
        already = (
            before_cfg["manufacturer"] == MANUFACTURER
            and before_cfg["product"] == PRODUCT
            and SERIAL_RE.match(before_cfg["serial"] or "")
        )
        if already and before_cfg["serial"] == serial and not force:
            print(f"already programmed as {serial}; pass --force to rewrite")
            return 0
        if already and before_cfg["serial"] != serial and not force:
            sys.exit(
                f"already Keyline {before_cfg['serial']}; "
                f"pass --force to reassign {serial}"
            )
        if before_cfg["invert_CTS"] or before_cfg["invert_RTS"]:
            sys.exit("invert_CTS/RTS is set — refusing (Keyline polarity would flip)")

        fleet = load_fleet()
        taken = used_serials(fleet)
        same_board = serial == before_cfg["serial"] or serial in {
            r.get("serial")
            for r in fleet
            if r.get("factory_serial") == factory_serial
            or r.get("serial") == factory_serial
        }
        if serial in taken and not same_board and not force:
            sys.exit(f"{serial} already in {FLEET_CSV.name}; pick another or --force")

        ee.set_manufacturer_name(MANUFACTURER)
        ee.set_product_name(PRODUCT)
        ee.set_serial_number(serial)
        ee.sync()  # rebuild image + CRC in RAM; chip is untouched
        after = bytes(ee._eeprom)
        after_cfg = snapshot(ee)

        if after_cfg["vendor_id"] != VID or after_cfg["product_id"] != PID:
            sys.exit("internal error: VID/PID would change")
        if after_cfg["invert_CTS"] or after_cfg["invert_RTS"]:
            sys.exit("internal error: invert flags would change")
        if after_cfg["manufacturer"] != MANUFACTURER or after_cfg["product"] != PRODUCT:
            sys.exit("internal error: strings did not take")
        if after_cfg["serial"] != serial:
            sys.exit("internal error: serial did not take")

        words = changed_words(before, after)
        print(
            f"target   {MANUFACTURER!r}  {PRODUCT!r}  SN={serial}  "
            f"({len(words)} words, {2*len(words)} bytes)"
        )
        print("words   " + ", ".join(f"0x{a:02x}" for a, _ in words))

        if not write:
            print("dry-run only; pass --write to commit to MTP")
            return 0

        save_backup(before, factory_serial or "unknown")
        write_words(ee, words, dry_run=False)
        verify = bytes(ee._ftdi.read_eeprom(0, len(after)))
        mismatch = [
            i for i in range(len(after))
            if i not in RESERVED_BYTES and verify[i] != after[i]
        ]
        if mismatch:
            pos = mismatch[0]
            sys.exit(f"MTP verify failed @ 0x{pos:02x}")
        print("MTP verify ok")
        usb_dev = getattr(ee._ftdi, "_usb_dev", None)
        bus = getattr(usb_dev, "bus", None)
        addr = getattr(usb_dev, "address", None)
        try:
            ee.reset_device()
        except Exception as exc:
            print(f"usb reset ({exc})")
    finally:
        try:
            ee.close()
        except Exception:
            pass
        UsbTools.flush_cache()

    if bus is not None and addr is not None:
        try:
            usbfs_reconnect(bus, addr)
            print(f"usb re-enumerate {bus:03d}/{addr:03d}")
        except OSError as exc:
            print(f"usb re-enumerate failed ({exc}); unplug/replug")

    append_fleet(
        {
            "serial": serial,
            "factory_serial": factory_serial,
            "manufacturer": MANUFACTURER,
            "product": PRODUCT,
            "programmed_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
    )
    print(f"logged   {FLEET_CSV}")

    info = wait_sysfs(serial)
    if info:
        print(
            f"usb      {info['manufacturer']!r}  {info['product']!r}  "
            f"SN={info['serial']}"
        )
    else:
        print(
            "kernel USB cache may still show the old strings — "
            "unplug/replug, then: python3 flash_keyline.py read"
        )
    print(f"label this board {serial} and unplug before the next one")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "--url",
        help="pyftdi URL (default: the only FT230X on the bus)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show FT230X devices")
    sub.add_parser("read", help="dump current USB identity")

    sp = sub.add_parser("program", help="set Keyline strings + this serial")
    sp.add_argument("serial", help="KLnnnn, e.g. KL0001")
    sp.add_argument("--write", action="store_true", help="commit to MTP (else dry-run)")
    sp.add_argument("--force", action="store_true", help="rewrite an already-Keyline board")

    sn = sub.add_parser("next", help="program the next free KLnnnn from fleet.csv")
    sn.add_argument("--write", action="store_true", help="commit to MTP (else dry-run)")
    sn.add_argument("--force", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "list":
        return print_list()

    url, _found = require_one(args.url)
    if args.cmd == "read":
        return dump_read(url)
    if args.cmd == "program":
        return program(url, args.serial, args.write, args.force)
    if args.cmd == "next":
        serial = next_serial(load_fleet())
        print(f"next serial {serial}")
        return program(url, serial, args.write, args.force)
    p.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
