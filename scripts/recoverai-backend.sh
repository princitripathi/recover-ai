#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/recover-ai/backend"
VENV_DIR="$BACKEND_DIR/.venv"
STAMP_FILE="$VENV_DIR/.requirements.stamp"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

if [ ! -f "$STAMP_FILE" ] || [ "$REQUIREMENTS_FILE" -nt "$STAMP_FILE" ]; then
  "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS_FILE"
  touch "$STAMP_FILE"
fi

cd "$BACKEND_DIR"
exec "$VENV_DIR/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000
