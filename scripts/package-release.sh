#!/usr/bin/env bash
# package-release.sh — build allow-list release artifacts (no hardware/).
#
# Design: docs/plan/wims_release_packages.md
#
# Usage:
#   scripts/package-release.sh [VERSION]
#
# VERSION is a release id: X.Y.Z | X.Y.Z-tester | X.Y.Z-rcN
# Numeric base must equal pyproject.toml / wims.__version__.
#
# Outputs (under dist/):
#   wims-<VERSION>-linux-x86_64.tar.gz
#   wims-<VERSION>-windows-x86_64.zip   (tree only; bundled runtime = later PR)
#   SHA256SUMS
#   manifest written inside each archive as manifest.json
#
# Env:
#   STRICT=1     — fail if working tree dirty
#   OUT_DIR      — default <repo>/dist
#   SKIP_WINDOWS=1 / SKIP_LINUX=1 — omit one platform artifact
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ "${STRICT:-0}" = "1" ]; then
    if [ -d "$ROOT/.git" ] && [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: working tree is dirty (STRICT=1)." >&2
        git status --porcelain >&2
        exit 1
    fi
fi

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    VERSION="$(python3 -c "import re,sys; sys.path.insert(0,'src'); import wims; print(wims.__version__)")"
fi

# Parse / validate via the shared helper (also writes a temp manifest).
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

python3 "$ROOT/scripts/packaging/write_manifest.py" "$VERSION" \
    -o "$STAGE/manifest.json" --repo-root "$ROOT"

DISPLAY=$(python3 -c "import json; print(json.load(open('$STAGE/manifest.json'))['version'])")
BASE=$(python3 -c "import json; print(json.load(open('$STAGE/manifest.json'))['version_base'])")
CHANNEL=$(python3 -c "import json; print(json.load(open('$STAGE/manifest.json'))['channel'])")
echo "Packaging display=$DISPLAY base=$BASE channel=$CHANNEL"

OUT_DIR="${OUT_DIR:-$ROOT/dist}"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/wims-"${DISPLAY}"-*.tar.gz \
      "$OUT_DIR"/wims-"${DISPLAY}"-*.zip \
      "$OUT_DIR"/SHA256SUMS

# ── Allow-list copy into a stage tree ─────────────────────────────────
# Normative include set from the design. Never copy hardware/, tests/,
# testbed/, .github/, dashboard/, scratch/, or __pycache__.
copy_tree() {
    local dest_root="$1"
    mkdir -p "$dest_root"

    # Top-level identity files
    for f in LICENSE pyproject.toml README.md INSTALL.md install.sh install.ps1; do
        if [ -e "$ROOT/$f" ]; then
            cp -a "$ROOT/$f" "$dest_root/"
        fi
    done

    # Directories (allow-list)
    for d in src scripts docs config; do
        if [ -d "$ROOT/$d" ]; then
            rsync -a \
                --exclude '__pycache__/' \
                --exclude '*.pyc' \
                --exclude 'install-log.txt' \
                --exclude 'python-path.txt' \
                --exclude 'seat-common.cmd' \
                --exclude 'seat-local.cmd' \
                --exclude 'radio-flex50.cmd' \
                --exclude 'radio-ic9700-144.cmd' \
                --exclude 'seat-startup-*.txt' \
                --exclude 'agent-daemon-log.txt' \
                "$ROOT/$d" "$dest_root/"
        fi
    done

    # Tired-op extract steps
    cat > "$dest_root/README-INSTALL.txt" <<EOF
WIMS ${DISPLAY} — quick install
================================

Windows (contest seat):
  1. Extract this folder to C:\\WIMS
  2. Double-click scripts\\windows\\Install-Wims.cmd (allow UAC)
  3. Start Desktop "WIMS"

  Bundled private Python runtime (offline) ships in a later release
  build. Until then Install uses/finds system Python >= 3.10.

Linux (personal laptop):
  1. Unpack the linux tar.gz
  2. ./install.sh
     (or: scripts/install-linux.sh)
  3. Start Desktop WIMS or: PYTHONPATH=src python3 -m wims solo

Docs: INSTALL.md · docs/tester_quickstart.md
Design: docs/plan/wims_release_packages.md

This package omits hardware/ (Keyline flash/KiCad). KEY *software*
(wims.seat --key) is included under src/.
EOF

    cp "$STAGE/manifest.json" "$dest_root/manifest.json"
}

deny_check() {
    local root="$1"
    local bad
    bad=$(find "$root" \( \
        -path '*/hardware/*' -o -path '*/hardware' -o \
        -path '*/tests/*' -o -path '*/tests' -o \
        -path '*/testbed/*' -o -path '*/testbed' -o \
        -path '*/.github/*' -o -path '*/.github' -o \
        -path '*/dashboard/*' -o -path '*/dashboard' -o \
        -path '*/scratch/*' -o -path '*/scratch' -o \
        -path '*/.git/*' -o -path '*/.git' -o \
        -name 'flash_keyline.py' -o \
        -name '99-keyline.rules' -o \
        -name '*.bin' -o \
        -name '__pycache__' \
        \) -print 2>/dev/null | head -50 || true)
    if [ -n "$bad" ]; then
        echo "ERROR: deny-list paths present in artifact stage:" >&2
        echo "$bad" >&2
        exit 1
    fi
    # Required paths
    for need in \
        "src/wims/__init__.py" \
        "src/wims/server/app.py" \
        "src/wims/server/static/ops.html" \
        "scripts/windows/Install-Wims.cmd" \
        "install.sh" \
        "INSTALL.md" \
        "manifest.json" \
        "README-INSTALL.txt"
    do
        if [ ! -e "$root/$need" ]; then
            echo "ERROR: missing required path: $need" >&2
            exit 1
        fi
    done
}

SUMS="$OUT_DIR/SHA256SUMS"
: > "$SUMS"

hash_file() {
    local f="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$OUT_DIR" && sha256sum "$(basename "$f")") >> "$SUMS"
    elif command -v shasum >/dev/null 2>&1; then
        (cd "$OUT_DIR" && shasum -a 256 "$(basename "$f")") >> "$SUMS"
    else
        local h
        h="$(openssl dgst -sha256 "$f" | awk '{print $NF}')"
        echo "$h  $(basename "$f")" >> "$SUMS"
    fi
}

# ── Linux tarball ─────────────────────────────────────────────────────
if [ "${SKIP_LINUX:-0}" != "1" ]; then
    LIN_PREFIX="wims-${DISPLAY}-linux-x86_64"
    LIN_STAGE="$STAGE/$LIN_PREFIX"
    copy_tree "$LIN_STAGE"
    deny_check "$LIN_STAGE"
    tar -C "$STAGE" -czf "$OUT_DIR/${LIN_PREFIX}.tar.gz" "$LIN_PREFIX"
    hash_file "$OUT_DIR/${LIN_PREFIX}.tar.gz"
    echo "Wrote $OUT_DIR/${LIN_PREFIX}.tar.gz"
fi

# ── Windows zip (tree only until runtime overlay lands) ───────────────
if [ "${SKIP_WINDOWS:-0}" != "1" ]; then
    WIN_PREFIX="wims-${DISPLAY}-windows-x86_64"
    WIN_STAGE="$STAGE/$WIN_PREFIX"
    copy_tree "$WIN_STAGE"
    # Placeholder notice — PR 5 adds runtime/python/
    mkdir -p "$WIN_STAGE/runtime"
    cat > "$WIN_STAGE/runtime/README.txt" <<EOF
Bundled embeddable CPython + Tk overlay is not in this build yet.
See docs/plan/wims_release_packages.md (PR 0 / PR 5).
Install-Wims.cmd will use system Python until runtime\\python\\ exists.
EOF
    deny_check "$WIN_STAGE"
    (
        cd "$STAGE"
        if command -v zip >/dev/null 2>&1; then
            zip -rq "$OUT_DIR/${WIN_PREFIX}.zip" "$WIN_PREFIX"
        else
            python3 - "$WIN_PREFIX" "$OUT_DIR/${WIN_PREFIX}.zip" <<'PY'
import sys, zipfile
from pathlib import Path
prefix, out = sys.argv[1], sys.argv[2]
root = Path(prefix)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            zf.write(path, path.as_posix())
PY
        fi
    )
    hash_file "$OUT_DIR/${WIN_PREFIX}.zip"
    echo "Wrote $OUT_DIR/${WIN_PREFIX}.zip"
fi

echo "Wrote $SUMS"
cat "$SUMS"
