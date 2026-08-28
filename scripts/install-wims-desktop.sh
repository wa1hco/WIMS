#!/usr/bin/env bash
# Install a Desktop "WIMS" launcher (Linux) with the project icon when available.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
PY="${PYTHON:-python3}"
exec "$PY" -m wims.launcher --install-shortcut
