#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_pid=""

cleanup() {
  if [[ -n "$api_pid" ]]; then
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$project_root/backend"
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
ready=false
for _attempt in {1..30}; do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    echo 'The API stopped before it was ready. Check the error above.' >&2
    exit 1
  fi
  if curl --silent --fail http://127.0.0.1:8000/health >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo 'The API did not become ready within 30 seconds.' >&2
  exit 1
fi

cd "$project_root/frontend"
if [[ ! -d node_modules ]]; then
  npm ci
fi
printf '\nDashboard: http://localhost:5173\n'
printf 'Press Ctrl+C to stop the dashboard and API.\n\n'
npm run dev -- --host 127.0.0.1
