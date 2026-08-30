#!/usr/bin/env bash
# Refresh docs/manual/images/*.png from docs/manual/shots.json
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
exec "${PYTHON:-python3}" "$ROOT/scripts/capture_user_manual_shots.py" "$@"
