#!/usr/bin/env bash
# Run on the Proxmox host (192.168.1.4) as root after the golden Win10 guest is shut down.
# Converts the source VM into a template (once), then clones two radio seats.
#
# Usage:
#   chmod +x proxmox-clone-wims-seats.sh
#   ./proxmox-clone-wims-seats.sh <SOURCE_VMID> [STORAGE]
#
# Example:
#   ./proxmox-clone-wims-seats.sh 100 local-lvm
#
# After clones boot:
#   IC-9700 VM  — attach IC-9700 USB (CP210x + USB Audio) via Proxmox Hardware → USB Device
#   Flex VM     — no USB radio; install/use SmartSDR + DAX/CAT over LAN to the 8600M
#   Inside each guest run (elevated):
#     scripts\windows\Set-SeatAfterClone.cmd IC9700-50 IC9700-50-FT8
#     scripts\windows\Set-SeatAfterClone.cmd FLEX-8600M FLEX-8600M-FT8

set -euo pipefail

SRC_VMID="${1:-}"
STORAGE="${2:-}"
IC_VMID="${IC_VMID:-201}"
FLEX_VMID="${FLEX_VMID:-202}"
IC_NAME="${IC_NAME:-wims-ic9700}"
FLEX_NAME="${FLEX_NAME:-wims-flex8600m}"

if [[ -z "$SRC_VMID" ]]; then
  echo "Usage: $0 <SOURCE_VMID> [STORAGE]"
  echo "  SOURCE_VMID = current golden Win10 WIMS guest (must be stopped)"
  exit 1
fi

if ! command -v qm >/dev/null; then
  echo "ERROR: qm not found — run this on the Proxmox host, not inside the Windows guest."
  exit 1
fi

echo "== Source VM =="
qm status "$SRC_VMID" || { echo "VM $SRC_VMID not found"; exit 1; }
qm config "$SRC_VMID" | sed -n '1,80p'

status="$(qm status "$SRC_VMID" | awk '{print $2}')"
if [[ "$status" != "stopped" ]]; then
  echo
  echo "VM $SRC_VMID is '$status'. Shut it down cleanly from Windows first, then re-run."
  echo "  (Proxmox: qm shutdown $SRC_VMID   or guest Start → Shut down)"
  exit 1
fi

# Only convert once — if already a template, qm template fails; ignore that.
if qm config "$SRC_VMID" | grep -q '^template:'; then
  echo "VM $SRC_VMID is already a template."
else
  echo "Converting VM $SRC_VMID to template..."
  qm template "$SRC_VMID"
fi

clone_one() {
  local newid="$1" name="$2"
  if qm status "$newid" &>/dev/null; then
    echo "WARN: VMID $newid already exists — skip clone of $name"
    return 0
  fi
  echo "Cloning $SRC_VMID -> $newid ($name) full clone..."
  if [[ -n "$STORAGE" ]]; then
    qm clone "$SRC_VMID" "$newid" --name "$name" --full 1 --storage "$STORAGE"
  else
    qm clone "$SRC_VMID" "$newid" --name "$name" --full 1
  fi
  # New MAC so DHCP does not collide with the template/other clones
  qm set "$newid" --net0 virtio,bridge=vmbr0,firewall=0
  # Keep agent for clean shutdown / IP reporting
  qm set "$newid" --agent enabled=1
  echo "Created $newid ($name)"
}

clone_one "$IC_VMID" "$IC_NAME"
clone_one "$FLEX_VMID" "$FLEX_NAME"

echo
echo "== Next: USB for IC-9700 only =="
echo "List host USB (look for Silicon Labs CP210x / Icom / USB Audio):"
echo "  lsusb"
echo "  qm monitor $IC_VMID   then: info usbhost"
echo "Attach (example — use YOUR vendor:product or hostbus/hostport):"
echo "  qm set $IC_VMID -usb1 host=10c4:ea60   # typical Silicon Labs CP210x"
echo "  # or: qm set $IC_VMID -usb1 host=1-4   # host bus-port from lsusb -t"
echo
echo "Do NOT attach the IC-9700 USB to the Flex VM."
echo
echo "Start seats:"
echo "  qm start $IC_VMID"
echo "  qm start $FLEX_VMID"
echo
echo "Inside each Windows guest (elevated cmd):"
echo "  cd C:\\Users\\W2SZ\\WIMS\\scripts\\windows"
echo "  Set-SeatAfterClone.cmd IC9700-50 IC9700-50-FT8"
echo "  Set-SeatAfterClone.cmd FLEX-8600M FLEX-8600M-FT8"
echo
echo "Flex 8600M: point SmartSDR/DAX/CAT at the radio LAN IP; WSJT-X uses DAX audio + Flex CAT,"
echo "  still with UDP Server 224.0.0.73 and Outgoing interface = Ethernet."
echo "WIMS server must keep: --iface 192.168.1.119  (and ideally --n1mm-group 224.0.0.73)"
