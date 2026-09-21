#!/usr/bin/env bash

# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Home H1 Inhibit: KEY → localhost digi gate (no site server).
# Needs patched WSJT-X TxInhibit on UDP 22372.
# Example: WIMS_KEY_DEVICE=/dev/ttyUSB0 ./scripts/start-wims-inhibit-home.sh
# Docs: docs/home_h0_h1.md

set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
PY="${PYTHON:-python3}"
TARGETS="${WIMS_KEY_TARGETS:-127.0.0.1:22372}"

echo "WIMS home Inhibit (H1): targets=${TARGETS} device=${WIMS_KEY_DEVICE:-'(unset)'}"
exec "$PY" -m wims.seat --key --targets "$TARGETS" "$@"
