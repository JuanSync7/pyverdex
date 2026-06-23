#!/usr/bin/env bash
# Launch the pyverify web app against the bundled demo project.
#
#   ./demo/run_demo.sh            # http://127.0.0.1:8000
#   PORT=9000 ./demo/run_demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.local/bin:$PATH"
# pick up an nvm node if present (frontend build only)
if [ -d "$HOME/.nvm/versions/node" ]; then
  NODE_DIR="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
  [ -n "${NODE_DIR:-}" ] && export PATH="$NODE_DIR:$PATH"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "[pyverify demo] syncing python env…"
uv sync >/dev/null

if [ ! -f src/pyverify/server/static/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "[pyverify demo] building web frontend…"
    ( cd web && npm install --no-fund --no-audit && npm run build )
  else
    echo "[pyverify demo] WARNING: frontend not built and npm not found — API only."
  fi
fi

echo "[pyverify demo] → http://$HOST:$PORT   (project: demo/sample_app)"
exec uv run pyverify serve demo/sample_app --host "$HOST" --port "$PORT"
