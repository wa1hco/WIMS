#!/usr/bin/env bash

# Open the WIMS window. The desktop icon runs this file.
# If that window is already open, this brings it forward.
# Python and the program path are set here. The operator does not type them.

set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/_resolve-python.sh" || exit 1
# Installing the icon does not open the window. The window needs Tk.
if [ "${1:-}" != "--install-shortcut" ]; then
  if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
    wims_say "WIMS" "WIMS needs the Python window library.

Install python3-tk, then double-click WIMS again.
On Fedora, the package is python3-tkinter."
    exit 1
  fi
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m wims.launcher "$@"
