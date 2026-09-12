#!/usr/bin/env bash
# One-shot setup so `make pdf` works on a normal Linux/macOS box.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
VENV=${VENV:-.venv}

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating $VENV"
  "$PY" -m venv "$VENV"
fi
echo "==> installing python deps"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

if ! "$VENV/bin/python" -c "import weasyprint" >/dev/null 2>&1; then
  echo "==> WeasyPrint needs the pango/cairo system libraries."
  echo "    Debian/Ubuntu: sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 fonts-dejavu-core fonts-liberation"
  echo "    macOS:         brew install pango"
  echo "    ...or render with the browser engine instead:  make pdf ENGINE=chromium"
fi

if [ "${1:-}" = "chromium" ] || [ "${ENGINE:-}" = "chromium" ]; then
  echo "==> installing playwright chromium"
  "$VENV/bin/pip" install -q playwright
  "$VENV/bin/python" -m playwright install --with-deps chromium || "$VENV/bin/python" -m playwright install chromium
fi
echo "==> self-test (offline logic)"
"$VENV/bin/python" scripts/selftest.py || { echo "selftest failed"; exit 1; }
echo "ready. Next:  make pdf"
