#!/usr/bin/env bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
: "${FRONTEND_PORT:=5173}"

cd "$ROOT/frontend"
npm install
echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT}"
npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
