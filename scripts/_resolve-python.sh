# Finds Python for the other Linux start files.
# Sets PY. Shows a plain message and returns 1 when Python is missing or too old.

_wims_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$_wims_here/_say.sh"

_wims_next="${WIMS_NEXT_CLICK:-WIMS}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  wims_say "WIMS" "Python was not found, so WIMS cannot start.

Install Python 3.10 or newer (the python3 package).
Also install python3-tk (on Fedora, python3-tkinter).
Then double-click ${_wims_next} again."
  return 1 2>/dev/null || exit 1
fi

if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  _wims_ver="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "older than 3.10")"
  wims_say "WIMS" "This PC has Python ${_wims_ver}. WIMS needs Python 3.10 or newer.

Install a newer Python 3, then double-click ${_wims_next} again."
  return 1 2>/dev/null || exit 1
fi
