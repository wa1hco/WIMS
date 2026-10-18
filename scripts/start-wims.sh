#!/usr/bin/env bash

# Open the WIMS window. The desktop icon runs this file.
# If that window is already open, this brings it forward.
# Python and the program path are set here. The operator does not type them.

set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/_resolve-python.sh"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m wims.launcher "$@"
