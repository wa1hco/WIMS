#!/usr/bin/env bash

# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Home H0 Operate (Linux/macOS). Docs: docs/home_h0_h1.md
# WSJT-X: UDP Server 224.0.0.73:2237, Accept UDP requests ON.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found, so WIMS cannot start."
  echo "Install Python 3, then run this file again."
  echo "On Ubuntu: open a terminal here and install the python3 package."
  exit 1
fi

# 0 = port free, 10 = WIMS already serving, 11 = something else has the port.
set +e
"$PY" - << 'PY'
import json, socket, sys, urllib.request
port = 8787
s = socket.socket()
s.settimeout(0.4)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    sys.exit(0)
finally:
    s.close()
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.8) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
except Exception:
    data = {}
if data.get("ok") and data.get("role") == "wims-site-server":
    sys.exit(10)
sys.exit(11)
PY
code=$?
set -e
open_console() {
  url="http://localhost:8787/"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  fi
}
if [ "$code" -eq 10 ]; then
  echo "WIMS is already open. Showing the console."
  open_console
  exit 0
fi
if [ "$code" -eq 11 ]; then
  echo "Port 8787 is in use, but it is not WIMS."
  echo "Close the other program, or open the WIMS window if it is already running."
  echo "The console, when WIMS is up, is http://localhost:8787/"
  exit 1
fi
exec "$PY" -m wims.solo "$@"
