#!/usr/bin/env bash
# Build a macOS .app that launches Signal Browser without a terminal.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
  "$PYTHON" -m venv .venv
  PYTHON=".venv/bin/python"
fi
"$PYTHON" scripts/build_icon.py
"$PYTHON" -m pip install -e ".[app,pack]"
"$PYTHON" -m PyInstaller --noconfirm packaging/signal_browser.spec

echo "→ App bundle: dist/Signal Browser.app"
echo "  Drag it to /Applications, then open Signal Browser."
