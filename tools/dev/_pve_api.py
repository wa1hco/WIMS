#!/usr/bin/env python3
"""Minimal Proxmox VE API helper (password auth). Not for production secrets storage."""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://192.168.1.4:8006/api2/json"
CTX = ssl._create_unverified_context()


class PVE:
    def __init__(self, host: str, user: str, password: str) -> None:
        self.base = f"https://{host}:8006/api2/json"
        self.ticket = ""
        self.csrf = ""
        self._login(user, password)

    def _login(self, user: str, password: str) -> None:
        data = urllib.parse.urlencode({"username": user, "password": password}).encode()
        req = urllib.request.Request(f"{self.base}/access/ticket", data=data, method="POST")
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
            with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
                raw = r.read().decode()
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")
            raise SystemExit(f"HTTP {e.code} {method} {path}: {err}") from e
        if not raw:
            return {}
        return json.loads(raw)

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, data: dict | None = None) -> dict:
        return self.request("POST", path, data or {})

    def put(self, path: str, data: dict | None = None) -> dict:
        return self.request("PUT", path, data or {})

    def wait_task(self, node: str, upid: str, timeout: int = 1800) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.get(f"/nodes/{node}/tasks/{urllib.parse.quote(upid, safe='')}/status")
            data = st.get("data") or {}
            if data.get("status") == "stopped":
                if data.get("exitstatus") != "OK":
                    raise SystemExit(f"Task failed: {data}")
                return data
            time.sleep(2)
        raise SystemExit(f"Task timeout: {upid}")


def cmd_list(pve: PVE) -> None:
    nodes = pve.get("/nodes")["data"]
    print("NODES:", ", ".join(n["node"] for n in nodes))
    for node in nodes:
        n = node["node"]
        print(f"\n=== node {n} ===")
        vms = pve.get(f"/nodes/{n}/qemu")["data"]
        for v in sorted(vms, key=lambda x: x["vmid"]):
            mem_g = (v.get("maxmem") or 0) // (1024**3)
            print(
                f"VM {v['vmid']:4d}  {(v.get('name') or '?'):24s}  "
                f"status={v.get('status'):8s}  template={v.get('template', 0)}  "
                f"mem={mem_g}G  cpus={v.get('cpus')}"
            )
            cfg = pve.get(f"/nodes/{n}/qemu/{v['vmid']}/config")["data"]
            nets = {k: cfg[k] for k in cfg if k.startswith("net")}
            usbs = {k: cfg[k] for k in cfg if k.startswith("usb") or k == "hostpci0"}
            print(f"       net={nets}")
            if usbs:
                print(f"       usb={usbs}")
            if cfg.get("agent"):
                print(f"       agent={cfg.get('agent')}")
        stor = pve.get(f"/nodes/{n}/storage")["data"]
        print("\nSTORAGE:")
        for s in stor:
            if not s.get("active"):
                continue
            avail = (s.get("avail") or 0) // (1024**3)
            total = (s.get("total") or 0) // (1024**3)
            print(f"  {s['storage']:20s} type={s.get('type'):8s} {avail}G free / {total}G  content={s.get('content')}")
        try:
            usb = pve.get(f"/nodes/{n}/hardware/usb")["data"]
            print("\nHOST USB:")
            for u in usb:
                print(f"  bus={u.get('bus')} port={u.get('port')} dev={u.get('dev')} vendid={u.get('vendid')} prodid={u.get('prodid')} {u.get('manufacturer','')} {u.get('product','')} class={u.get('class')}")
        except SystemExit as e:
            print("HOST USB list failed:", e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.1.4")
    ap.add_argument("--user", default="root@pam")
    ap.add_argument("--password", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    args = ap.parse_args()
    pve = PVE(args.host, args.user, args.password)
    if args.cmd == "list":
        cmd_list(pve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
