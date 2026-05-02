#!/usr/bin/env bash
set -euo pipefail

PORT="${WASM_UI_PORT:-8787}"
HOST="${WASM_UI_HOST:-127.0.0.1}"
RUN_PY="/local/scripts/public/ui-gateway/run.py"

if [[ ! -f "$RUN_PY" ]]; then
  echo "run.py not found at $RUN_PY" >&2
  exit 1
fi

existing_pids="$(ss -ltnp "( sport = :$PORT )" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)"
if [[ -n "$existing_pids" ]]; then
  echo "[wasm-ui] stopping process(es) on ${HOST}:${PORT}: $existing_pids"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
  done <<< "$existing_pids"

  for _ in $(seq 1 20); do
    if ! ss -ltn "( sport = :$PORT )" | grep -q ":$PORT "; then
      break
    fi
    sleep 0.25
  done
fi

export WASM_UI_EXPERIMENTAL="${WASM_UI_EXPERIMENTAL:-1}"

echo "[wasm-ui] starting on ${HOST}:${PORT}"
exec python3 "$RUN_PY"
