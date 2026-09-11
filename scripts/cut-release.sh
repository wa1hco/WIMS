#!/usr/bin/env bash
# Tag HEAD and push so Actions "Release" publishes GitHub Releases.
# Not run on every push — call when operators should see Update available.
#
# Usage:
#   scripts/cut-release.sh                 # tag v$(pyproject version)
#   scripts/cut-release.sh v1.0.1
#   scripts/cut-release.sh v1.0.1-tester
#   scripts/cut-release.sh v1.0.1-rc1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -n "${1:-}" ]; then
  TAG="$1"
  case "$TAG" in
    v*) ;;
    *) TAG="v$TAG" ;;
  esac
else
  BASE=$(python3 -c "import re; t=open('pyproject.toml').read(); m=re.search(r'(?m)^version\\s*=\\s*\\\"([^\\\"]+)\\\"', t); assert m; print(m.group(1))")
  TAG="v${BASE}"
fi

python3 scripts/packaging/write_manifest.py "${TAG#v}" --repo-root "$ROOT" >/dev/null

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "ERROR: tag $TAG already exists." >&2
  exit 1
fi

git tag -a "$TAG" -m "WIMS ${TAG#v}"
echo "Created $TAG on $(git rev-parse --short HEAD)"
echo "Publish: git push origin $TAG"
echo "  (Actions workflow Release builds zip/tar and creates the GitHub Release)"
if [ "${PUSH:-0}" = "1" ]; then
  git push origin "$TAG"
  echo "Pushed $TAG"
fi
