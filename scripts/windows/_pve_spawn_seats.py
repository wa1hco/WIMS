#!/usr/bin/env python3
"""Clone Win10Tiny (100) into IC-9700 + Flex radio seats on Proxmox."""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = "192.168.1.4"
NODE = "pve"
SRC = 100
IC_ID = 110
FLEX_ID = 111
IC_NAME = "wims-ic9700"
FLEX_NAME = "wims-flex8600m"
STORAGE = "nvme-thin"
CTX = ssl._create_unverified_context()


class PVE:
    def __init__(self, password: str) -> None:
        self.base = f"https://{HOST}:8006/api2/json"
        data = urllib.parse.urlencode(
            {"username": "root@pam", "password": password}
        ).encode()
        req = urllib.request.Request(
            f"{self.base}/access/ticket", data=data, method="POST"
        )
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            body = json.loads(r.read().decode())["data"]
        self.ticket = body["ticket"]
        self.csrf = body["CSRFPreventionToken"]

    def request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        body = None
        headers = {"Cookie": f"PVEAuthCookie={self.ticket}"}
        if data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["CSRFPreventionToken"] = self.csrf
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=300) as r:
                raw = r.read().decode()
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {err}") from e
        return json.loads(raw) if raw else {}

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, data: dict | None = None) -> dict:
        return self.request("POST", path, data or {})

    def put(self, path: str, data: dict | None = None) -> dict:
        return self.request("PUT", path, data or {})

    def wait_task(self, upid: str, label: str, timeout: int = 3600) -> None:
        print(f"  waiting for {label}: {upid}")
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.get(
                f"/nodes/{NODE}/tasks/{urllib.parse.quote(upid, safe='')}/status"
            )["data"]
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise RuntimeError(f"Task failed ({label}): {st}")
                print(f"  OK: {label}")
                return
            time.sleep(3)
        raise RuntimeError(f"Timeout waiting for {label}")


def vm_exists(pve: PVE, vmid: int) -> bool:
    try:
        pve.get(f"/nodes/{NODE}/qemu/{vmid}/status/current")
        return True
    except RuntimeError as e:
        if "404" in str(e) or "does not exist" in str(e).lower():
            return False
        # list and check
        vms = pve.get(f"/nodes/{NODE}/qemu")["data"]
        return any(v["vmid"] == vmid for v in vms)


def clone_vm(pve: PVE, newid: int, name: str) -> None:
    if vm_exists(pve, newid):
        print(f"VM {newid} already exists — skip clone of {name}")
        return
    print(f"Cloning {SRC} -> {newid} ({name}) full on {STORAGE}...")
    res = pve.post(
        f"/nodes/{NODE}/qemu/{SRC}/clone",
        {
            "newid": newid,
            "name": name,
            "full": 1,
            "storage": STORAGE,
            "target": NODE,
        },
    )
    upid = res["data"]
    pve.wait_task(upid, f"clone {name}")


def set_net_new_mac(pve: PVE, vmid: int) -> None:
    """Force a new virtio/e1000 NIC so DHCP does not share the gold MAC.

    Omit hwaddr so Proxmox assigns a fresh MAC.
    """
    cfg = pve.get(f"/nodes/{NODE}/qemu/{vmid}/config")["data"]
    # Match gold bridge/firewall but new auto MAC; keep e1000 for Win10 drivers already present
    pve.put(
        f"/nodes/{NODE}/qemu/{vmid}/config",
        {"net0": "e1000,bridge=vmbr0,firewall=1"},
    )
    new = pve.get(f"/nodes/{NODE}/qemu/{vmid}/config")["data"].get("net0")
    print(f"  VM {vmid} net0 -> {new} (was {cfg.get('net0')})")


def delete_keys(pve: PVE, vmid: int, keys: list[str]) -> None:
    cfg = pve.get(f"/nodes/{NODE}/qemu/{vmid}/config")["data"]
    present = [k for k in keys if k in cfg]
    if not present:
        print(f"  VM {vmid}: no keys to delete among {keys}")
        return
    print(f"  VM {vmid}: delete {present}")
    pve.put(
        f"/nodes/{NODE}/qemu/{vmid}/config",
        {"delete": ",".join(present)},
    )


def ensure_usb_ic(pve: PVE) -> None:
    """IC seat gets the three IC-9700 host USB ports used on gold."""
    # Gold currently: usb0=host=4-5.2, usb1=host=4-5.3, usb2=host=4-5.4
    mapping = {
        "usb0": "host=4-5.2",
        "usb1": "host=4-5.3",
        "usb2": "host=4-5.4",
    }
    print(f"  VM {IC_ID}: set USB {mapping}")
    pve.put(f"/nodes/{NODE}/qemu/{IC_ID}/config", mapping)


def start_vm(pve: PVE, vmid: int) -> None:
    st = pve.get(f"/nodes/{NODE}/qemu/{vmid}/status/current")["data"]
    if st.get("status") == "running":
        print(f"  VM {vmid} already running")
        return
    print(f"  starting VM {vmid}...")
    res = pve.post(f"/nodes/{NODE}/qemu/{vmid}/status/start")
    upid = res.get("data")
    if upid:
        pve.wait_task(upid, f"start {vmid}", timeout=300)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: _pve_spawn_seats.py <password>")
        return 2
    password = sys.argv[1]
    pve = PVE(password)

    src = pve.get(f"/nodes/{NODE}/qemu/{SRC}/status/current")["data"]
    print(f"Source VM {SRC}: status={src.get('status')} name=Win10Tiny")

    clone_vm(pve, IC_ID, IC_NAME)
    clone_vm(pve, FLEX_ID, FLEX_NAME)

    print("Configuring network (new MACs)...")
    set_net_new_mac(pve, IC_ID)
    set_net_new_mac(pve, FLEX_ID)

    print("USB: only on IC seat; strip from Flex + gold...")
    delete_keys(pve, FLEX_ID, ["usb0", "usb1", "usb2"])
    # Free USB from gold so IC clone can claim host ports
    delete_keys(pve, SRC, ["usb0", "usb1", "usb2"])
    ensure_usb_ic(pve)

    # Agent + onboot helpful for seats
    for vmid in (IC_ID, FLEX_ID):
        pve.put(
            f"/nodes/{NODE}/qemu/{vmid}/config",
            {"agent": "enabled=1", "onboot": 0, "name": IC_NAME if vmid == IC_ID else FLEX_NAME},
        )

    print("Starting radio seats...")
    start_vm(pve, IC_ID)
    start_vm(pve, FLEX_ID)

    print("\n=== Final status ===")
    for vmid in (SRC, IC_ID, FLEX_ID):
        st = pve.get(f"/nodes/{NODE}/qemu/{vmid}/status/current")["data"]
        cfg = pve.get(f"/nodes/{NODE}/qemu/{vmid}/config")["data"]
        usbs = {k: cfg[k] for k in cfg if k.startswith("usb")}
        print(
            f"VM {vmid} {(cfg.get('name') or ''):16s} status={st.get('status'):8s} "
            f"net0={cfg.get('net0')} usb={usbs or '-'}"
        )
    print("\nDone. After Windows boots on clones, RDP/console and run:")
    print(r"  cd C:\Users\W2SZ\WIMS\scripts\windows")
    print(r"  Set-SeatAfterClone.cmd wims-ic9700 wims-ic9700-FT8")
    print(r"  Set-SeatAfterClone.cmd wims-flex8600m wims-flex8600m-FT8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
