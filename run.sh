#!/usr/bin/env bash
# One-command launcher for PyLibro.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${PYLIBRO_VENV_DIR:-$ROOT_DIR/.venv}"
VENV_PYTHON="$VENV_DIR/bin/python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "PyLibro requires Python 3.10 or newer, but '$PYTHON_BIN' was not found." >&2
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[PyLibro] Creating virtual environment in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_PYTHON" -m pip install --upgrade pip
fi

if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "PyLibro requires Python 3.10 or newer." >&2
  exit 1
fi

REQUIREMENTS_HASH="$("$VENV_PYTHON" -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("requirements.txt").read_bytes()).hexdigest())')"
STAMP_FILE="$VENV_DIR/.pylibro-requirements"
INSTALLED_HASH="$(cat "$STAMP_FILE" 2>/dev/null || true)"

if [[ "$REQUIREMENTS_HASH" != "$INSTALLED_HASH" ]]; then
  echo "[PyLibro] Installing application dependencies"
  "$VENV_PYTHON" -m pip install -r requirements.txt
  printf '%s\n' "$REQUIREMENTS_HASH" > "$STAMP_FILE"
fi

echo "[PyLibro] Starting on http://${PYLIBRO_HOST:-0.0.0.0}:${PYLIBRO_PORT:-8080}"
echo "[PyLibro] Press Ctrl+C here, or use the power button in the web app, to stop."
exec "$VENV_PYTHON" app.py
