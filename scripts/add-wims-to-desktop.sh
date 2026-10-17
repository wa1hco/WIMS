#!/usr/bin/env bash
# Put a WIMS icon on the desktop and in the application menu.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/start-wims.sh" --install-shortcut
