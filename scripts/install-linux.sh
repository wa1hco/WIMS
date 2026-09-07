#!/usr/bin/env bash
# install-linux.sh — Linux entry (design PR 4).
# Delegates to the repo-root install.sh (map144-style UX).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/install.sh" "$@"
