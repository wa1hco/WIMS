#!/usr/bin/env bash
# See whether the logs on this PC agree. Reads logs. Does not change them.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found, so Check logs cannot start."
  echo "Install Python 3, then run this file again."
  exit 1
fi
exec "$PY" -m wims.logaudit.page
