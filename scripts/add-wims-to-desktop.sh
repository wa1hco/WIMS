#!/usr/bin/env bash
# Put a WIMS icon on the desktop and in the application menu.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found, so the WIMS icon could not be created."
  echo "Install Python 3 (and the window library, python3-tk), then run this file again."
  exit 1
fi
exec "$PY" -m wims.launcher --install-shortcut
