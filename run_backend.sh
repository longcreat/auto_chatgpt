#!/usr/bin/env bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example"
  echo "Edit .env and run again."
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [ ! -x "$VENV_PY" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_PY" -m pip install --disable-pip-version-check --upgrade pip >/dev/null
"$VENV_PY" -m pip install --disable-pip-version-check -r "$ROOT/backend/requirements.txt"

cd "$ROOT/backend"
"$VENV_PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
