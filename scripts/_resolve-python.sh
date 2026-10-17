# Finds Python for the other Linux start files.
# Sets PY. Prints a plain message and returns 1 when Python is missing.
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found, so WIMS cannot start."
  echo "Install Python 3, then try again."
  echo "On Ubuntu: install the python3 package, and python3-tk for the WIMS window."
  return 1 2>/dev/null || exit 1
fi
