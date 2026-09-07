#!/usr/bin/env bash
# install.sh — WIMS install / update for Linux (+ macOS with python3).
#
# Run from inside the cloned or unpacked tree (no auto-clone):
#
#     git clone https://github.com/wa1hco/WIMS.git
#     cd WIMS
#     ./install.sh
#
# Or after unpacking a GitHub Release ZIP:
#
#     unzip wims-0.1.0-tester.zip
#     cd wims-0.1.0-tester
#     ./install.sh
#
# Re-runnable. Stdlib-only — no venv, no pip.
# Sets up:
#   - Python ≥ 3.10 check
#   - import smoke for the wims package
#   - Desktop "WIMS" shortcut (unless --no-shortcut)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

WANT_SHORTCUT=1
for arg in "$@"; do
    case "$arg" in
        --no-shortcut) WANT_SHORTCUT=0 ;;
        -h|--help)
            echo "Usage: ./install.sh [--no-shortcut]"
            echo "  --no-shortcut  skip Desktop launcher icon"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: ./install.sh [--no-shortcut]" >&2
            exit 1
            ;;
    esac
done

if [ ! -f "$REPO_DIR/src/wims/__init__.py" ]; then
    echo "ERROR: not a WIMS tree (missing src/wims/__init__.py)." >&2
    echo "  Run this script from the repo root." >&2
    exit 1
fi

PYTHON_CMD="${WIMS_PYTHON:-python3}"
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    echo "ERROR: '$PYTHON_CMD' not found." >&2
    echo "  Install Python 3.10+ (Debian/Ubuntu: sudo apt install python3)." >&2
    echo "  Or set WIMS_PYTHON to the full path of a python3 binary." >&2
    exit 1
fi

"$PYTHON_CMD" -c '
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python {sys.version_info[:3]} found; WIMS needs >= 3.10.")
print(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} OK")
'

# Desktop launcher needs Tk. Warn only — server/solo still run without it.
if ! "$PYTHON_CMD" -c "import tkinter" >/dev/null 2>&1; then
    echo "WARNING: python3-tk not available (import tkinter failed)." >&2
    echo "  Desktop launcher needs it. Server/solo still work." >&2
    echo "  Debian/Ubuntu: sudo apt install python3-tk" >&2
fi

export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
VER="$("$PYTHON_CMD" -c 'import wims; print(wims.__version__)')"
echo "WIMS import OK (version $VER)"

if [ "$WANT_SHORTCUT" = "1" ]; then
    if [ -x "$REPO_DIR/scripts/install-wims-desktop.sh" ]; then
        echo "Installing Desktop shortcut ..."
        "$REPO_DIR/scripts/install-wims-desktop.sh" || {
            echo "WARNING: Desktop shortcut install failed (tk / desktop dir?)." >&2
            echo "  You can re-run: scripts/install-wims-desktop.sh" >&2
        }
    else
        echo "WARNING: scripts/install-wims-desktop.sh missing; skip shortcut." >&2
    fi
else
    echo "Skipping Desktop shortcut (--no-shortcut)."
fi

cat <<EOF

Install complete.

Start (pick one):
  Desktop icon:     WIMS
  GUI launcher:     PYTHONPATH=src $PYTHON_CMD -m wims
  Solo (one PC):    PYTHONPATH=src $PYTHON_CMD -m wims solo
  Site server:      PYTHONPATH=src $PYTHON_CMD -m wims server

Docs: INSTALL.md · docs/tester_quickstart.md
EOF
