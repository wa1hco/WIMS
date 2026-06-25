#!/usr/bin/env bash
#
# WIMS smoke validation — proves the project runs end-to-end on this machine.
#
# Honors CLAUDE.md "verify live, not by assertion": it runs the self-contained
# unit suites AND a live no-RF run (server ingests the emulator's multicast →
# state → SSE → JSON). No network hardware, no N1MM, no pytest required.
#
# Usage:   scripts/validate.sh
# Exit:    0 = all checks passed, non-zero = first failing check's status.
#
# Throwaway logs land in ./scratch/validate/ (gitignored).

set -u

# --- locate repo root (script lives in scripts/) ---------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python3}"

LOGDIR="$ROOT/scratch/validate"
mkdir -p "$LOGDIR"

# --- live-run knobs (overridable from the environment) ---------------------
IFACE="${WIMS_IFACE:-127.0.0.1}"
HTTP_PORT="${WIMS_HTTP_PORT:-8799}"
INSTANCES="${WIMS_INSTANCES:-ROY-6M:50313000,CHIP-2M:144174000,TRL-432:432174000}"

# --- pretty output ---------------------------------------------------------
PASS=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf '\n=== %s ===\n' "$1"; }

# --- background-process cleanup (always runs) ------------------------------
SRV_PID=""; EMU_PID=""
cleanup() {
    [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null
    [ -n "$EMU_PID" ] && kill "$EMU_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
hdr "1. Unit suites (tests/unit/test_*.py)"
for t in tests/unit/test_*.py; do
    name="$(basename "$t")"
    if "$PY" "$t" > "$LOGDIR/$name.log" 2>&1; then
        ok "$name"
    else
        bad "$name  (see $LOGDIR/$name.log)"
        tail -15 "$LOGDIR/$name.log" | sed 's/^/        /'
    fi
done

# ---------------------------------------------------------------------------
hdr "2. Module imports"
if "$PY" - > "$LOGDIR/imports.log" 2>&1 <<'PY'; then
import wims
from wims.server import app, state
from wims.udp import messages, sink, controller, encode, activity, monitor
from wims.interlock import arbiter
from wims.engine import scoring, roster
from wims.discovery import fleet
from wims.state import logstore
from wims.integrations import wsjtx_config
from wims.integrations.n1mm import qso, logdb, listener
from wims.core import bands
print("all imports OK")
PY
    ok "every wims module imports"
else
    bad "module import failed (see $LOGDIR/imports.log)"
    tail -15 "$LOGDIR/imports.log" | sed 's/^/        /'
fi

# ---------------------------------------------------------------------------
hdr "3. Interlock bench (zero TX overlap)"
if timeout 40 "$PY" testbed/interlock_bench.py > "$LOGDIR/interlock.log" 2>&1 \
        && grep -q "RESULT: PASS" "$LOGDIR/interlock.log"; then
    ok "$(grep -m1 'overlap violations' "$LOGDIR/interlock.log" | sed 's/^ *//')"
else
    bad "interlock bench (see $LOGDIR/interlock.log)"
    tail -15 "$LOGDIR/interlock.log" | sed 's/^/        /'
fi

# ---------------------------------------------------------------------------
hdr "4. Live end-to-end (server + emulator → SSE → JSON)"
"$PY" src/wims/server/app.py --iface "$IFACE" --http-port "$HTTP_PORT" \
    --no-seed --refresh 1 > "$LOGDIR/server.log" 2>&1 &
SRV_PID=$!
"$PY" testbed/simulators/emulator.py --iface "$IFACE" \
    --instances "$INSTANCES" > "$LOGDIR/emulator.log" 2>&1 &
EMU_PID=$!

# wait for HTTP to come up (a few decode cycles need to flow first)
up=""
for _ in $(seq 1 15); do
    if curl -s -o /dev/null --max-time 1 "http://$IFACE:$HTTP_PORT/healthz" 2>/dev/null; then
        up=1; break
    fi
    sleep 1
done

if [ -z "$up" ]; then
    bad "server never answered /healthz (see $LOGDIR/server.log)"
    tail -15 "$LOGDIR/server.log" | sed 's/^/        /'
else
    ok "server up (/healthz 200)"
    # let a couple of emulator cycles populate state, then grab one SSE frame
    sleep 5
    curl -s --max-time 5 "http://$IFACE:$HTTP_PORT/events" 2>/dev/null \
        | grep -m1 '^data:' | sed 's/^data: //' > "$LOGDIR/frame.json"

    if "$PY" - "$LOGDIR/frame.json" "$INSTANCES" > "$LOGDIR/frame_check.log" 2>&1 <<'PY'; then
import json, sys
frame_path, instances_arg = sys.argv[1], sys.argv[2]
raw = open(frame_path).read().strip()
if not raw:
    print("no SSE frame captured"); sys.exit(1)
d = json.loads(raw)

expected_keys = {"instances", "loggers", "rx", "interlock",
                 "roster", "activity", "decodes", "n1mm_sync"}
missing = expected_keys - set(d)
if missing:
    print("state contract missing keys:", sorted(missing)); sys.exit(1)

ids = {i.get("id") or i.get("name") or i.get("call") for i in d["instances"]}
wanted = {spec.split(":")[0] for spec in instances_arg.split(",")}
absent = wanted - ids
if absent:
    print("emulated instances not in live state:", sorted(absent),
          "| saw:", sorted(ids)); sys.exit(1)

print(f"state OK: {len(d['instances'])} instances, "
      f"{len(d['decodes'])} decodes, "
      f"{d['roster'].get('count', 0)} roster candidates; "
      f"emulated {sorted(wanted)} all present")
PY
        ok "$(cat "$LOGDIR/frame_check.log")"
    else
        bad "live state check (see $LOGDIR/frame_check.log)"
        sed 's/^/        /' "$LOGDIR/frame_check.log"
    fi
fi

# ---------------------------------------------------------------------------
hdr "Summary"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "  WIMS validates on this machine."
