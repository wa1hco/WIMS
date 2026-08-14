#!/usr/bin/env bash
# WIMS — start site server + UI fleet simulator (no RF).
#
# Usage:
#   scripts/run_ui_fleet.sh              # full multi-band backdrop
#   scripts/run_ui_fleet.sh --six-only   # only 3×6m → N1MM-50 on SSB-PC
#
# Then open: http://localhost:8787/status
# Stop: Ctrl-C (kills both).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python3}"
IFACE="${WIMS_IFACE:-127.0.0.1}"
HTTP="${WIMS_HTTP_PORT:-8787}"

EXTRA_FLEET=()
for a in "$@"; do
  EXTRA_FLEET+=("$a")
done

cleanup() {
  [[ -n "${SRV_PID:-}" ]] && kill "$SRV_PID" 2>/dev/null || true
  [[ -n "${FLEET_PID:-}" ]] && kill "$FLEET_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "=== WIMS UI fleet lab ==="
echo "  iface=$IFACE  console=http://localhost:${HTTP}/status"
echo "  6m:  3×WSJT → N1MM-50 @ SSB PC"
echo "  2m:  FT8 + MSK144 WSJT → N1MM-144; SSB PC has N1MM, no WSJT"
echo "  222/432: one PC each, FT8 ↔ SSB (mode switch)"
echo

"$PY" -m wims.server.app \
  --iface "$IFACE" \
  --http-port "$HTTP" \
  --no-presence \
  --no-seed \
  --no-tx \
  >"scratch/ui_fleet_server.log" 2>&1 &
SRV_PID=$!

# Wait for server
for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${HTTP}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.15
done
if ! curl -sf "http://127.0.0.1:${HTTP}/healthz" >/dev/null 2>&1; then
  echo "server failed to start — see scratch/ui_fleet_server.log" >&2
  exit 1
fi
echo "  server up (pid $SRV_PID)  log: scratch/ui_fleet_server.log"

mkdir -p scratch
"$PY" testbed/simulators/fleet_ui.py --iface "$IFACE" "${EXTRA_FLEET[@]}" &
FLEET_PID=$!
echo "  fleet_ui (pid $FLEET_PID)"
echo
echo "  Open:  http://localhost:${HTTP}/status"
echo "  Also:  http://localhost:${HTTP}/"
echo "  Ctrl-C to stop both."
echo

wait "$FLEET_PID"
