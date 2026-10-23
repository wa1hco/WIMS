#!/usr/bin/env bash
# Put a WIMS icon on the desktop and in the application menu.
# The desktop file runs this with bash, so the executable bit is optional.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Zip and some archive tools drop the executable bit. Put it back on the
# files a later double-click runs.
repair_wims_exec_bits() {
  local f
  for f in \
    "$ROOT/install.sh" \
    "$ROOT/scripts/Add WIMS to Desktop.desktop" \
    "$ROOT/scripts/add-wims-to-desktop.sh" \
    "$ROOT/scripts/install-linux.sh" \
    "$ROOT/scripts/start-wims.sh" \
    "$ROOT/scripts/start-wims-solo.sh" \
    "$ROOT/scripts/start-wims-inhibit-home.sh" \
    "$ROOT/scripts/Check logs.sh" \
    "$ROOT/scripts/_resolve-python.sh" \
    "$ROOT/scripts/_say.sh"
  do
    if [ -f "$f" ]; then
      chmod a+x "$f" 2>/dev/null || chmod u+x "$f" || true
    fi
  done
}
repair_wims_exec_bits

# shellcheck disable=SC1091
source "$ROOT/scripts/_say.sh"
export WIMS_NEXT_CLICK="Add WIMS to Desktop"
# shellcheck disable=SC1091
source "$ROOT/scripts/_resolve-python.sh" || exit 1

if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
  wims_say "WIMS" "WIMS needs the Python window library.

Install python3-tk, then double-click Add WIMS to Desktop again.
On Fedora, the package is python3-tkinter."
  exit 1
fi

if ! "$ROOT/scripts/start-wims.sh" --install-shortcut; then
  wims_say "WIMS" "WIMS could not add the desktop icon.

Double-click Add WIMS to Desktop again."
  exit 1
fi

wims_say "WIMS" "WIMS is on the desktop and in the app menu.

Double-click WIMS."
