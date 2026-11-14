#!/usr/bin/env bash
# Install WS Hub: put the program in its place and the icon on the desktop.
# The desktop file "Install WS Hub" runs this with bash, so the executable
# bit is optional.
#
# A downloaded release (no .git) is copied to ~/.local/share/ws-hub
# ($XDG_DATA_HOME/ws-hub when set), replacing an older copy there, so the
# download can be deleted afterwards. A git checkout stays where it is.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Zip and some archive tools drop the executable bit. Put it back on the
# files a later double-click runs.
repair_wims_exec_bits() {
  local f
  for f in \
    "$ROOT/scripts/Install WS Hub.desktop" \
    "$ROOT/scripts/add-wims-to-desktop.sh" \
    "$ROOT/scripts/install-linux.sh" \
    "$ROOT/scripts/start-wims.sh" \
    "$ROOT/scripts/start-wims-solo.sh" \
    "$ROOT/scripts/start-wims-inhibit-home.sh" \
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
export WIMS_NEXT_CLICK="Install WS Hub"
# shellcheck disable=SC1091
source "$ROOT/scripts/_resolve-python.sh" || exit 1

if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
  wims_say "WS Hub" "WS Hub needs the Python window library.

Install python3-tk, then double-click Install WS Hub again.
On Fedora, the package is python3-tkinter."
  exit 1
fi

# Where the program lives from now on: this folder for a git checkout,
# otherwise the fixed install place. Runs without the window library.
if ! HOME_DIR="$("$PY" "$ROOT/src/wims/launcher/install_tree.py" "$ROOT")" \
    || [ -z "$HOME_DIR" ] || [ ! -f "$HOME_DIR/scripts/start-wims.sh" ]; then
  wims_say "WS Hub" "WS Hub could not copy itself into your home folder.

Check that there is free space, then double-click Install WS Hub again."
  exit 1
fi

if ! /bin/bash "$HOME_DIR/scripts/start-wims.sh" --install-shortcut; then
  wims_say "WS Hub" "WS Hub could not add the desktop icon.

Double-click Install WS Hub again."
  exit 1
fi

if [ "$HOME_DIR" = "$ROOT" ]; then
  wims_say "WS Hub" "WS Hub is on the desktop and in the app menu.

Double-click WS Hub."
else
  wims_say "WS Hub" "WS Hub is installed, on the desktop, and in the app menu.

It lives in $HOME_DIR.
You can delete the downloaded folder now.

Double-click WS Hub."
fi
